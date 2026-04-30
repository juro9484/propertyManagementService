"""
Skip tracing enrichment via Tracerfy API.

Finds personal email addresses and phone numbers for property owners
using their name + mailing address from county assessor records.

Tracerfy API docs: https://www.tracerfy.com/skip-tracing-api-documentation/
Instant lookup: POST /v1/api/trace/lookup/ — 5 credits/hit, 0 on miss
"""

import re
import httpx
from db import get_cursor

TRACERFY_BASE = "https://tracerfy.com/v1/api"


def enrich_lead(lead: dict, api_key: str) -> dict:
    """Skip-trace a single lead. Returns contact info and updates DB."""
    owner = lead["owner_name"]
    address = lead.get("mailing_address") or lead.get("property_address") or ""
    city = lead.get("mailing_city") or lead.get("city") or ""
    state = lead.get("mailing_state") or "CO"
    zip_code = lead.get("mailing_zip") or ""

    # Parse the mailing address — it's stored as "123 Main St, Boulder, CO 80301"
    # We need just the street line
    street = address.split(",")[0].strip() if address else ""

    # Parse owner name for first/last (county format: "LAST FIRST MIDDLE")
    first, last = _parse_county_name(owner)
    is_entity = _is_entity(owner)

    # Build request — if it's an entity or we can't parse the name,
    # let Tracerfy find the owner via the address (find_owner=true)
    payload = {
        "address": street,
        "city": city,
        "state": state,
        "zip": zip_code,
    }

    if is_entity or not first or not last:
        payload["find_owner"] = True
    else:
        payload["find_owner"] = False
        payload["first_name"] = first
        payload["last_name"] = last

    try:
        resp = httpx.post(
            f"{TRACERFY_BASE}/trace/lookup/",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=20,
        )
    except Exception as e:
        return {"enriched": False, "error": str(e)}

    if resp.status_code != 200:
        return {"enriched": False, "error": f"Tracerfy error {resp.status_code}: {resp.text[:200]}"}

    data = resp.json()

    if not data.get("hit"):
        # Mark as enriched (attempted) so we don't retry
        _mark_enriched(lead["id"])
        return {"enriched": False, "error": "No hit — address not found"}

    persons = data.get("persons") or []
    if not persons:
        _mark_enriched(lead["id"])
        return {"enriched": False, "error": "Hit but no persons returned"}

    # Take the first (highest-ranked) person
    person = persons[0]

    # Extract best email and phone
    emails = person.get("emails") or []
    phones = person.get("phones") or []

    email = emails[0]["email"] if emails else None
    phone = _best_phone(phones)
    full_name = person.get("full_name")
    litigator = person.get("litigator", False)

    # Check DNC status of the selected phone
    phone_dnc = False
    for p in phones:
        if p.get("number") == phone:
            phone_dnc = p.get("dnc", False)
            break

    # Store all phones and emails as JSON for the detail view
    all_phones = [{"number": p["number"], "type": p.get("type"), "dnc": p.get("dnc")} for p in phones]
    all_emails = [e["email"] for e in emails]

    # Update lead in DB
    with get_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE leads
            SET email = COALESCE(%s, email),
                phone = COALESCE(%s, phone),
                company = COALESCE(%s, company),
                phone_dnc = %s,
                enriched_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
        """, [email, phone, full_name, phone_dnc, lead["id"]])

    return {
        "enriched": True,
        "email": email,
        "phone": phone,
        "all_emails": all_emails,
        "all_phones": all_phones,
        "owner_name": full_name,
        "litigator": litigator,
        "credits_used": data.get("credits_deducted", 5),
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
        result = enrich_lead(dict(lead), api_key)
        results.append({"lead_id": lead["id"], "owner": lead["owner_name"], **result})

    enriched = sum(1 for r in results if r.get("enriched"))
    print(f"[ENRICH] {enriched}/{len(results)} leads enriched via Tracerfy")
    return results


def _mark_enriched(lead_id):
    """Mark a lead as enriched (attempted) so we don't retry it."""
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE leads SET enriched_at = NOW(), updated_at = NOW() WHERE id = %s",
            [lead_id],
        )


def _best_phone(phones):
    """Pick the best phone — prefer mobile, non-DNC."""
    mobile = [p for p in phones if p.get("type") == "Mobile" and not p.get("dnc")]
    if mobile:
        return mobile[0]["number"]
    non_dnc = [p for p in phones if not p.get("dnc")]
    if non_dnc:
        return non_dnc[0]["number"]
    if phones:
        return phones[0]["number"]
    return None


def _parse_county_name(name):
    """Parse 'LAST FIRST MIDDLE ET AL' → (first, last)."""
    clean = re.sub(r'\s+(ET\s+AL|JR|SR|II|III|IV|C/O\s+.*)$', '', name, flags=re.IGNORECASE).strip()
    parts = clean.split()
    if len(parts) < 2:
        return None, None
    return parts[1].title(), parts[0].title()


def _is_entity(name):
    keywords = ["LLC", "LP", "HOLDINGS", "PROPERTIES", "INVESTMENTS",
                "GROUP", "TRUST", "REALTY", "VENTURES", "PARTNERS",
                "CAPITAL", "ASSETS", "ENTERPRISES", "MANAGEMENT", "INC",
                "PARTNERSHIP", "ASSOCIATION", "ASSOCS", "CORP", "COMPANY"]
    up = name.upper()
    return any(kw in up for kw in keywords)
