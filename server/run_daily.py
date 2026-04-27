"""Daily pipeline — called by cron at 5 AM MT.
Downloads fresh data and runs scoring + enrichment for all counties.
"""

from scraper import download_csv
from pipeline_db import run_pipeline

COUNTIES = ["boulder", "larimer"]

for county in COUNTIES:
    print(f"\n{'='*50}")
    print(f"  Processing {county}")
    print(f"{'='*50}")

    dl = download_csv(county)
    if not dl.get("ok"):
        print(f"  [ERROR] Download failed: {dl.get('error')}")
        continue

    if not dl.get("changed"):
        print(f"  [SKIP] No data changes")
        continue

    print(f"  Downloaded {dl['rows']:,} rows")
    result = run_pipeline(county)
    print(f"  Scored: {result['leads_scored']:,} | Enriched: {result.get('leads_enriched', 0)} | Geocoded: {result.get('addresses_geocoded', 0)}")

print("\nDone.")
