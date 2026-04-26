"""
All County Lead Generation — FastAPI Server

Endpoints:
  GET  /api/leads                 - List leads (filterable, paginated)
  GET  /api/leads/:id             - Single lead with properties + outreach history
  PATCH /api/leads/:id/status     - Update lead status
  POST /api/pipeline/run          - Trigger pipeline manually
  GET  /api/pipeline/runs         - Pipeline run history
  POST /api/leads/:id/enrich      - Enrich single lead via Apollo
  POST /api/letters/verify        - Verify mailing address via Lob
  POST /api/letters/send          - Send physical letter via Lob
  POST /api/outreach/email        - Send email via SendGrid
  GET  /api/outreach/:lead_id     - Outreach history for a lead
  GET  /api/stats                 - Dashboard KPI stats
"""

import os
from typing import Optional
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

from db import get_cursor, init_db
from auth import (
    get_current_user, login, create_user, seed_admin,
    LoginRequest, CreateUserRequest,
)

app = FastAPI(title="All County Lead Gen API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ── Serve built frontend in production ────────────────────────────────────────
DIST_DIR = Path(__file__).parent.parent / "dist"


@app.on_event("startup")
def startup():
    init_db()
    seed_admin()
    if (DIST_DIR / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")
        if (DIST_DIR / "data").exists():
            app.mount("/data", StaticFiles(directory=DIST_DIR / "data"), name="data")


# ── Auth middleware ───────────────────────────────────────────────────────────

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Skip auth for: login endpoint, static files, docs
    if (path == "/api/auth/login" or
        not path.startswith("/api/") or
        path in ("/docs", "/openapi.json", "/redoc")):
        return await call_next(request)

    # Validate JWT
    try:
        user = get_current_user(request)
        request.state.user = user
    except HTTPException as e:
        from starlette.responses import JSONResponse
        return JSONResponse(status_code=e.status_code, content={"detail": e.detail})

    return await call_next(request)


# ── Auth endpoints ────────────────────────────────────────────────────────────

@app.post("/api/auth/login")
def auth_login(body: LoginRequest):
    return login(body.email, body.password)

@app.get("/api/auth/users")
def auth_list_users(request: Request):
    user = getattr(request.state, "user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    with get_cursor() as cur:
        cur.execute("SELECT id, email, name, role, active, created_at, last_login FROM users ORDER BY created_at")
        return cur.fetchall()

@app.post("/api/auth/users")
def auth_create_user(body: CreateUserRequest, request: Request):
    user = getattr(request.state, "user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    return create_user(body.email, body.name, body.password, body.role)

@app.get("/api/auth/me")
def auth_me(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return user



# ── Models ────────────────────────────────────────────────────────────────────

class StatusUpdate(BaseModel):
    status: str  # new | contacted | replied | converted | skipped

class VerifyRequest(BaseModel):
    name: str
    line1: str
    city: Optional[str] = None
    state: Optional[str] = "CO"
    zip: Optional[str] = None

class SendLetterRequest(BaseModel):
    lead_id: int
    letter_text: str

class SendEmailRequest(BaseModel):
    lead_id: int
    subject: str
    body: str
    to_email: str


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats():
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) as total FROM leads")
        total = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) as c FROM leads WHERE 'NEW_OWNER' = ANY(badges)")
        new_owners = cur.fetchone()["c"]

        cur.execute("SELECT COALESCE(AVG(score), 0) as avg FROM leads")
        avg_score = round(cur.fetchone()["avg"], 1)

        cur.execute("SELECT COUNT(*) as c FROM leads WHERE email IS NOT NULL")
        enriched = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) as c FROM outreach WHERE status = 'sent'")
        sent = cur.fetchone()["c"]

    return {
        "total_leads": total,
        "new_owner_events": new_owners,
        "avg_score": avg_score,
        "enriched_leads": enriched,
        "outreach_sent": sent,
    }


# ── Leads ─────────────────────────────────────────────────────────────────────

@app.get("/api/leads")
def list_leads(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    city: Optional[str] = None,
    min_score: int = 0,
    status: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "score_desc",
):
    conditions = []
    params = []

    if city:
        conditions.append("l.city = %s")
        params.append(city)
    if min_score:
        conditions.append("l.score >= %s")
        params.append(min_score)
    if status:
        conditions.append("l.status = %s")
        params.append(status)
    if search:
        conditions.append("(l.owner_name ILIKE %s OR l.property_address ILIKE %s OR l.city ILIKE %s)")
        q = f"%{search}%"
        params.extend([q, q, q])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    order_map = {
        "score_desc": "l.score DESC",
        "score_asc": "l.score ASC",
        "name_asc": "l.owner_name ASC",
        "newest": "l.created_at DESC",
    }
    order = order_map.get(sort, "l.score DESC")

    offset = (page - 1) * per_page
    params.extend([per_page, offset])

    with get_cursor() as cur:
        # Count
        cur.execute(f"SELECT COUNT(*) as total FROM leads l {where}", params[:-2])
        total = cur.fetchone()["total"]

        # Leads
        cur.execute(f"""
            SELECT l.*,
                   COALESCE(
                     (SELECT json_agg(json_build_object(
                        'folio', lp.folio, 'address', lp.address, 'city', lp.city,
                        'lat', lp.lat, 'lng', lp.lng
                      )) FROM lead_properties lp WHERE lp.lead_id = l.id),
                     '[]'::json
                   ) AS all_properties
            FROM leads l
            {where}
            ORDER BY {order}
            LIMIT %s OFFSET %s
        """, params)
        leads = cur.fetchall()

    # Convert to serializable dicts
    result = []
    for row in leads:
        d = dict(row)
        d["badges"] = list(d.get("badges") or [])
        d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
        d["updated_at"] = d["updated_at"].isoformat() if d.get("updated_at") else None
        d["enriched_at"] = d["enriched_at"].isoformat() if d.get("enriched_at") else None
        result.append(d)

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "leads": result,
    }


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: int):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM leads WHERE id = %s", [lead_id])
        lead = cur.fetchone()
        if not lead:
            raise HTTPException(404, "Lead not found")

        cur.execute("""
            SELECT folio, address, city, lat, lng
            FROM lead_properties WHERE lead_id = %s
        """, [lead_id])
        props = cur.fetchall()

        cur.execute("""
            SELECT * FROM outreach
            WHERE lead_id = %s ORDER BY created_at DESC
        """, [lead_id])
        outreach = cur.fetchall()

    d = dict(lead)
    d["badges"] = list(d.get("badges") or [])
    d["all_properties"] = [dict(p) for p in props]
    d["outreach_history"] = [dict(o) for o in outreach]
    return d


@app.patch("/api/leads/{lead_id}/status")
def update_lead_status(lead_id: int, body: StatusUpdate):
    valid = {"new", "contacted", "replied", "converted", "skipped"}
    if body.status not in valid:
        raise HTTPException(400, f"Invalid status. Must be one of: {valid}")
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE leads SET status = %s, updated_at = NOW() WHERE id = %s RETURNING id",
            [body.status, lead_id],
        )
        if not cur.fetchone():
            raise HTTPException(404, "Lead not found")
    return {"ok": True, "status": body.status}


# ── Pipeline ──────────────────────────────────────────────────────────────────

@app.post("/api/pipeline/run")
def trigger_pipeline(county: str = "boulder", skip_download: bool = False):
    """Full daily flow: download fresh CSV → run scoring pipeline.
    Cloud Scheduler hits this endpoint daily.
    """
    from scraper import download_csv
    from pipeline_db import run_pipeline

    result = {"county": county}

    # Step 1: Download latest data
    if not skip_download:
        dl = download_csv(county)
        result["download"] = dl
        if not dl["ok"]:
            raise HTTPException(500, f"Download failed: {dl.get('error')}")
        if not dl["changed"]:
            result["pipeline"] = {"skipped": True, "reason": "No data changes"}
            return result

    # Step 2: Run scoring pipeline
    pipeline_result = run_pipeline(county)
    result["pipeline"] = pipeline_result
    return result


@app.post("/api/pipeline/download-only")
def download_only(county: str = "boulder"):
    """Just download the CSV, don't run the pipeline."""
    from scraper import download_csv
    return download_csv(county)


@app.get("/api/pipeline/runs")
def pipeline_runs():
    with get_cursor() as cur:
        cur.execute("""
            SELECT * FROM pipeline_runs
            ORDER BY started_at DESC LIMIT 20
        """)
        return cur.fetchall()


# ── Enrichment (Apollo) ──────────────────────────────────────────────────────

@app.post("/api/leads/{lead_id}/enrich")
def enrich_lead_endpoint(lead_id: int):
    """Skip-trace a single lead via Tracerfy — returns email + phone."""
    api_key = os.getenv("TRACERFY_API_KEY")
    if not api_key:
        raise HTTPException(501, "TRACERFY_API_KEY not configured")

    with get_cursor() as cur:
        cur.execute("SELECT * FROM leads WHERE id = %s", [lead_id])
        lead = cur.fetchone()
        if not lead:
            raise HTTPException(404, "Lead not found")

    from enrichment import enrich_lead
    result = enrich_lead(dict(lead), api_key)
    return result


# ── Address verification (Lob) ───────────────────────────────────────────────

@app.post("/api/letters/verify")
def verify_address(body: VerifyRequest):
    """Verify a mailing address via Lob US Verifications API."""
    api_key = os.getenv("LOB_API_KEY")
    if not api_key:
        raise HTTPException(501, "LOB_API_KEY not configured")

    import httpx
    from base64 import b64encode

    auth = b64encode(f"{api_key}:".encode()).decode()
    resp = httpx.post(
        "https://api.lob.com/v1/us_verifications",
        headers={"Authorization": f"Basic {auth}"},
        json={
            "primary_line": body.line1,
            "city": body.city or "",
            "state": body.state or "CO",
            "zip_code": body.zip or "",
        },
    )

    if resp.status_code != 200:
        err = resp.json().get("error", {})
        raise HTTPException(resp.status_code, err.get("message", "Lob verification failed"))

    data = resp.json()
    return {
        "deliverability": data.get("deliverability", "unknown"),
        "line1": data.get("primary_line", body.line1),
        "city": data.get("components", {}).get("city", body.city),
        "state": data.get("components", {}).get("state", body.state),
        "zip": data.get("components", {}).get("zip_code", body.zip),
    }


# ── Letter sending (Lob) ─────────────────────────────────────────────────────

@app.post("/api/letters/send")
def send_letter(body: SendLetterRequest):
    """Send a physical letter via Lob."""
    api_key = os.getenv("LOB_API_KEY")
    if not api_key:
        raise HTTPException(501, "LOB_API_KEY not configured")

    with get_cursor() as cur:
        cur.execute("SELECT * FROM leads WHERE id = %s", [body.lead_id])
        lead = cur.fetchone()
        if not lead:
            raise HTTPException(404, "Lead not found")

    import httpx
    from base64 import b64encode

    auth = b64encode(f"{api_key}:".encode()).decode()
    html = (
        '<html><body style="font-family:serif;font-size:13px;'
        'line-height:1.7;padding:48px;white-space:pre-wrap;">'
        + body.letter_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        + "</body></html>"
    )

    resp = httpx.post(
        "https://api.lob.com/v1/letters",
        headers={"Authorization": f"Basic {auth}"},
        json={
            "to": {
                "name": lead["owner_name"],
                "address_line1": lead["mailing_address"] or lead["property_address"],
                "address_city": lead["mailing_city"] or lead["city"] or "Boulder",
                "address_state": lead["mailing_state"] or "CO",
                "address_zip": lead.get("mailing_zip") or "80301",
                "address_country": "US",
            },
            "from": {
                "name": "All County Property Management",
                "address_line1": os.getenv("FROM_ADDRESS_LINE1", "1234 Pearl St"),
                "address_city": os.getenv("FROM_CITY", "Boulder"),
                "address_state": "CO",
                "address_zip": os.getenv("FROM_ZIP", "80302"),
                "address_country": "US",
            },
            "file": html,
            "color": False,
        },
    )

    if resp.status_code not in (200, 201):
        err = resp.json().get("error", {})
        raise HTTPException(resp.status_code, err.get("message", "Lob send failed"))

    data = resp.json()

    # Log outreach
    with get_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO outreach (lead_id, channel, body, to_address, status, external_id, cost, sent_at)
            VALUES (%s, 'letter', %s, %s, 'sent', %s, %s, NOW())
        """, [
            body.lead_id,
            body.letter_text,
            lead["mailing_address"] or lead["property_address"],
            data.get("id"),
            0.87,
        ])
        cur.execute(
            "UPDATE leads SET status = 'contacted', updated_at = NOW() WHERE id = %s AND status = 'new'",
            [body.lead_id],
        )

    return {
        "id": data.get("id"),
        "expected_delivery_date": data.get("expected_delivery_date"),
        "url": data.get("url"),
    }


# ── Email outreach (SendGrid) ────────────────────────────────────────────────

@app.post("/api/outreach/email")
def send_email(body: SendEmailRequest):
    """Send outreach email via SendGrid."""
    api_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("SENDGRID_FROM_EMAIL", "outreach@allcountyboulder.com")
    if not api_key:
        raise HTTPException(501, "SENDGRID_API_KEY not configured")

    import httpx

    resp = httpx.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "personalizations": [{"to": [{"email": body.to_email}]}],
            "from": {"email": from_email, "name": "All County Property Management"},
            "subject": body.subject,
            "content": [{"type": "text/plain", "value": body.body}],
        },
    )

    if resp.status_code not in (200, 201, 202):
        raise HTTPException(resp.status_code, f"SendGrid error: {resp.text}")

    # Log outreach
    with get_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO outreach (lead_id, channel, subject, body, to_address, status, sent_at)
            VALUES (%s, 'email', %s, %s, %s, 'sent', NOW())
        """, [body.lead_id, body.subject, body.body, body.to_email])
        cur.execute(
            "UPDATE leads SET status = 'contacted', updated_at = NOW() WHERE id = %s AND status = 'new'",
            [body.lead_id],
        )

    return {"ok": True, "to": body.to_email}


# ── Outreach history ──────────────────────────────────────────────────────────

@app.get("/api/outreach/{lead_id}")
def outreach_history(lead_id: int):
    with get_cursor() as cur:
        cur.execute("""
            SELECT * FROM outreach
            WHERE lead_id = %s ORDER BY created_at DESC
        """, [lead_id])
        rows = cur.fetchall()
    return [dict(r) for r in rows]


# ── AI Email Generation (Claude) ─────────────────────────────────────────────

class GenerateEmailRequest(BaseModel):
    lead_id: int
    tone: Optional[str] = "professional"  # professional, friendly, direct

MAX_GENERATIONS_PER_LEAD = 3

@app.post("/api/outreach/generate")
def generate_email(body: GenerateEmailRequest):
    """Generate a personalized outreach email using Claude AI. Max 3 per lead."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(501, "ANTHROPIC_API_KEY not configured")

    # Rate limit: max 3 generations per lead
    with get_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) as c FROM outreach WHERE lead_id = %s AND channel = 'ai_draft'",
            [body.lead_id],
        )
        count = cur.fetchone()["c"]
        if count >= MAX_GENERATIONS_PER_LEAD:
            raise HTTPException(429, f"Generation limit reached ({MAX_GENERATIONS_PER_LEAD} per lead)")

    with get_cursor() as cur:
        cur.execute("SELECT * FROM leads WHERE id = %s", [body.lead_id])
        lead = cur.fetchone()
        if not lead:
            raise HTTPException(404, "Lead not found")

        cur.execute("""
            SELECT address, city FROM lead_properties
            WHERE lead_id = %s LIMIT 10
        """, [body.lead_id])
        properties = cur.fetchall()

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    props_list = "\n".join(f"  - {p['address']}, {p['city']}" for p in properties) if properties else "  (address on file)"

    prompt = f"""Write a property management outreach letter for All County Property Management (Boulder County, Colorado).

TARGET OWNER:
- Name: {lead['owner_name']}
- Properties owned: {lead['property_count']}
- Property addresses:
{props_list}
- Mailing address: {lead['mailing_address'] or 'N/A'}
- Mailing state: {lead['mailing_state'] or 'CO'}
- Score: {lead['score']}/22 (higher = stronger lead)
- Badges: {', '.join(lead['badges'] or [])}

KEY SIGNALS TO ADDRESS:
{"- They are an LLC/entity — speak to their investment strategy and NOI optimization" if 'LLC' in (lead['badges'] or []) else ""}
{"- Out-of-state owner — emphasize local boots-on-the-ground management, they can't be there daily" if 'OUT_OF_STATE' in (lead['badges'] or []) else ""}
{"- Absentee owner — they don't live near their properties, management is a hassle" if 'ABSENTEE' in (lead['badges'] or []) else ""}
{"- Portfolio owner (5+ properties) — managing multiple units is time-intensive, professional management scales" if 'PORTFOLIO' in (lead['badges'] or []) else ""}
{"- Multi-property (3-4 units) — growing portfolio, now is the time to professionalize" if 'MULTI_PROP' in (lead['badges'] or []) else ""}
{"- New owner — just acquired, may not have management in place yet" if 'NEW_OWNER' in (lead['badges'] or []) else ""}

TONE: {body.tone}

REQUIREMENTS:
- Keep it SHORT — under 150 words. 3-4 short paragraphs max.
- Reference ONE specific property address and their situation
- ONE concrete value prop (pick the most relevant for their situation)
- End with a clear, simple call to action
- Sign off as [Your Name], All County Property Management — Boulder County
- No subject line — just the letter body
- Conversational, not corporate. Short sentences."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    generated_text = message.content[0].text

    # Log the generation
    with get_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO outreach (lead_id, channel, body, status, created_at)
            VALUES (%s, 'ai_draft', %s, 'draft', NOW())
        """, [body.lead_id, generated_text])

    remaining = MAX_GENERATIONS_PER_LEAD - count - 1
    return {"email": generated_text, "generations_remaining": remaining}


# ── SPA catch-all (MUST be last) ─────────────────────────────────────────────

@app.get("/{path:path}", include_in_schema=False)
async def serve_spa(path: str):
    """Serve built frontend. Falls back to index.html for client-side routing."""
    if path.startswith("api/"):
        raise HTTPException(404)
    file_path = DIST_DIR / path
    if file_path.is_file():
        return FileResponse(file_path)
    index = DIST_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(404, "Frontend not built — run: npm run build")
