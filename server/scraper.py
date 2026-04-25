"""
Daily scraper — downloads county property records from public assessor data.

Sources:
  Boulder:  https://bouldercounty.gov/property-and-land/assessor/data-download/
  Larimer:  https://www.larimer.gov/assessor/publicdata

Both refresh daily. No auth or API keys needed.

Usage:
    python scraper.py                  # Download + run pipeline
    python scraper.py --download-only  # Just download, don't score

On GCP, Cloud Scheduler calls POST /api/pipeline/run which calls this.
"""

import csv
import io
import os
import sys
import shutil
import hashlib
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Data sources ──────────────────────────────────────────────────────────────

SOURCES = {
    "boulder": {
        "urls": ["https://assessor.boco.solutions/ASR_PublicDataFiles/Owner_Address.csv"],
        "filename": "boulder_records.csv",
        "normalize": None,  # Already in the right format
    },
    "larimer": {
        "urls": [
            "https://storage.googleapis.com/lc-public/asr/assessor-public-owner-location.csv",
            "https://storage.googleapis.com/lc-public/asr/assessor-public-account.csv",
        ],
        "filename": "larimer_records.csv",
        "normalize": "larimer",  # Needs field mapping
    },
}

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _fetch_file(url: str, dest: Path):
    """Download a single URL to a file."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "AllCountyLeadGen/1.0 (property management research)",
    })
    with urllib.request.urlopen(req, timeout=180) as resp:
        with open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)


def download_csv(county: str) -> dict:
    """Download the latest property records CSV for a county.

    Returns dict with download metadata:
      {ok, county, path, size_mb, rows, changed, downloaded_at, error?}
    """
    if county not in SOURCES:
        return {"ok": False, "county": county, "error": f"Unknown county: {county}"}

    src = SOURCES[county]
    dest = DATA_DIR / src["filename"]

    try:
        # Download all required files
        raw_files = []
        for url in src["urls"]:
            fname = url.split("/")[-1]
            tmp = DATA_DIR / f"_tmp_{fname}"
            print(f"[SCRAPER] Downloading {fname} from {url}")
            _fetch_file(url, tmp)
            raw_files.append(tmp)

        # Normalize if needed (Larimer has different column names)
        if src["normalize"] == "larimer":
            merged = _normalize_larimer(raw_files[0], raw_files[1])
            tmp_out = dest.with_suffix(".tmp")
            with open(tmp_out, "w", newline="", encoding="utf-8") as f:
                f.write(merged)
        else:
            # Boulder — single file, already correct format
            tmp_out = raw_files[0]

        # Check if data changed (hash comparison)
        new_hash = _file_hash(tmp_out)
        old_hash = _file_hash(dest) if dest.exists() else None
        changed = new_hash != old_hash

        # Move into place
        shutil.move(str(tmp_out), str(dest))

        # Clean up temp files
        for f in raw_files:
            f.unlink(missing_ok=True)

        size_mb = round(dest.stat().st_size / (1024 * 1024), 1)
        rows = sum(1 for _ in open(dest)) - 1
        print(f"[SCRAPER] {county}: {'new data' if changed else 'unchanged'} — {rows:,} rows, {size_mb} MB")

        return {
            "ok": True, "county": county, "path": str(dest),
            "size_mb": size_mb, "rows": rows, "changed": changed,
            "downloaded_at": datetime.now().isoformat(),
        }

    except Exception as e:
        # Clean up any temp files on failure
        for pattern in DATA_DIR.glob("_tmp_*"):
            pattern.unlink(missing_ok=True)
        dest.with_suffix(".tmp").unlink(missing_ok=True)
        return {"ok": False, "county": county, "error": str(e)}


def _normalize_larimer(owner_loc_path: Path, account_path: Path) -> str:
    """Join Larimer Owner-Location + Account CSVs and remap columns to match
    the Boulder format that pipeline_db.py expects.

    Larimer Owner-Location fields:
        PARCELNO, ACCOUNTNO, SCHEDULENUM, NAME1, NAME2,
        MAILADDRESS1, MAILADDRESS2, MAILCITY, MAILSTATE, MAILZIPCODE,
        SITUSSTREETNO, SITUSPREDIRECTION, SITUSSTREETNAME, SITUSSTREETTYPE,
        SITUSPOSTDIRECTION, SITUSUNIT, SITUSADDRESS, SITUSCITY, SITUSZIPCODE,
        TAXYEAR, RUNDATE

    Larimer Account fields:
        PARCELNO, ACCOUNTNO, SCHEDULENUM, TAXAREA, ACCTTYPE, ...

    Output: CSV matching Boulder's format (same columns pipeline_db expects).
    """
    # Load account types by ACCOUNTNO
    acct_types = {}
    with open(account_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            acct_no = (row.get("ACCOUNTNO") or "").strip()
            if acct_no:
                acct_types[acct_no] = (row.get("ACCTTYPE") or "").strip()

    # Read owner-location and output in Boulder format
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=[
        "CreatedDate", "strap", "folio", "status_cd", "bld_num",
        "str_num", "str_pfx", "str", "str_sfx", "str_unit",
        "city", "sub_code", "sub_dscr", "section", "township", "range",
        "block", "lot", "owner_name", "mail_to",
        "mailingAddr1", "mailingAddr2", "mailingCity", "mailingState", "mailingZip",
        "mailingCountry", "role_cd", "pct_own", "taxArea", "nh", "mill_levy",
        "legalDscr", "waterFee", "account_type",
    ])
    writer.writeheader()

    with open(owner_loc_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            acct_no = (row.get("ACCOUNTNO") or "").strip()
            acct_type = acct_types.get(acct_no, "")
            run_date = (row.get("RUNDATE") or "").strip()

            writer.writerow({
                "CreatedDate": run_date,
                "strap": row.get("PARCELNO", ""),
                "folio": acct_no or row.get("PARCELNO", ""),
                "status_cd": "A",
                "bld_num": "",
                "str_num": (row.get("SITUSSTREETNO") or "").strip(),
                "str_pfx": (row.get("SITUSPREDIRECTION") or "").strip(),
                "str": (row.get("SITUSSTREETNAME") or "").strip(),
                "str_sfx": (row.get("SITUSSTREETTYPE") or "").strip(),
                "str_unit": (row.get("SITUSUNIT") or "").strip(),
                "city": (row.get("SITUSCITY") or "").strip(),
                "sub_code": "",
                "sub_dscr": "",
                "section": "",
                "township": "",
                "range": "",
                "block": "",
                "lot": "",
                "owner_name": ((row.get("NAME1") or "") + " " + (row.get("NAME2") or "")).strip(),
                "mail_to": "",
                "mailingAddr1": (row.get("MAILADDRESS1") or "").strip(),
                "mailingAddr2": (row.get("MAILADDRESS2") or "").strip(),
                "mailingCity": (row.get("MAILCITY") or "").strip(),
                "mailingState": (row.get("MAILSTATE") or "").strip(),
                "mailingZip": (row.get("MAILZIPCODE") or "").strip(),
                "mailingCountry": "US",
                "role_cd": "",
                "pct_own": "1.0000",
                "taxArea": "",
                "nh": "",
                "mill_levy": "",
                "legalDscr": "",
                "waterFee": "",
                "account_type": acct_type,
            })

    return out.getvalue()


def download_all() -> list[dict]:
    """Download records for all configured counties."""
    results = []
    for county in SOURCES:
        result = download_csv(county)
        results.append(result)
    return results


def _file_hash(path: Path) -> str:
    """SHA-256 of first 100KB — fast enough for change detection."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            h.update(f.read(102400))
    except FileNotFoundError:
        return ""
    return h.hexdigest()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    download_only = "--download-only" in sys.argv

    print("=" * 60)
    print("  All County Lead Gen — Daily Scraper")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = download_all()
    for r in results:
        if r["ok"]:
            print(f"  ✓ {r['county']}: {r['rows']:,} rows, {'changed' if r['changed'] else 'unchanged'}")
        else:
            print(f"  ✗ {r['county']}: {r['error']}")

    if download_only:
        print("\n  Download only — skipping pipeline.\n")
        sys.exit(0)

    # Run pipeline for any county that had changes
    changed = [r for r in results if r.get("ok") and r.get("changed")]
    if not changed:
        print("\n  No data changes — pipeline skipped.\n")
        sys.exit(0)

    from pipeline_db import run_pipeline
    for r in changed:
        print(f"\n  Running pipeline for {r['county']}...")
        try:
            result = run_pipeline(r["county"])
            print(f"  ✓ {result['leads_scored']} leads scored, {result['new_owners_found']} new owners")
        except Exception as e:
            print(f"  ✗ Pipeline failed: {e}")

    print("\n  Done.\n")
