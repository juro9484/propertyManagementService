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
            # Compute max history price and price drop
            history = l.get("history", {})
            prices = [e.get("price", 0) for e in history.values() if e.get("price")]
            max_hist_price = max(prices) if prices else (l.get("price") or 0)
            current_price = l.get("price") or 0
            price_drop = round((max_hist_price - current_price) / max_hist_price * 100, 1) if max_hist_price > current_price else 0

            cur.execute("""
                INSERT INTO rental_listings (id, address, city, state, zip_code, county,
                    price, bedrooms, bathrooms, sqft, property_type,
                    days_on_market, listed_date, status, last_seen,
                    max_history_price, price_drop_pct, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    price = EXCLUDED.price,
                    days_on_market = EXCLUDED.days_on_market,
                    status = EXCLUDED.status,
                    last_seen = EXCLUDED.last_seen,
                    max_history_price = EXCLUDED.max_history_price,
                    price_drop_pct = EXCLUDED.price_drop_pct,
                    fetched_at = NOW()
            """, [
                l.get("id"),
                (l.get("addressLine1", "") + (" " + l.get("addressLine2", "") if l.get("addressLine2") else "")).strip(),
                l.get("city", ""),
                l.get("state", ""),
                l.get("zipCode", ""),
                l.get("county", ""),
                current_price,
                l.get("bedrooms"),
                l.get("bathrooms"),
                l.get("squareFootage"),
                l.get("propertyType"),
                l.get("daysOnMarket"),
                l.get("listedDate", "")[:10] if l.get("listedDate") else None,
                l.get("status"),
                l.get("lastSeenDate"),
                max_hist_price,
                price_drop,
            ])

    print(f"[RENTCAST] Stored {len(listings)} listings")


def _base_address(addr):
    """Strip unit number: '830 20TH ST #106' → '830 20TH ST'"""
    if not addr:
        return ""
    addr = addr.upper().strip()
    addr = re.sub(r'\s*(#|APT|UNIT|STE|SUITE)\s*\S*$', '', addr)
    return re.sub(r'\s+', ' ', addr).strip()


def _has_unit(addr):
    """Check if address contains a unit/apt number."""
    if not addr:
        return False
    return bool(re.search(r'(#|APT|UNIT|STE|SUITE)\s*\S', addr.upper()))


def _full_address(addr):
    """Normalize full address for matching (keep unit)."""
    if not addr:
        return ""
    return re.sub(r'\s+', ' ', addr.upper().strip())


def match_listings_to_leads(county="boulder"):
    """Match rental listings to leads and update vacancy scores.

    Matching rules:
      - House (no unit in listing or lead): match by base address
      - Apartment with unit in listing: match by full address including unit
      - Apartment without unit in listing but lead has unit: NO match (can't tell which unit)

    Returns number of leads matched.
    """
    with get_cursor() as cur:
        cur.execute("""
            SELECT address, city, zip_code, days_on_market, price,
                   rent_estimate, max_history_price, price_drop_pct
            FROM rental_listings
            WHERE days_on_market BETWEEN 1 AND 180
            AND fetched_at > NOW() - INTERVAL '10 days'
        """)
        listings = cur.fetchall()

    if not listings:
        print(f"[RENTCAST] No listings to match for {county}")
        return 0

    # Build lookups — full address and house-only maps
    # Each stores: {addr: {dom, zip, price_drop, overpriced_pct}}
    full_map = {}
    house_map = {}

    for l in listings:
        addr = (l["address"] or "").strip()
        dom = l["days_on_market"] or 0
        if not addr or dom < 1:
            continue

        full = _full_address(addr)
        base = _base_address(addr)

        listing_info = {
            "dom": dom,
            "zip": l.get("zip_code", ""),
            "price_drop": float(l.get("price_drop_pct") or 0),
            "rent_estimate": l.get("rent_estimate") or 0,
            "price": l.get("price") or 0,
        }
        # Compute overpriced %
        if listing_info["rent_estimate"] > 0 and listing_info["price"] > 0:
            listing_info["overpriced_pct"] = round(
                (listing_info["price"] - listing_info["rent_estimate"]) / listing_info["rent_estimate"] * 100, 1
            )
        else:
            listing_info["overpriced_pct"] = 0

        # Keep the worst (highest DOM) listing per address
        if full not in full_map or dom > full_map[full]["dom"]:
            full_map[full] = listing_info

        if not _has_unit(addr):
            if base not in house_map or dom > house_map[base]["dom"]:
                house_map[base] = listing_info

    print(f"[RENTCAST] {len(full_map)} full addresses, {len(house_map)} house addresses to match")

    # Match against lead_properties
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

        lead_data = {}
        for p in props:
            lid = p["lead_id"]
            if lid not in lead_data:
                lead_data[lid] = {
                    "doms": [],
                    "total_props": p["property_count"] or 1,
                    "is_new": p["is_new_owner"],
                    "best_zip": "",
                    "max_price_drop": 0,
                    "max_overpriced": 0,
                }

            prop_addr = (p["address"] or "").strip()
            prop_full = _full_address(prop_addr)
            prop_base = _base_address(prop_addr)
            prop_has_unit = _has_unit(prop_addr)

            # Match
            info = full_map.get(prop_full)
            if not info and not prop_has_unit:
                info = house_map.get(prop_base)

            if info and 15 <= info["dom"] <= 180:
                lead_data[lid]["doms"].append(info["dom"])
                if info["zip"]:
                    lead_data[lid]["best_zip"] = info["zip"]
                lead_data[lid]["max_price_drop"] = max(lead_data[lid]["max_price_drop"], info["price_drop"])
                lead_data[lid]["max_overpriced"] = max(lead_data[lid]["max_overpriced"], info["overpriced_pct"])

        # Calculate total struggle bonus
        for lead_id, data in lead_data.items():
            doms = sorted(data["doms"], reverse=True)
            if not doms:
                continue

            total_props = data["total_props"]
            is_new = data["is_new"]
            vacant_count = len(doms)
            vacancy_ratio = vacant_count / max(total_props, 1)

            breakdown = {}
            total_bonus = 0

            # DOM base
            best_dom = doms[0]
            if 15 <= best_dom < 45:
                b = round(12 * 0.55)  # 7
            elif 45 <= best_dom < 90:
                b = round(25 * 0.55)  # 14
            else:
                b = round(15 * 0.55)  # 8
            total_bonus += b
            breakdown[f"vacancy_{best_dom}d"] = b

            # Price drop from original
            drop_pct = data["max_price_drop"]
            if drop_pct >= 15:
                pb = round(10 * 0.55)  # 6
                total_bonus += pb
                breakdown[f"price_drop_{drop_pct:.0f}pct"] = pb
            elif drop_pct >= 5:
                pb = round(5 * 0.55)   # 3
                total_bonus += pb
                breakdown[f"price_drop_{drop_pct:.0f}pct"] = pb

            # Overpriced vs market comps
            over_pct = data["max_overpriced"]
            if over_pct >= 15:
                ob = round(10 * 0.55)  # 6
                total_bonus += ob
                breakdown[f"overpriced_{over_pct:.0f}pct"] = ob
            elif over_pct >= 5:
                ob = round(5 * 0.55)   # 3
                total_bonus += ob
                breakdown[f"overpriced_{over_pct:.0f}pct"] = ob

            # Multi-vacancy
            multi_bonus = 0
            if vacancy_ratio > 0.5 and not is_new:
                multi_bonus = 0
            else:
                extra = vacant_count - 1
                if extra >= 1: multi_bonus += 4
                if extra >= 2: multi_bonus += 4
                if extra >= 3: multi_bonus += 2
                multi_bonus = min(multi_bonus, 10)
            if multi_bonus > 0:
                total_bonus += multi_bonus
                breakdown["multi_vacancy"] = multi_bonus

            import json as json_mod
            cur.execute("""
                UPDATE leads SET
                    score = score + %s,
                    score_breakdown = score_breakdown || %s::jsonb,
                    badges = array_append(badges, 'VACANT'),
                    updated_at = NOW()
                WHERE id = %s
                AND NOT ('VACANT' = ANY(badges))
            """, [total_bonus, json_mod.dumps(breakdown), lead_id])

            if cur.rowcount > 0:
                matched += 1

    print(f"[RENTCAST] Matched {matched} leads with vacancy signals")
    return matched


def fetch_rent_estimates(api_key, county="boulder"):
    """Fetch rent estimates for vacant listings that don't have one yet.
    Only calls API for listings matched to leads (saves credits).
    """
    with get_cursor() as cur:
        cur.execute("""
            SELECT rl.id, rl.address, rl.city, rl.state, rl.zip_code,
                   rl.bedrooms, rl.property_type, rl.price
            FROM rental_listings rl
            WHERE rl.rent_estimate IS NULL
            AND rl.days_on_market BETWEEN 1 AND 180
            AND rl.fetched_at > NOW() - INTERVAL '10 days'
            AND rl.price IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM lead_properties lp
                JOIN leads l ON l.id = lp.lead_id
                WHERE l.county = %s
                AND UPPER(REGEXP_REPLACE(lp.address, '\s*(#|APT|UNIT|STE|SUITE)\s*\S*$', ''))
                  = UPPER(REGEXP_REPLACE(rl.address, '\s*(#|Apt|Unit|Ste|Suite)\s*\S*$', ''))
            )
            LIMIT 50
        """, [county])
        to_estimate = cur.fetchall()

    if not to_estimate:
        print(f"[RENTCAST] No listings need rent estimates for {county}")
        return 0

    estimated = 0
    calls = 0
    for listing in to_estimate:
        addr = f"{listing['address']}, {listing['city']}, {listing['state']} {listing['zip_code']}"
        prop_type = listing.get("property_type") or "Apartment"
        beds = listing.get("bedrooms") or 2

        try:
            resp = httpx.get(
                f"{RENTCAST_BASE}/avm/rent/long-term",
                headers={"X-Api-Key": api_key},
                params={
                    "address": addr,
                    "propertyType": prop_type,
                    "bedrooms": beds,
                    "compCount": 5,
                },
                timeout=15,
            )
            calls += 1

            if resp.status_code == 200:
                data = resp.json()
                rent_est = data.get("rent")
                if rent_est:
                    with get_cursor(commit=True) as cur:
                        cur.execute("""
                            UPDATE rental_listings SET
                                rent_estimate = %s,
                                rent_range_low = %s,
                                rent_range_high = %s
                            WHERE id = %s
                        """, [rent_est, data.get("rentRangeLow"), data.get("rentRangeHigh"), listing["id"]])
                    estimated += 1
            elif resp.status_code == 429:
                print(f"[RENTCAST] Rate limited during estimates — stopping")
                break

        except Exception as e:
            print(f"[RENTCAST] Estimate failed for {addr}: {e}")

    print(f"[RENTCAST] Fetched {estimated} rent estimates ({calls} API calls)")
    return calls


def run_rentcast(county="boulder"):
    """Full weekly flow: fetch listings → store → match → get comps for vacant."""
    api_key = os.environ.get("RENTCAST_API_KEY", "")
    if not api_key:
        print("[RENTCAST] No RENTCAST_API_KEY set — skipping")
        return {"ok": False, "error": "No API key"}

    print(f"\n[RENTCAST] Running for {county}")
    listings, calls = fetch_listings(api_key, county)
    store_listings(listings)
    matched = match_listings_to_leads(county)

    # Fetch rent estimates for matched vacant listings (extra API calls)
    est_calls = fetch_rent_estimates(api_key, county)
    calls += est_calls

    # Re-match to pick up overpriced signals from new estimates
    if est_calls > 0:
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
