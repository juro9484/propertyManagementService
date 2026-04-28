"""Weekly RentCast run — called by cron on Mon/Thu at 6 AM MT.
Fetches rental listings and matches to leads for vacancy scoring.
"""

from rentcast import run_all_counties

print("Running weekly RentCast fetch...")
results = run_all_counties()
for r in results:
    county = r.get("county", "?")
    if r.get("ok"):
        print(f"  {county}: {r['listings_fetched']} listings, {r['leads_matched']} leads matched, {r['api_calls']} API calls")
    else:
        print(f"  {county}: {r.get('error')}")
print("Done.")
