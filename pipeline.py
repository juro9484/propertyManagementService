#!/usr/bin/env python3
"""
Property Management Lead Generation Pipeline
Boulder County, Colorado

Processes public property records to identify high-value landlord leads
and generates mocked realtor prospect data.

Usage:
    python pipeline.py

Reads:
    data/boulder_records.csv         - Current property records
    data/previous_boulder_records.csv - Previous snapshot for new-owner detection

Writes:
    public/data/landlord_leads.json  - Top 50 scored landlord leads
    public/data/realtor_leads.json   - 20 mocked realtor prospects
    data/previous_boulder_records.csv - Updated snapshot for next run
"""

import csv
import io
import json
import os
import shutil
import random
import urllib.request
from datetime import datetime
from collections import Counter, defaultdict
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────────
DATA_DIR        = Path("data")
PUBLIC_DATA_DIR = Path("public/data")
CURRENT_CSV     = DATA_DIR / "boulder_records.csv"
PREVIOUS_CSV    = DATA_DIR / "previous_boulder_records.csv"
LANDLORD_OUTPUT = PUBLIC_DATA_DIR / "landlord_leads.json"
REALTOR_OUTPUT  = PUBLIC_DATA_DIR / "realtor_leads.json"

PUBLIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Scoring constants ────────────────────────────────────────────────────────
LLC_KEYWORDS    = ["LLC", "LP", "HOLDINGS", "PROPERTIES", "INVESTMENTS",
                   "GROUP", "TRUST", "REALTY", "VENTURES", "PARTNERS",
                   "CAPITAL", "ASSETS", "ENTERPRISES", "MANAGEMENT"]
RENTAL_ACCT     = ["MULTI_FAMILY", "APARTMENT", "DUPLEX", "TRIPLEX",
                   "CONDO", "TOWNHOME", "RESIDENTIAL RENTAL"]

random.seed(42)


# ── Scoring logic ────────────────────────────────────────────────────────────
def has_llc_signal(name: str) -> bool:
    up = name.upper()
    return any(kw in up for kw in LLC_KEYWORDS)


def score_lead(owner_name: str, prop_city: str, mail_city: str,
               mail_state: str, prop_count: int, acct_type: str,
               is_new: bool) -> tuple[int, list[str], dict]:
    score = 0
    badges: list[str] = []
    breakdown: dict = {}

    # LLC / entity signal (+4)
    if has_llc_signal(owner_name):
        score += 4
        badges.append("LLC")
        breakdown["llc_signal"] = 4

    # Out-of-state owner (+5) — supersedes absentee
    if mail_state and mail_state.upper() not in ("CO", ""):
        score += 5
        badges.append("OUT_OF_STATE")
        breakdown["out_of_state"] = 5
    # Absentee owner — same state, different city (+3)
    elif (mail_city and prop_city and
          mail_city.strip().upper() != prop_city.strip().upper()):
        score += 3
        badges.append("ABSENTEE")
        breakdown["absentee"] = 3

    # Multiple properties (+3 for 3-4, +6 for 5+)
    if 3 <= prop_count <= 4:
        score += 3
        badges.append("MULTI_PROP")
        breakdown["multi_property"] = 3
    elif prop_count >= 5:
        score += 6
        badges.append("PORTFOLIO")
        breakdown["portfolio"] = 6

    # Rental account type (+2)
    at_up = acct_type.upper()
    if any(r in at_up for r in RENTAL_ACCT):
        score += 2
        breakdown["rental_type"] = 2

    # New owner bonus (+5)
    if is_new:
        score += 5
        badges.append("NEW_OWNER")
        breakdown["new_owner"] = 5

    return score, badges, breakdown


# ── CSV loading ──────────────────────────────────────────────────────────────
def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append({k.strip(): v.strip() for k, v in row.items() if k is not None})
    return records


def detect_new_owners(current: list[dict], previous: list[dict]) -> set[str]:
    """Return set of folios where an owner_name appeared that wasn't present before.

    Uses sets-per-folio so that multi-row folios (e.g. mobile-home parks with
    one folio shared across the land owner + every individual unit) don't
    generate false positives when individual units turnover.  A folio is only
    flagged when a current owner name does not appear anywhere in the previous
    owner set for that same folio AND the folio existed in the previous snapshot.
    """
    from collections import defaultdict
    prev_by_folio: dict[str, set[str]] = defaultdict(set)
    for r in previous:
        folio = r.get("folio", "")
        owner = r.get("owner_name", "")
        if folio and owner:
            prev_by_folio[folio].add(owner)

    changed: set[str] = set()
    for rec in current:
        folio = rec.get("folio", "")
        owner = rec.get("owner_name", "")
        prev_owners = prev_by_folio.get(folio)
        # Only flag if folio existed before AND this specific owner is brand-new
        if prev_owners is not None and owner and owner not in prev_owners:
            changed.add(folio)
    return changed


def build_address(rec: dict) -> str:
    parts = [
        rec.get("str_num", ""),
        rec.get("str_pfx", ""),
        rec.get("str", ""),
        rec.get("str_sfx", ""),
    ]
    addr = " ".join(p for p in parts if p).strip()
    unit = rec.get("str_unit", "")
    if unit:
        addr += f" #{unit}"
    return addr


# ── Landlord lead processing ─────────────────────────────────────────────────
def process_landlord_leads(records: list[dict],
                           new_owner_folios: set[str]) -> list[dict]:
    # Group by owner_name
    by_owner: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        owner = rec.get("owner_name", "").strip()
        if owner:
            by_owner[owner].append(rec)

    leads = []
    for owner_name, recs in by_owner.items():
        primary = recs[0]
        prop_count  = len(recs)
        folio       = primary.get("folio", "")
        is_new      = folio in new_owner_folios
        prop_city   = primary.get("city", "").strip()
        mail_city   = primary.get("mailingCity", "").strip()
        mail_state  = primary.get("mailingState", "").strip()
        acct_type   = primary.get("account_type", "").strip()

        score, badges, breakdown = score_lead(
            owner_name, prop_city, mail_city,
            mail_state, prop_count, acct_type, is_new
        )

        mail_addr1 = primary.get("mailingAddr1", "")
        mail_zip   = primary.get("mailingZip", "")
        full_mail  = f"{mail_addr1}, {mail_city}, {mail_state} {mail_zip}".strip(", ")

        all_props = []
        for r in recs:
            all_props.append({
                "folio":       r.get("folio", ""),
                "address":     build_address(r),
                "city":        r.get("city", ""),
                "account_type": r.get("account_type", ""),
                "tax_area":    r.get("taxArea", ""),
                "is_new_owner": r.get("folio", "") in new_owner_folios,
            })

        leads.append({
            "rank":             0,
            "owner_name":       owner_name,
            "folio":            folio,
            "property_address": build_address(primary),
            "city":             prop_city,
            "mailing_address":  full_mail,
            "mailing_city":     mail_city,
            "mailing_state":    mail_state,
            "score":            score,
            "badges":           badges,
            "is_new_owner":     is_new,
            "property_count":   prop_count,
            "account_type":     acct_type,
            "legal_description": primary.get("legalDscr", ""),
            "tax_area":         primary.get("taxArea", ""),
            "score_breakdown":  breakdown,
            "all_properties":   all_props,
        })

    leads.sort(key=lambda x: x["score"], reverse=True)
    for i, lead in enumerate(leads[:50]):
        lead["rank"] = i + 1
    return leads[:50]


# ── Mocked fallback data ─────────────────────────────────────────────────────
def generate_mocked_landlord_leads() -> list[dict]:
    """Fallback mocked data when CSV is not present."""
    entries = [
        ("Pacific Rim Holdings LLC",         "2847 Iris Ave",       "Boulder",    "Seattle",      "WA", 7,  "MULTI_FAMILY"),
        ("Boulder Valley Properties LLC",    "1415 Pearl St",       "Boulder",    "Denver",       "CO", 6,  "MULTI_FAMILY"),
        ("Chen Properties Trust",            "3301 Arapahoe Ave",   "Boulder",    "San Francisco","CA", 5,  "RESIDENTIAL"),
        ("Front Range Capital LP",           "889 28th St",         "Boulder",    "Denver",       "CO", 4,  "MULTI_FAMILY"),
        ("Mountain West Investments Group",  "4210 Table Mesa Dr",  "Boulder",    "Los Angeles",  "CA", 3,  "RESIDENTIAL"),
        ("Sunset Holdings LLC",              "711 Main St",         "Longmont",   "Phoenix",      "AZ", 2,  "MULTI_FAMILY"),
        ("Northern Colorado Properties LP",  "3042 Baseline Rd",    "Boulder",    "Loveland",     "CO", 4,  "RESIDENTIAL"),
        ("Rocky Mountain Realty Group LLC",  "1820 Folsom St",      "Boulder",    "Boulder",      "CO", 3,  "MULTI_FAMILY"),
        ("Skyline Assets LLC",               "620 Canyon Blvd",     "Boulder",    "Chicago",      "IL", 5,  "MULTI_FAMILY"),
        ("Apex Real Estate Ventures LLC",    "1105 Broadway",       "Boulder",    "Dallas",       "TX", 3,  "RESIDENTIAL"),
        ("Williams Katherine A",             "445 Mapleton Ave",    "Boulder",    "Austin",       "TX", 1,  "RESIDENTIAL"),
        ("Smith Michael D & Renee L",        "2230 Linden Dr",      "Boulder",    "Boulder",      "CO", 1,  "RESIDENTIAL"),
        ("Green Pines Investments LLC",      "910 9th St",          "Boulder",    "Portland",     "OR", 4,  "MULTI_FAMILY"),
        ("Johnson Robert T",                 "1634 Spruce St",      "Boulder",    "Thornton",     "CO", 2,  "RESIDENTIAL"),
        ("Lafayette Property Trust",         "325 W South Boulder", "Lafayette",  "Denver",       "CO", 3,  "RESIDENTIAL"),
        ("Flatiron Capital Group LLC",       "2100 Baseline Rd",    "Boulder",    "New York",     "NY", 6,  "MULTI_FAMILY"),
        ("Reynolds Thomas W",                "545 Iris Ave",        "Boulder",    "Louisville",   "CO", 1,  "RESIDENTIAL"),
        ("Erie Landlord Group LLC",          "714 Miner Way",       "Erie",       "Erie",         "CO", 2,  "RESIDENTIAL"),
        ("Blue Sky Properties Trust",        "3401 Iris Ave",       "Boulder",    "Miami",        "FL", 3,  "MULTI_FAMILY"),
        ("Hernandez Carlos & Maria",         "1102 9th Ave",        "Longmont",   "Longmont",     "CO", 1,  "RESIDENTIAL"),
        ("Superior Rentals LLC",             "601 Coal Creek Dr",   "Superior",   "Denver",       "CO", 4,  "MULTI_FAMILY"),
        ("Anderson James P",                 "3318 9th St",         "Boulder",    "Nashville",    "TN", 1,  "RESIDENTIAL"),
        ("Alpine Holdings LP",               "2005 30th St",        "Boulder",    "Denver",       "CO", 5,  "MULTI_FAMILY"),
        ("Turnberry Real Estate LLC",        "410 Kimbark St",      "Longmont",   "Los Angeles",  "CA", 3,  "RESIDENTIAL"),
        ("Boulder Creek Properties Group",   "1788 Broadway",       "Boulder",    "Boulder",      "CO", 7,  "MULTI_FAMILY"),
        ("Pacific Coast Real Estate LLC",    "511 University Ave",  "Boulder",    "San Diego",    "CA", 8,  "MULTI_FAMILY"),
        ("Garcia Investments LLC",           "2912 Marine St",      "Boulder",    "Houston",      "TX", 2,  "RESIDENTIAL"),
        ("Lakeview Partners LLC",            "1414 Euclid Ave",     "Boulder",    "Chicago",      "IL", 4,  "MULTI_FAMILY"),
        ("Kim David & Susan Trust",          "3750 28th St",        "Boulder",    "Denver",       "CO", 3,  "RESIDENTIAL"),
        ("Patel Raj Enterprise LLC",         "1600 Pearl St",       "Boulder",    "Mumbai",       "",   5,  "MULTI_FAMILY"),
    ]

    now_ts = datetime.now().isoformat(timespec="seconds")
    leads = []
    folio_base = 1000000
    for i, (owner, addr, city, mail_city, mail_state, count, acct) in enumerate(entries):
        is_new = i < 4
        score, badges, breakdown = score_lead(
            owner, city, mail_city, mail_state, count, acct, is_new
        )
        mail_addr = f"{random.randint(100,9999)} {random.choice(['Main','Oak','Elm','Pine','Cedar'])} St"
        mail_zip  = f"{random.randint(10000,99999)}"
        full_mail = f"{mail_addr}, {mail_city}, {mail_state} {mail_zip}".strip(", ")
        leads.append({
            "rank":             i + 1,
            "owner_name":       owner,
            "folio":            str(folio_base + i),
            "property_address": addr,
            "city":             city,
            "mailing_address":  full_mail,
            "mailing_city":     mail_city,
            "mailing_state":    mail_state,
            "score":            score,
            "badges":           badges,
            "is_new_owner":     is_new,
            "property_count":   count,
            "account_type":     acct,
            "legal_description": f"BLK {random.randint(1,20)} LOT {random.randint(1,40)} SUBDIVISION",
            "tax_area":         f"0{random.randint(100,400)}",
            "score_breakdown":  breakdown,
            "all_properties": [{
                "folio":        str(folio_base + i),
                "address":      addr,
                "city":         city,
                "account_type": acct,
                "tax_area":     f"0{random.randint(100,400)}",
                "is_new_owner": is_new,
            }],
        })
    leads.sort(key=lambda x: x["score"], reverse=True)
    for i, lead in enumerate(leads):
        lead["rank"] = i + 1
    return leads[:50]


# ── Realtor lead generation (mocked) ────────────────────────────────────────
def generate_realtor_leads() -> list[dict]:
    brokerages = [
        "Keller Williams Boulder",
        "RE/MAX of Boulder",
        "Coldwell Banker Realty",
        "8z Real Estate",
        "West + Main Homes",
        "Compass Colorado",
        "Equity Colorado",
    ]
    specialties_pool = [
        "Multi-family", "Investment Properties", "1031 Exchange",
        "Buy & Hold Strategy", "Fix & Flip", "Short-term Rentals",
        "Commercial Mixed-Use", "Student Housing", "Vacation Rentals",
        "New Construction", "Value-Add Properties", "NNN Leases",
    ]
    first_names = ["Sarah", "James", "Amanda", "David", "Jennifer", "Michael",
                   "Lisa", "Robert", "Stephanie", "Carlos", "Megan", "Brandon",
                   "Allison", "Tyler", "Nicole", "Derek", "Brittany", "Nathan",
                   "Erica", "Marcus"]
    last_names  = ["Mitchell", "Patterson", "Torres", "Kim", "Walsh", "Brennan",
                   "Chen", "Hughes", "Moore", "Rivera", "Harper", "Stone",
                   "Foster", "Nguyen", "Patel", "Reeves", "Lawson", "Ortiz",
                   "Coleman", "Barnes"]

    score_map = {range(18, 30): "High", range(12, 18): "High",
                 range(8, 12): "Medium", range(0, 8): "Low"}

    def get_score_tier(n: int) -> str:
        if n >= 18: return "High"
        if n >= 12: return "Medium"
        return "Low"

    realtors = []
    used_names: set[str] = set()
    for i in range(20):
        while True:
            fn = random.choice(first_names)
            ln = random.choice(last_names)
            full = f"{fn} {ln}"
            if full not in used_names:
                used_names.add(full)
                break

        brokerage    = random.choice(brokerages)
        inv_listings = random.randint(5, 25)
        score_tier   = get_score_tier(inv_listings)
        specs        = random.sample(specialties_pool, random.randint(2, 4))
        phone_area   = random.choice(["303", "720"])
        phone        = f"({phone_area}) {random.randint(200,999)}-{random.randint(1000,9999)}"
        slug         = fn.lower() + "." + ln.lower()
        brok_slug    = brokerage.lower().replace(" ", "").replace("+", "").replace("/", "")
        email        = f"{slug}@{brok_slug}.com"

        if score_tier == "High":
            urgency = "I'd love to schedule a quick coffee chat this week"
            value   = f"With {inv_listings} investor transactions under your belt, I know your clients are always looking for reliable management solutions"
        elif score_tier == "Medium":
            urgency = "I'd love to connect when you have a moment"
            value   = f"Your {inv_listings} investor deals show you understand the buy-and-hold market"
        else:
            urgency = "I'd love to introduce myself"
            value   = f"Your work in the investment space caught my eye"

        outreach = f"""Subject: Referral Partnership Opportunity — {brokerage}

Hi {fn},

I came across your profile and was impressed by your {inv_listings} investor {"transaction" if inv_listings == 1 else "transactions"} in the Boulder County area. {value}, and I wanted to reach out about a potential referral partnership.

I run a boutique property management firm focused exclusively on Boulder County. When your investor clients close, they often need someone they can trust to handle leasing, tenant screening, maintenance, and rent collection — without the headaches.

Here's what I can offer your clients:
• Guaranteed rent collection with direct deposit
• 24/7 maintenance coordination
• Detailed monthly owner statements
• Local Boulder County expertise

In return, I'd love to refer buyers and property owners to you when they're ready to expand their portfolios.

{urgency} — I'm flexible on timing. Would a 15-minute call work this week?

Best,
[Your Name]
Peak Property Management — Boulder County
(303) 555-0100 | www.peakpropertyco.com"""

        realtors.append({
            "id":               i + 1,
            "name":             full,
            "brokerage":        brokerage,
            "phone":            phone,
            "email":            email,
            "investor_listings": inv_listings,
            "specialties":      specs,
            "score":            score_tier,
            "outreach_email":   outreach,
        })

    realtors.sort(key=lambda x: x["investor_listings"], reverse=True)
    for i, r in enumerate(realtors):
        r["id"] = i + 1
    return realtors


# ── Geocoding ────────────────────────────────────────────────────────────────
def geocode_leads(leads: list[dict]) -> None:
    """Geocode all property addresses using US Census Geocoder batch API.
    Mutates leads and their all_properties items in-place adding lat/lng.
    Uses address as the batch key (deduped) so each unique street address
    is only sent once even when shared across multiple units.
    """
    if not leads:
        return

    # Collect every unique base address across all properties
    # key: (base_address, city) → list of (lead, prop_or_none) to update
    import re
    def base_addr(s):
        return re.sub(r'\s+(#|APT|UNIT|STE|SUITE|FL|FLOOR)\b.*', '', (s or '').upper()).strip()

    # addr_key → list of objects to stamp with lat/lng
    addr_targets: dict[str, list] = {}
    for lead in leads:
        for prop in lead.get('all_properties') or [lead]:
            addr = base_addr(prop.get('address') or lead.get('property_address', ''))
            city = (prop.get('city') or lead.get('city', '')).strip()
            key  = f"{addr}|{city}"
            addr_targets.setdefault(key, []).append(prop)
        # Also stamp the lead-level coords from primary property
        primary_addr = base_addr(lead.get('property_address', ''))
        primary_city = lead.get('city', '').strip()
        addr_targets.setdefault(f"{primary_addr}|{primary_city}", []).append(lead)

    # Build CSV with one row per unique address (use index as ID)
    unique_keys = list(addr_targets.keys())
    buf = io.StringIO()
    w = csv.writer(buf)
    for idx, key in enumerate(unique_keys):
        addr, city = key.split('|', 1)
        w.writerow([str(idx), addr, city, 'CO', ''])
    csv_bytes = buf.getvalue().encode('utf-8')

    boundary = 'CensusGeoBoundary7a3f9'
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="benchmark"\r\n\r\n'
        f'Public_AR_Current\r\n'
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="addressFile"; filename="addresses.csv"\r\n'
        f'Content-Type: text/csv\r\n\r\n'
    ).encode() + csv_bytes + f'\r\n--{boundary}--\r\n'.encode()

    req = urllib.request.Request(
        'https://geocoding.geo.census.gov/geocoder/locations/addressbatch',
        data=body,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
        method='POST',
    )

    coord_map: dict[str, tuple[float, float]] = {}
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = resp.read().decode('utf-8')
        reader = csv.reader(io.StringIO(result))
        for row in reader:
            if len(row) >= 6 and row[2].strip() == 'Match':
                idx_str  = row[0].strip()
                coord_str = row[5].strip()
                if ',' in coord_str:
                    lon_s, lat_s = coord_str.split(',', 1)
                    try:
                        coord_map[idx_str] = (float(lat_s.strip()), float(lon_s.strip()))
                    except ValueError:
                        pass
    except Exception as e:
        print(f'[WARN] Geocoding failed: {e}')
        return

    matched = 0
    for idx, key in enumerate(unique_keys):
        if str(idx) in coord_map:
            lat, lng = coord_map[str(idx)]
            for obj in addr_targets[key]:
                obj['lat'] = lat
                obj['lng'] = lng
            matched += 1
    print(f'[INFO] Geocoded {matched}/{len(unique_keys)} unique addresses')


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Boulder County Lead Generation Pipeline")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Load data
    current  = load_csv(CURRENT_CSV)
    previous = load_csv(PREVIOUS_CSV)

    if not current:
        print(f"\n[WARN] {CURRENT_CSV} not found — using mocked landlord data.\n")
        landlord_leads   = generate_mocked_landlord_leads()
        total_processed  = len(landlord_leads)
        new_owner_count  = sum(1 for l in landlord_leads if l["is_new_owner"])
    else:
        print(f"[INFO] Loaded {len(current)} records from {CURRENT_CSV}")
        new_owner_folios = detect_new_owners(current, previous)
        print(f"[INFO] Detected {len(new_owner_folios)} new-owner events")
        landlord_leads   = process_landlord_leads(current, new_owner_folios)
        total_processed  = len(current)
        new_owner_count  = len(new_owner_folios)
        geocode_leads(landlord_leads)

    # Realtor leads (always mocked)
    realtor_leads = generate_realtor_leads()
    print(f"[INFO] Generated {len(realtor_leads)} realtor prospects")

    # Compute avg score
    scores    = [l["score"] for l in landlord_leads]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    # Write landlord output
    landlord_payload = {
        "generated_at":         datetime.now().isoformat(timespec="seconds"),
        "total_records_processed": total_processed,
        "new_owner_events":     new_owner_count,
        "avg_score":            avg_score,
        "leads":                landlord_leads,
    }
    with open(LANDLORD_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(landlord_payload, f, indent=2)
    print(f"[OK]   Wrote {len(landlord_leads)} landlord leads → {LANDLORD_OUTPUT}")

    # Write realtor output
    realtor_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "realtors":     realtor_leads,
    }
    with open(REALTOR_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(realtor_payload, f, indent=2)
    print(f"[OK]   Wrote {len(realtor_leads)} realtor leads → {REALTOR_OUTPUT}")

    # Snapshot current → previous
    if CURRENT_CSV.exists():
        shutil.copy2(CURRENT_CSV, PREVIOUS_CSV)
        print(f"[OK]   Snapshot saved → {PREVIOUS_CSV}")

    print("\n  Pipeline complete.\n")


if __name__ == "__main__":
    main()
