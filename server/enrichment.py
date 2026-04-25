"""
Apollo.io enrichment — finds email, phone, LinkedIn for lead owners.

Apollo People Enrichment API:
  POST https://api.apollo.io/api/v1/people/match
  Requires: name + company/domain OR name + location

For property owners:
  - LLC owners: search by organization name
  - Individual owners: search by name + city/state
"""

import httpx
from db import get_cursor


def enrich_with_apollo(lead: dict, api_key: str) -> dict:
    """Enrich a single lead. Updates DB and returns enrichment result."""
    owner = lead["owner_name"]
    city = lead.get("city", "Boulder")
    state = lead.get("mailing_state", "CO")

    # Build Apollo search payload
    payload = {
        "api_key": api_key,
        "name": owner,
        "organization_name": owner if _is_entity(owner) else None,
        "city": city,
        "state": state,
        "country": "United States",
    }
    # Remove None values
    payload = {k: v for k, v in payload.items() if v is not None}

    resp = httpx.post(
        "https://api.apollo.io/api/v1/people/match",
        json=payload,
        timeout=15,
    )

    if resp.status_code != 200:
        return {"enriched": False, "error": f"Apollo API error {resp.status_code}"}

    data = resp.json()
    person = data.get("person")

    if not person:
        return {"enriched": False, "error": "No match found"}

    email = person.get("email")
    phone = _extract_phone(person)
    linkedin = person.get("linkedin_url")
    company = person.get("organization", {}).get("name")

    # Update lead in DB
    with get_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE leads
            SET email = COALESCE(%s, email),
                phone = COALESCE(%s, phone),
                linkedin = COALESCE(%s, linkedin),
                company = COALESCE(%s, company),
                enriched_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
        """, [email, phone, linkedin, company, lead["id"]])

    return {
        "enriched": True,
        "email": email,
        "phone": phone,
        "linkedin": linkedin,
        "company": company,
    }


def enrich_top_leads(api_key: str, county: str = "boulder", limit: int = 50):
    """Batch-enrich top N unenriched leads by score."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT * FROM leads
            WHERE county = %s AND enriched_at IS NULL
            ORDER BY score DESC
            LIMIT %s
        """, [county, limit])
        leads = cur.fetchall()

    results = []
    for lead in leads:
        result = enrich_with_apollo(dict(lead), api_key)
        results.append({"lead_id": lead["id"], "owner": lead["owner_name"], **result})

    enriched = sum(1 for r in results if r.get("enriched"))
    print(f"[ENRICH] {enriched}/{len(results)} leads enriched via Apollo")
    return results


def _is_entity(name: str) -> bool:
    keywords = ["LLC", "LP", "HOLDINGS", "PROPERTIES", "INVESTMENTS",
                 "GROUP", "TRUST", "REALTY", "VENTURES", "PARTNERS",
                 "CAPITAL", "ASSETS", "ENTERPRISES", "MANAGEMENT", "INC"]
    up = name.upper()
    return any(kw in up for kw in keywords)


def _extract_phone(person: dict):
    phones = person.get("phone_numbers") or []
    if phones:
        return phones[0].get("sanitized_number") or phones[0].get("raw_number")
    return person.get("phone")
