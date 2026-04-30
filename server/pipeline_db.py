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
    # Larimer account types
    "MULTIPLE UNIT", "MH PARK", "MOBILE HOME",
]

# Owners that are clearly developers/builders/institutional — not PM prospects
DEVELOPER_KEYWORDS = [
    "HOMES", "HOMEBUILDERS", "HOMECO", "REAL ESTATE GROUP",
    "BORROWER", "FORESTAR", "LENNAR", "DR HORTON", "MERITAGE",
    "KB HOME", "TOLL BROTHERS", "PULTE", "NVR ", "DREAM FINDERS",
]


def has_llc_signal(name: str) -> bool:
    return any(kw in name.upper() for kw in LLC_KEYWORDS)


def _is_developer(name: str) -> bool:
    up = name.upper()
    return any(kw in up for kw in DEVELOPER_KEYWORDS)


def score_lead(owner_name, prop_city, mail_city, mail_state, prop_count, acct_type, is_new):
    """
    Weighted scoring system:
      FINAL = (Fit × 0.30) + (Struggle × 0.55) + (Timing × 0.15)

    Fit (max ~63): do they match the PM client profile?
    Struggle (max ~35): added by RentCast vacancy matching (not in this function)
    Timing (max ~25): new owner within last 60 days

    Final score range: 0-40ish
    """
    badges = []
    breakdown = {}

    # Developers/builders = 0
    if _is_developer(owner_name):
        return 0, [], {}

    # ── FIT (weighted at 0.30) ───────────────────────────────────────────
    fit_signals = {}

    # Location signal
    if mail_state and mail_state.upper() not in ("CO", ""):
        fit_signals["out_of_state"] = 18; badges.append("OUT_OF_STATE")
    elif mail_city and prop_city and mail_city.strip().upper() != prop_city.strip().upper():
        fit_signals["absentee"] = 12; badges.append("ABSENTEE")

    # Entity type
    if has_llc_signal(owner_name):
        fit_signals["llc_signal"] = 5; badges.append("LLC")

    # Property count
    if prop_count == 1:
        fit_signals["properties"] = 12
    elif 2 <= prop_count <= 4:
        fit_signals["properties"] = 15; badges.append("MULTI_PROP")
    elif 5 <= prop_count <= 8:
        fit_signals["properties"] = 18; badges.append("PORTFOLIO")
    elif 9 <= prop_count <= 20:
        fit_signals["properties"] = 15; badges.append("PORTFOLIO")
    elif 21 <= prop_count <= 50:
        fit_signals["properties"] = 8; badges.append("PORTFOLIO")

    # Rental account type
    if any(r in acct_type.upper() for r in RENTAL_ACCT):
        fit_signals["rental_type"] = 8

    # ── TIMING (weighted at 0.15) ────────────────────────────────────────
    timing_signals = {}
    if is_new:
        timing_signals["new_owner"] = 25; badges.append("NEW_OWNER")

    # ── WEIGHTED SCORE — breakdown adds up to total ────────────────────────
    for k, raw in fit_signals.items():
        weighted = round(raw * 0.30)
        if weighted > 0:
            breakdown[k] = weighted
    for k, raw in timing_signals.items():
        weighted = round(raw * 0.15)
        if weighted > 0:
            breakdown[k] = weighted

    score = sum(breakdown.values())

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

        # Alert: success
        try:
            from alerts import pipeline_success
            pipeline_success(county, result["leads_scored"],
                           result.get("leads_enriched", 0),
                           result.get("addresses_geocoded", 0))
        except Exception:
            pass

        return result

    except Exception as e:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE pipeline_runs SET status = 'failed', finished_at = NOW(), error_message = %s WHERE id = %s",
                [str(e), run_id],
            )

        # Alert: failure
        try:
            from alerts import pipeline_failure
            pipeline_failure(county, str(e))
        except Exception:
            pass

        raise


RESIDENTIAL_TYPES = {
    # Boulder
    "residential", "residential condo", "apartment", "affordable res",
    "manufactured home", "mixed use", "ag with non-integral res",
    "bed & break", "imp only",
    # Larimer
    "multiple unit", "mobile home", "mh park",
}


def _run_pipeline_inner(county: str, run_id: int):
    csv_path = DATA_DIR / f"{county}_records.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"{csv_path} not found")

    # Load CSV — residential properties only
    all_records = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_records.append({k.strip(): v.strip() for k, v in row.items() if k is not None})

    records = [r for r in all_records if r.get("account_type", "").lower() in RESIDENTIAL_TYPES]
    print(f"[PIPELINE] Loaded {len(all_records)} records, {len(records)} residential from {csv_path}")

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

    # ── Step 1: Score ALL leads in memory, then batch upsert ─────────────────
    import json as json_mod
    from psycopg2.extras import execute_values

    scored_in_memory = []  # [(owner_name, score, lead_row_tuple, recs), ...]

    for owner_name, recs in by_owner.items():
        primary = recs[0]
        prop_count = len(recs)
        folio = primary.get("folio", "")
        # New owner is handled post-upsert (60-day window based on created_at)
        is_new = False
        prop_city = primary.get("city", "").strip()
        mail_city = primary.get("mailingCity", "").strip()
        mail_state = primary.get("mailingState", "").strip()
        acct_type = primary.get("account_type", "").strip()

        score, badges, breakdown = score_lead(
            owner_name, prop_city, mail_city, mail_state, prop_count, acct_type, is_new
        )

        mail_addr1 = primary.get("mailingAddr1", "").strip()
        mail_addr2 = primary.get("mailingAddr2", "").strip()
        mail_zip = primary.get("mailingZip", "")
        # Use addr2 if addr1 looks like a name/dept (not a street)
        mail_street = mail_addr2 if mail_addr2 and not any(c.isdigit() for c in mail_addr1) else mail_addr1
        if mail_addr2 and mail_street == mail_addr1:
            mail_street = f"{mail_addr1}, {mail_addr2}"
        full_mail = f"{mail_street}, {mail_city}, {mail_state} {mail_zip}".strip(", ")
        prop_address = build_address(primary)

        lead_row = (
            owner_name, county, score, badges,
            json_mod.dumps(breakdown),
            folio, prop_address, prop_city, full_mail,
            mail_city, mail_state, mail_zip, prop_count,
        )
        scored_in_memory.append((owner_name, score, lead_row, recs))

    print(f"[PIPELINE] Scored {len(scored_in_memory)} owners in memory")

    # Batch upsert leads
    BATCH = 2000
    lead_id_map = {}  # owner_name → lead_id
    leads_scored = 0

    with get_cursor(commit=True) as cur:
        for i in range(0, len(scored_in_memory), BATCH):
            batch = scored_in_memory[i:i+BATCH]
            lead_rows = [item[2] for item in batch]
            result = execute_values(cur, """
                INSERT INTO leads (owner_name, county, score, badges, score_breakdown,
                    primary_folio, property_address, city, mailing_address, mailing_city,
                    mailing_state, mailing_zip, property_count)
                VALUES %s
                ON CONFLICT (owner_name, county) DO UPDATE SET
                    score = EXCLUDED.score,
                    badges = EXCLUDED.badges,
                    score_breakdown = EXCLUDED.score_breakdown::jsonb,
                    property_address = EXCLUDED.property_address,
                    city = EXCLUDED.city,
                    mailing_address = EXCLUDED.mailing_address,
                    mailing_city = EXCLUDED.mailing_city,
                    mailing_state = EXCLUDED.mailing_state,
                    mailing_zip = EXCLUDED.mailing_zip,
                    property_count = EXCLUDED.property_count,
                    updated_at = NOW()
                RETURNING id, owner_name
            """, lead_rows, fetch=True)

            for row in result:
                lead_id_map[row["owner_name"]] = row["id"]

            leads_scored += len(batch)
            print(f"[PIPELINE] Leads: {leads_scored}/{len(scored_in_memory)} upserted")

    # Batch upsert lead_properties for all leads
    print("[PIPELINE] Upserting lead_properties...")
    prop_rows = []
    for owner_name, score, lead_row, recs in scored_in_memory:
        lead_id = lead_id_map.get(owner_name)
        if not lead_id:
            continue
        for r in recs:
            r_folio = r.get("folio", "").strip()
            if not r_folio:
                continue
            prop_rows.append((lead_id, r_folio, county, build_address(r), r.get("city", "").strip()))

    with get_cursor(commit=True) as cur:
        # Clear old lead_properties for this county's leads
        cur.execute("""
            DELETE FROM lead_properties WHERE lead_id IN (
                SELECT id FROM leads WHERE county = %s
            )
        """, [county])

        for i in range(0, len(prop_rows), BATCH):
            batch = prop_rows[i:i+BATCH]
            execute_values(cur, """
                INSERT INTO lead_properties (lead_id, folio, county, address, city)
                VALUES %s
                ON CONFLICT DO NOTHING
            """, batch)
        print(f"[PIPELINE] Lead properties: {len(prop_rows)} upserted")

    # ── New owner handling ──────────────────────────────────────────────────
    new_owner_bonus = round(25 * 0.15)  # 4 points

    # Step 1: Stamp new_owner_since on leads with changed folios
    if new_owner_folios:
        with get_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE leads SET new_owner_since = CURRENT_DATE
                WHERE county = %s
                AND id IN (
                    SELECT DISTINCT lead_id FROM lead_properties
                    WHERE folio = ANY(%s) AND county = %s
                )
            """, [county, list(new_owner_folios), county])
            if cur.rowcount > 0:
                print(f"[PIPELINE] Stamped new_owner_since on {cur.rowcount} leads")

    # Step 2: Add NEW_OWNER badge + bonus to leads within 60 days
    with get_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE leads SET
                badges = array_append(badges, 'NEW_OWNER'),
                score = score + %s,
                score_breakdown = score_breakdown || %s::jsonb
            WHERE county = %s
            AND new_owner_since IS NOT NULL
            AND new_owner_since > CURRENT_DATE - INTERVAL '60 days'
            AND NOT ('NEW_OWNER' = ANY(badges))
        """, [new_owner_bonus, f'{{"new_owner": {new_owner_bonus}}}', county])
        if cur.rowcount > 0:
            print(f"[PIPELINE] Flagged {cur.rowcount} leads as NEW_OWNER (<60 days)")

    # Step 3: Expire NEW_OWNER badge from leads older than 60 days
    with get_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE leads SET
                badges = array_remove(badges, 'NEW_OWNER'),
                new_owner_since = NULL
            WHERE county = %s
            AND new_owner_since IS NOT NULL
            AND new_owner_since <= CURRENT_DATE - INTERVAL '60 days'
        """, [county])
        if cur.rowcount > 0:
            print(f"[PIPELINE] Expired NEW_OWNER from {cur.rowcount} leads (>60 days)")

    # Build scored_leads list for geocoding/enrichment steps
    scored_leads = [(owner, score, lead_id_map.get(owner), recs)
                    for owner, score, _, recs in scored_in_memory
                    if lead_id_map.get(owner)]

    # ── Step 2: Geocode top 50 leads' properties (map pins) ─────────────────
    scored_leads.sort(key=lambda x: x[1], reverse=True)
    map_leads = scored_leads[:50]

    addr_set = set()
    addr_to_lead_props = {}
    for owner_name, score, lead_id, recs in map_leads:
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

    print(f"[PIPELINE] Geocoding {len(addr_set)} addresses for top 50 map leads")
    coord_map = geocode_addresses(list(addr_set))
    print(f"[PIPELINE] Geocoded {len(coord_map)}/{len(addr_set)} addresses")

    for key, coords in coord_map.items():
        lat, lng = coords
        for lead_id, folio in addr_to_lead_props.get(key, []):
            with get_cursor(commit=True) as cur:
                cur.execute("""
                    UPDATE lead_properties SET lat = %s, lng = %s
                    WHERE lead_id = %s AND folio = %s
                """, [lat, lng, lead_id, folio])

    # ── Step 3: Skip-trace unenriched leads in the top 200 ─────────────────
    enrich_n = int(os.environ.get("TOP_LEADS_COUNT", "200"))
    tracerfy_key = os.environ.get("TRACERFY_API_KEY", "")
    leads_enriched = 0
    if tracerfy_key:
        from enrichment import enrich_lead as tracerfy_enrich
        # Get top 200 by score, then filter to only unenriched
        with get_cursor() as cur:
            cur.execute("""
                SELECT * FROM (
                    SELECT * FROM leads WHERE county = %s
                    ORDER BY score DESC LIMIT %s
                ) top
                WHERE enriched_at IS NULL
            """, [county, enrich_n])
            unenriched = cur.fetchall()

        print(f"[PIPELINE] Skip-tracing {len(unenriched)} unenriched leads from top {enrich_n}")
        for lead in unenriched:
            result = tracerfy_enrich(dict(lead), tracerfy_key)
            if result.get("enriched"):
                leads_enriched += 1
        print(f"[PIPELINE] Enriched {leads_enriched}/{len(unenriched)} leads")
    else:
        print("[PIPELINE] TRACERFY_API_KEY not set — skipping enrichment")

    # ── Step 4: Match vacancy data from rental_listings (no API call) ───────
    vacancy_matched = 0
    try:
        from rentcast import match_listings_to_leads
        # Clear old VACANT badges + scores so strict matching re-applies cleanly
        with get_cursor(commit=True) as cur:
            # Get vacancy points to subtract
            cur.execute("""
                UPDATE leads SET
                    badges = array_remove(badges, 'VACANT'),
                    score = score - COALESCE(
                        (SELECT (v.value)::int FROM jsonb_each_text(score_breakdown) v
                         WHERE v.key LIKE 'vacancy_%%' LIMIT 1), 0),
                    score_breakdown = (
                        SELECT COALESCE(jsonb_object_agg(k, v), '{}'::jsonb)
                        FROM jsonb_each(score_breakdown) x(k, v)
                        WHERE k NOT LIKE 'vacancy_%%'
                    )
                WHERE county = %s AND 'VACANT' = ANY(badges)
            """, [county])
            if cur.rowcount > 0:
                print(f"[PIPELINE] Cleared VACANT from {cur.rowcount} leads for re-matching")
        vacancy_matched = match_listings_to_leads(county)
    except Exception as e:
        print(f"[PIPELINE] Vacancy matching failed: {e}")

    # ── Step 5: Verify emails for top leads that haven't been checked ─────
    emails_verified = 0
    try:
        from email_verify import verify_emails
        emails_verified = verify_emails(limit=50)
    except Exception as e:
        print(f"[PIPELINE] Email verification failed: {e}")

    return {
        "run_id": run_id,
        "county": county,
        "records_processed": len(records),
        "leads_scored": leads_scored,
        "new_owners_found": len(new_owner_folios),
        "addresses_geocoded": len(coord_map),
        "leads_enriched": leads_enriched,
        "vacancy_matched": vacancy_matched,
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
    """Bulk upsert raw property records using batch inserts."""
    from psycopg2.extras import execute_values

    seen = set()
    rows = []
    for rec in records:
        folio = rec.get("folio", "").strip()
        if not folio or folio in seen:
            continue
        seen.add(folio)
        rows.append((
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
        ))

    BATCH = 5000
    with get_cursor(commit=True) as cur:
        for i in range(0, len(rows), BATCH):
            batch = rows[i:i+BATCH]
            execute_values(cur, """
                INSERT INTO properties (folio, county, owner_name, property_address, city,
                    mailing_address, mailing_city, mailing_state, mailing_zip,
                    account_type, tax_area)
                VALUES %s
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
            """, batch)
            print(f"[PIPELINE] Properties: {min(i+BATCH, len(rows))}/{len(rows)} upserted")
