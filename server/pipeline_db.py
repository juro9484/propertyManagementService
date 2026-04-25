"""
Pipeline — Database version

Same scoring logic as pipeline.py but writes to PostgreSQL instead of JSON files.
Called by the /api/pipeline/run endpoint or by the daily cron scheduler.
"""

import csv
import io
import os
import re
import urllib.request
from datetime import datetime
from collections import defaultdict
from pathlib import Path

from db import get_cursor

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR    = Path(__file__).parent.parent / "data"
CURRENT_CSV = DATA_DIR / "boulder_records.csv"

# ── Scoring constants (identical to pipeline.py) ─────────────────────────────
LLC_KEYWORDS = [
    "LLC", "LP", "HOLDINGS", "PROPERTIES", "INVESTMENTS",
    "GROUP", "TRUST", "REALTY", "VENTURES", "PARTNERS",
    "CAPITAL", "ASSETS", "ENTERPRISES", "MANAGEMENT",
]
RENTAL_ACCT = [
    "MULTI_FAMILY", "APARTMENT", "DUPLEX", "TRIPLEX",
    "CONDO", "TOWNHOME", "RESIDENTIAL RENTAL",
]


def has_llc_signal(name: str) -> bool:
    return any(kw in name.upper() for kw in LLC_KEYWORDS)


def score_lead(owner_name, prop_city, mail_city, mail_state, prop_count, acct_type, is_new):
    score = 0
    badges = []
    breakdown = {}

    if has_llc_signal(owner_name):
        score += 4; badges.append("LLC"); breakdown["llc_signal"] = 4

    if mail_state and mail_state.upper() not in ("CO", ""):
        score += 5; badges.append("OUT_OF_STATE"); breakdown["out_of_state"] = 5
    elif mail_city and prop_city and mail_city.strip().upper() != prop_city.strip().upper():
        score += 3; badges.append("ABSENTEE"); breakdown["absentee"] = 3

    if 3 <= prop_count <= 4:
        score += 3; badges.append("MULTI_PROP"); breakdown["multi_property"] = 3
    elif prop_count >= 5:
        score += 6; badges.append("PORTFOLIO"); breakdown["portfolio"] = 6

    if any(r in acct_type.upper() for r in RENTAL_ACCT):
        score += 2; breakdown["rental_type"] = 2

    if is_new:
        score += 5; badges.append("NEW_OWNER"); breakdown["new_owner"] = 5

    return score, badges, breakdown


def build_address(rec: dict) -> str:
    parts = [rec.get("str_num", ""), rec.get("str_pfx", ""), rec.get("str", ""), rec.get("str_sfx", "")]
    addr = " ".join(p for p in parts if p).strip()
    unit = rec.get("str_unit", "")
    if unit:
        addr += f" #{unit}"
    return addr


def base_addr(s):
    return re.sub(r'\s+(#|APT|UNIT|STE|SUITE|FL|FLOOR)\b.*', '', (s or '').upper()).strip()


# ── Geocoding ─────────────────────────────────────────────────────────────────
def geocode_addresses(addr_list):
    """Geocode a list of (address, city) tuples. Returns {addr|city: (lat, lng)}."""
    if not addr_list:
        return {}

    buf = io.StringIO()
    w = csv.writer(buf)
    for idx, (addr, city) in enumerate(addr_list):
        w.writerow([str(idx), addr, city, 'CO', ''])

    csv_bytes = buf.getvalue().encode('utf-8')
    boundary = 'CensusGeoBoundary7a3f9'
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="benchmark"\r\n\r\n'
        f'Public_AR_Current\r\n--{boundary}\r\n'
        f'Content-Disposition: form-data; name="addressFile"; filename="addresses.csv"\r\n'
        f'Content-Type: text/csv\r\n\r\n'
    ).encode() + csv_bytes + f'\r\n--{boundary}--\r\n'.encode()

    req = urllib.request.Request(
        'https://geocoding.geo.census.gov/geocoder/locations/addressbatch',
        data=body,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
        method='POST',
    )

    coord_map = {}
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = resp.read().decode('utf-8')
        reader = csv.reader(io.StringIO(result))
        for row in reader:
            if len(row) >= 6 and row[2].strip() == 'Match':
                idx = int(row[0].strip())
                coord_str = row[5].strip()
                if ',' in coord_str:
                    lon_s, lat_s = coord_str.split(',', 1)
                    key = f"{addr_list[idx][0]}|{addr_list[idx][1]}"
                    coord_map[key] = (float(lat_s.strip()), float(lon_s.strip()))
    except Exception as e:
        print(f'[WARN] Geocoding failed: {e}')

    return coord_map


# ── Main pipeline ─────────────────────────────────────────────────────────────
def run_pipeline(county: str = "boulder"):
    started = datetime.now()
    run_id = None

    # Log the run
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO pipeline_runs (county) VALUES (%s) RETURNING id",
            [county],
        )
        run_id = cur.fetchone()["id"]

    try:
        result = _run_pipeline_inner(county, run_id)
        with get_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pipeline_runs
                SET status = 'completed', finished_at = NOW(),
                    records_processed = %s, leads_scored = %s, new_owners_found = %s
                WHERE id = %s
            """, [result["records_processed"], result["leads_scored"],
                  result["new_owners_found"], run_id])
        return result

    except Exception as e:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE pipeline_runs SET status = 'failed', finished_at = NOW(), error_message = %s WHERE id = %s",
                [str(e), run_id],
            )
        raise


def _run_pipeline_inner(county: str, run_id: int):
    csv_path = DATA_DIR / f"{county}_records.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"{csv_path} not found")

    # Load CSV
    records = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append({k.strip(): v.strip() for k, v in row.items() if k is not None})

    print(f"[PIPELINE] Loaded {len(records)} records from {csv_path}")

    # Detect new owners by comparing against current DB state
    new_owner_folios = _detect_new_owners_from_db(records, county)
    print(f"[PIPELINE] {len(new_owner_folios)} new-owner events")

    # Upsert raw properties into DB
    _upsert_properties(records, county)

    # Group by owner, score, and upsert leads
    by_owner = defaultdict(list)
    for rec in records:
        owner = rec.get("owner_name", "").strip()
        if owner:
            by_owner[owner].append(rec)

    # ── Step 1: Score ALL leads and upsert (no geocoding yet) ────────────────
    leads_scored = 0
    scored_leads = []  # [(owner_name, score, recs), ...] for sorting

    for owner_name, recs in by_owner.items():
        primary = recs[0]
        prop_count = len(recs)
        folio = primary.get("folio", "")
        is_new = folio in new_owner_folios
        prop_city = primary.get("city", "").strip()
        mail_city = primary.get("mailingCity", "").strip()
        mail_state = primary.get("mailingState", "").strip()
        acct_type = primary.get("account_type", "").strip()

        score, badges, breakdown = score_lead(
            owner_name, prop_city, mail_city, mail_state, prop_count, acct_type, is_new
        )

        mail_addr1 = primary.get("mailingAddr1", "")
        mail_zip = primary.get("mailingZip", "")
        full_mail = f"{mail_addr1}, {mail_city}, {mail_state} {mail_zip}".strip(", ")

        prop_address = build_address(primary)

        with get_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO leads (owner_name, county, score, badges, score_breakdown,
                    primary_folio, property_address, city, mailing_address, mailing_city,
                    mailing_state, mailing_zip, property_count, status)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, 'new')
                ON CONFLICT (owner_name, county) DO UPDATE SET
                    score = EXCLUDED.score,
                    badges = EXCLUDED.badges,
                    score_breakdown = EXCLUDED.score_breakdown,
                    property_address = EXCLUDED.property_address,
                    city = EXCLUDED.city,
                    mailing_address = EXCLUDED.mailing_address,
                    mailing_city = EXCLUDED.mailing_city,
                    mailing_state = EXCLUDED.mailing_state,
                    mailing_zip = EXCLUDED.mailing_zip,
                    property_count = EXCLUDED.property_count,
                    updated_at = NOW()
                RETURNING id
            """, [
                owner_name, county, score, badges,
                __import__("json").dumps(breakdown),
                folio, prop_address, prop_city, full_mail,
                mail_city, mail_state, mail_zip, prop_count,
            ])
            lead_id = cur.fetchone()["id"]

            # Insert lead_properties (without coords for now)
            cur.execute("DELETE FROM lead_properties WHERE lead_id = %s", [lead_id])
            for r in recs:
                r_folio = r.get("folio", "").strip()
                if not r_folio:
                    continue
                addr = build_address(r)
                city = r.get("city", "").strip()
                cur.execute("""
                    INSERT INTO lead_properties (lead_id, folio, county, address, city)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, [lead_id, r_folio, county, addr, city])

        scored_leads.append((owner_name, score, lead_id, recs))
        leads_scored += 1

    # ── Step 2: Geocode only top 50 leads' properties ─────────────────────
    top_n = int(os.environ.get("TOP_LEADS_COUNT", "50"))
    scored_leads.sort(key=lambda x: x[1], reverse=True)
    top_leads = scored_leads[:top_n]

    addr_set = set()
    addr_to_lead_props = {}  # addr_key → [(lead_id, folio), ...]
    for owner_name, score, lead_id, recs in top_leads:
        for r in recs:
            r_folio = r.get("folio", "").strip()
            if not r_folio:
                continue
            addr = base_addr(build_address(r))
            city = r.get("city", "").strip()
            if addr and city:
                key = f"{addr}|{city}"
                addr_set.add((addr, city))
                addr_to_lead_props.setdefault(key, []).append((lead_id, r_folio))

    print(f"[PIPELINE] Geocoding {len(addr_set)} addresses for top {len(top_leads)} leads")
    coord_map = geocode_addresses(list(addr_set))
    print(f"[PIPELINE] Geocoded {len(coord_map)}/{len(addr_set)} addresses")

    # Stamp coords onto lead_properties for top leads
    for key, coords in coord_map.items():
        lat, lng = coords
        for lead_id, folio in addr_to_lead_props.get(key, []):
            with get_cursor(commit=True) as cur:
                cur.execute("""
                    UPDATE lead_properties SET lat = %s, lng = %s
                    WHERE lead_id = %s AND folio = %s
                """, [lat, lng, lead_id, folio])

    # ── Step 3: Auto-enrich top leads via Apollo ────────────────────────────
    apollo_key = os.environ.get("APOLLO_API_KEY", "")
    leads_enriched = 0
    if apollo_key:
        from enrichment import enrich_with_apollo
        # Only enrich leads that haven't been enriched yet
        with get_cursor() as cur:
            cur.execute("""
                SELECT * FROM leads
                WHERE county = %s AND enriched_at IS NULL
                ORDER BY score DESC
                LIMIT %s
            """, [county, top_n])
            unenriched = cur.fetchall()

        print(f"[PIPELINE] Enriching {len(unenriched)} leads via Apollo")
        for lead in unenriched:
            result = enrich_with_apollo(dict(lead), apollo_key)
            if result.get("enriched"):
                leads_enriched += 1
        print(f"[PIPELINE] Enriched {leads_enriched}/{len(unenriched)} leads")
    else:
        print("[PIPELINE] APOLLO_API_KEY not set — skipping enrichment")

    return {
        "run_id": run_id,
        "county": county,
        "records_processed": len(records),
        "leads_scored": leads_scored,
        "new_owners_found": len(new_owner_folios),
        "addresses_geocoded": len(coord_map),
        "leads_enriched": leads_enriched,
    }


def _detect_new_owners_from_db(records, county):
    """Compare CSV owners against what's already in the properties table.
    First run (empty DB) returns empty set — nothing to compare against.
    Subsequent runs detect folios where the owner_name changed since last run.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) as c FROM properties WHERE county = %s",
            [county],
        )
        count = cur.fetchone()["c"]

        # First run — no previous data to compare against
        if count == 0:
            print("[PIPELINE] First run for this county — skipping new-owner detection")
            return set()

        cur.execute(
            "SELECT folio, owner_name FROM properties WHERE county = %s",
            [county],
        )
        existing = cur.fetchall()

    prev_by_folio = defaultdict(set)
    for row in existing:
        prev_by_folio[row["folio"]].add(row["owner_name"])

    changed = set()
    for rec in records:
        folio = rec.get("folio", "")
        owner = rec.get("owner_name", "")
        prev_owners = prev_by_folio.get(folio)
        if prev_owners is not None and owner and owner not in prev_owners:
            changed.add(folio)
    return changed


def _upsert_properties(records, county):
    """Bulk upsert raw property records."""
    with get_cursor(commit=True) as cur:
        for rec in records:
            folio = rec.get("folio", "")
            if not folio:
                continue
            cur.execute("""
                INSERT INTO properties (folio, county, owner_name, property_address, city,
                    mailing_address, mailing_city, mailing_state, mailing_zip,
                    account_type, tax_area)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (folio, county) DO UPDATE SET
                    owner_name = EXCLUDED.owner_name,
                    property_address = EXCLUDED.property_address,
                    city = EXCLUDED.city,
                    mailing_address = EXCLUDED.mailing_address,
                    mailing_city = EXCLUDED.mailing_city,
                    mailing_state = EXCLUDED.mailing_state,
                    mailing_zip = EXCLUDED.mailing_zip,
                    account_type = EXCLUDED.account_type,
                    tax_area = EXCLUDED.tax_area,
                    last_seen = CURRENT_DATE
            """, [
                folio, county,
                rec.get("owner_name", ""),
                build_address(rec),
                rec.get("city", ""),
                rec.get("mailingAddr1", ""),
                rec.get("mailingCity", ""),
                rec.get("mailingState", ""),
                rec.get("mailingZip", ""),
                rec.get("account_type", ""),
                rec.get("taxArea", ""),
            ])
