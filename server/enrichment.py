"""
Apollo.io enrichment — finds email, phone, LinkedIn for lead owners.

Apollo People Enrichment API:
  POST https://api.apollo.io/api/v1/people/match
  Requires: first_name + last_name + location OR organization

Apollo Organization Enrichment API:
  POST https://api.apollo.io/api/v1/organizations/enrich
  Requires: organization name or domain

For property owners:
  - LLC/entity owners: enrich via organization endpoint
  - Individual owners: parse "LAST FIRST MIDDLE" → first_name/last_name, then people match
"""

import re
import httpx
from db import get_cursor


def enrich_with_apollo(lead: dict, api_key: str) -> dict:
    """Enrich a single lead. Updates DB and returns enrichment result."""
    owner = lead["owner_name"]
    city = lead.get("city", "Boulder")
    state = lead.get("mailing_state", "CO")

    if _is_entity(owner):
        return _enrich_organization(lead, api_key)
    else:
        return _enrich_person(lead, api_key)


def _enrich_person(lead: dict, api_key: str) -> dict:
    """Enrich an individual property owner."""
    owner = lead["owner_name"]
    city = lead.get("city", "Boulder")
    state = lead.get("mailing_state") or "CO"

    first, last = _parse_county_name(owner)
    if not first or not last:
        return {"enriched": False, "error": f"Could not parse name: {owner}"}

    payload = {
        "first_name": first,
        "last_name": last,
        "state": state,
        "city": city,
        "country": "United States",
    }

    resp = httpx.post(
        "https://api.apollo.io/api/v1/people/match",
        headers={"X-Api-Key": api_key},
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

    _update_lead_enrichment(lead["id"], email, phone, linkedin, company)

    return {
        "enriched": True,
        "email": email,
        "phone": phone,
        "linkedin": linkedin,
        "company": company,
    }


def _enrich_organization(lead: dict, api_key: str) -> dict:
    """Enrich an LLC/entity by searching for people at that organization."""
    owner = lead["owner_name"]
    city = lead.get("city", "Boulder")
    state = lead.get("mailing_state") or "CO"

    # Clean up entity name for search
    clean_name = re.sub(r'\s+(ET\s+AL|C/O\s+.*)$', '', owner, flags=re.IGNORECASE).strip()

    # Use People Search to find contacts at this organization
    payload = {
        "organization_name": clean_name,
        "person_locations": [f"{city}, {state}"],
        "page": 1,
        "per_page": 1,
    }

    resp = httpx.post(
        "https://api.apollo.io/api/v1/mixed_people/api_search",
        headers={"X-Api-Key": api_key},
        json=payload,
        timeout=15,
    )

    if resp.status_code != 200:
        return {"enriched": False, "error": f"Apollo search error {resp.status_code}"}

    data = resp.json()
    people = data.get("people") or []

    if not people:
        return {"enriched": False, "error": "No contacts found for organization"}

    person = people[0]
    email = person.get("email")
    phone = _extract_phone(person)
    linkedin = person.get("linkedin_url")
    company = person.get("organization", {}).get("name") or clean_name

    _update_lead_enrichment(lead["id"], email, phone, linkedin, company)

    return {
        "enriched": True,
        "email": email,
        "phone": phone,
        "linkedin": linkedin,
        "company": company,
    }


def _update_lead_enrichment(lead_id, email, phone, linkedin, company):
    """Write enrichment data to the leads table."""
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
        """, [email, phone, linkedin, company, lead_id])


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


def _parse_county_name(name: str):
    """Parse county format 'LAST FIRST MIDDLE ET AL' → (first, last).

    Examples:
        'WEBBER CHRISTOPHER JOHN ET AL' → ('Christopher', 'Webber')
        'SMITH JOHN' → ('John', 'Smith')
        'OBRIEN MARY-TERESA E ET AL' → ('Mary-Teresa', 'Obrien')
    """
    # Remove suffixes
    clean = re.sub(r'\s+(ET\s+AL|JR|SR|II|III|IV|C/O\s+.*)$', '', name, flags=re.IGNORECASE).strip()
    parts = clean.split()

    if len(parts) < 2:
        return None, None

    last = parts[0].title()
    first = parts[1].title()
    return first, last


def _is_entity(name: str) -> bool:
    keywords = ["LLC", "LP", "HOLDINGS", "PROPERTIES", "INVESTMENTS",
                 "GROUP", "TRUST", "REALTY", "VENTURES", "PARTNERS",
                 "CAPITAL", "ASSETS", "ENTERPRISES", "MANAGEMENT", "INC",
                 "PARTNERSHIP", "ASSOCIATION", "ASSOCS", "CORP", "COMPANY"]
    up = name.upper()
    return any(kw in up for kw in keywords)


def _extract_phone(person: dict):
    phones = person.get("phone_numbers") or []
    if phones:
        return phones[0].get("sanitized_number") or phones[0].get("raw_number")
    return person.get("phone")
