"""
RentCast integration — fetches rental listings to identify vacant properties.

Runs weekly. Matches listing addresses to leads and boosts scores
for landlords with properties sitting vacant.

Scoring signals:
  15-45 days on market  → +2 (mild struggle)
  45-90 days on market  → +5 (genuinely struggling)
  90-180 days on market → +3 (real problem, but might be stale)
  180+ days             → ignored (ghost listing)
"""

import os
import re
import httpx
from datetime import datetime
from db import get_cursor

RENTCAST_BASE = "https://api.rentcast.io/v1"

# Boulder County zip codes
BOULDER_ZIPS = [
    "80301", "80302", "80303", "80304", "80305",
    "80310", "80314", "80401", "80501", "80503",
    "80504", "80510", "80513", "80516", "80540",
]

# Larimer County (Fort Collins area) zip codes
LARIMER_ZIPS = [
    "80521", "80524", "80525", "80526", "80528",
    "80537", "80538", "80547", "80549", "80550",
]

COUNTY_ZIPS = {
    "boulder": BOULDER_ZIPS,
    "larimer": LARIMER_ZIPS,
}


def fetch_listings(api_key, county="boulder"):
    """Fetch all active rental listings for a county's zip codes.
    Returns list of listings and number of API calls used.
    """
    zips = COUNTY_ZIPS.get(county, [])
    all_listings = []
    calls = 0

    for zip_code in zips:
        try:
            resp = httpx.get(
                f"{RENTCAST_BASE}/listings/rental/long-term",
                headers={"X-Api-Key": api_key},
                params={"zipCode": zip_code, "status": "Active", "limit": 500},
                timeout=20,
            )
            calls += 1

            if resp.status_code == 200:
                listings = resp.json()
                # Filter: only 1-180 days on market (skip ghost listings)
                valid = [l for l in listings if 1 <= (l.get("daysOnMarket") or 0) <= 180]
                all_listings.extend(valid)
                print(f"[RENTCAST] {zip_code}: {len(listings)} listings, {len(valid)} valid (1-180 DOM)")
            elif resp.status_code == 429:
                print(f"[RENTCAST] Rate limited at {zip_code} — stopping")
                break
            else:
                print(f"[RENTCAST] {zip_code}: error {resp.status_code}")

        except Exception as e:
            print(f"[RENTCAST] {zip_code}: failed — {e}")

    print(f"[RENTCAST] {county}: {len(all_listings)} valid listings from {calls} API calls")
    return all_listings, calls


def store_listings(listings):
    """Upsert listings into the rental_listings table."""
    if not listings:
        return

    with get_cursor(commit=True) as cur:
        for l in listings:
            cur.execute("""
                INSERT INTO rental_listings (id, address, city, state, zip_code, county,
                    price, bedrooms, bathrooms, sqft, property_type,
                    days_on_market, listed_date, status, last_seen, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    price = EXCLUDED.price,
                    days_on_market = EXCLUDED.days_on_market,
                    status = EXCLUDED.status,
                    last_seen = EXCLUDED.last_seen,
                    fetched_at = NOW()
            """, [
                l.get("id"),
                l.get("addressLine1", ""),
                l.get("city", ""),
                l.get("state", ""),
                l.get("zipCode", ""),
                l.get("county", ""),
                l.get("price"),
                l.get("bedrooms"),
                l.get("bathrooms"),
                l.get("squareFootage"),
                l.get("propertyType"),
                l.get("daysOnMarket"),
                l.get("listedDate", "")[:10] if l.get("listedDate") else None,
                l.get("status"),
                l.get("lastSeenDate"),
            ])

    print(f"[RENTCAST] Stored {len(listings)} listings")


def _normalize_address(addr):
    """Normalize address for matching: uppercase, strip unit, standardize."""
    if not addr:
        return ""
    addr = addr.upper().strip()
    addr = re.sub(r'\s+(#|APT|UNIT|STE|SUITE)\s*\S*', '', addr)
    addr = re.sub(r'\s+', ' ', addr)
    return addr


def match_listings_to_leads(county="boulder"):
    """Match rental listings to leads and update vacancy scores.
    Returns number of leads matched.
    """
    with get_cursor() as cur:
        # Get all valid listings for this county
        cur.execute("""
            SELECT address, city, days_on_market, price
            FROM rental_listings
            WHERE days_on_market BETWEEN 1 AND 180
            AND fetched_at > NOW() - INTERVAL '10 days'
        """)
        listings = cur.fetchall()

    if not listings:
        print(f"[RENTCAST] No listings to match for {county}")
        return 0

    # Build lookup: normalized address → best (highest) DOM
    listing_map = {}
    for l in listings:
        norm = _normalize_address(l["address"])
        if not norm:
            continue
        existing = listing_map.get(norm, 0)
        listing_map[norm] = max(existing, l["days_on_market"] or 0)

    print(f"[RENTCAST] {len(listing_map)} unique addresses to match")

    # Match against lead_properties — track ALL vacant props per lead
    matched = 0
    with get_cursor(commit=True) as cur:
        cur.execute("""
            SELECT lp.lead_id, lp.address, l.property_count,
                   l.created_at > NOW() - INTERVAL '60 days' as is_new_owner
            FROM lead_properties lp
            JOIN leads l ON l.id = lp.lead_id
            WHERE l.county = %s
        """, [county])
        props = cur.fetchall()

        # Build per-lead vacancy data: {lead_id: {doms: [list], total_props: N, is_new: bool}}
        lead_data = {}
        for p in props:
            lid = p["lead_id"]
            if lid not in lead_data:
                lead_data[lid] = {
                    "doms": [],
                    "total_props": p["property_count"] or 1,
                    "is_new": p["is_new_owner"],
                }
            norm = _normalize_address(p["address"])
            dom = listing_map.get(norm, 0)
            if 15 <= dom <= 180:
                lead_data[lid]["doms"].append(dom)

        # Calculate vacancy bonus with multi-vacancy and ratio check
        for lead_id, data in lead_data.items():
            doms = sorted(data["doms"], reverse=True)
            if not doms:
                continue

            total_props = data["total_props"]
            is_new = data["is_new"]
            vacant_count = len(doms)
            vacancy_ratio = vacant_count / max(total_props, 1)

            # Base bonus from worst (longest) vacancy
            best_dom = doms[0]
            if 15 <= best_dom < 45:
                base = round(12 * 0.55)    # 7
            elif 45 <= best_dom < 90:
                base = round(25 * 0.55)    # 14
            else:
                base = round(15 * 0.55)    # 8

            # Multi-vacancy bonus: +4, +4, +2 (capped at +10)
            multi_bonus = 0
            if vacancy_ratio > 0.5 and not is_new:
                # Suspicious — likely stale data. No multi-bonus.
                multi_bonus = 0
            else:
                extra = vacant_count - 1
                if extra >= 1: multi_bonus += 4
                if extra >= 2: multi_bonus += 4
                if extra >= 3: multi_bonus += 2
                # Cap at 10
                multi_bonus = min(multi_bonus, 10)

            total_bonus = base + multi_bonus

            detail = f"vacancy_{best_dom}d"
            if vacant_count > 1:
                detail += f"_x{vacant_count}"

            cur.execute("""
                UPDATE leads SET
                    score = score + %s,
                    score_breakdown = score_breakdown || %s::jsonb,
                    badges = array_append(badges, 'VACANT'),
                    updated_at = NOW()
                WHERE id = %s
                AND NOT ('VACANT' = ANY(badges))
            """, [total_bonus, f'{{"{detail}": {total_bonus}}}', lead_id])

            if cur.rowcount > 0:
                matched += 1

    print(f"[RENTCAST] Matched {matched} leads with vacancy signals")
    return matched


def run_rentcast(county="boulder"):
    """Full weekly flow: fetch listings → store → match to leads."""
    api_key = os.environ.get("RENTCAST_API_KEY", "")
    if not api_key:
        print("[RENTCAST] No RENTCAST_API_KEY set — skipping")
        return {"ok": False, "error": "No API key"}

    print(f"\n[RENTCAST] Running for {county}")
    listings, calls = fetch_listings(api_key, county)
    store_listings(listings)
    matched = match_listings_to_leads(county)

    return {
        "ok": True,
        "county": county,
        "listings_fetched": len(listings),
        "api_calls": calls,
        "leads_matched": matched,
    }


def run_all_counties():
    """Run RentCast for all counties."""
    results = []
    for county in COUNTY_ZIPS:
        result = run_rentcast(county)
        results.append(result)
    return results
