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
    # Clean up any orphaned "running" pipeline runs from crashed containers
    with get_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE pipeline_runs SET status = 'failed', error_message = 'Orphaned — container restarted'
            WHERE status = 'running'
        """)
    if (DIST_DIR / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")
        if (DIST_DIR / "data").exists():
            app.mount("/data", StaticFiles(directory=DIST_DIR / "data"), name="data")


# ── Login rate limiting (prevent brute force) ────────────────────────────────
_login_attempts = {}  # ip → (count, first_attempt_time)
LOGIN_MAX_ATTEMPTS = 10
LOGIN_WINDOW_SECONDS = 300  # 5 min


# ── Auth middleware ───────────────────────────────────────────────────────────

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Rate limit login endpoint
    if path == "/api/auth/login" and request.method == "POST":
        ip = request.client.host
        now = __import__("time").time()
        attempts, first_time = _login_attempts.get(ip, (0, now))
        if now - first_time > LOGIN_WINDOW_SECONDS:
            attempts, first_time = 0, now
        if attempts >= LOGIN_MAX_ATTEMPTS:
            from starlette.responses import JSONResponse
            return JSONResponse(status_code=429, content={"detail": "Too many login attempts. Try again in 5 minutes."})
        _login_attempts[ip] = (attempts + 1, first_time)

    # Skip auth for: login, health, static files, docs
    if (path in ("/api/auth/login", "/api/health") or
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

    # Log API access
    user_email = user.get("email", "?") if user else "anon"
    import logging
    logging.info(f"[API] {request.method} {path} — {user_email}")

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

class ResetPasswordRequest(BaseModel):
    password: str

@app.patch("/api/auth/users/{user_id}/password")
def auth_reset_password(user_id: int, body: ResetPasswordRequest, request: Request):
    user = getattr(request.state, "user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    from auth import hash_password
    hashed = hash_password(body.password)
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE users SET password_hash = %s WHERE id = %s RETURNING id", [hashed, user_id])
        if not cur.fetchone():
            raise HTTPException(404, "User not found")
    return {"ok": True}

@app.delete("/api/auth/users/{user_id}")
def auth_delete_user(user_id: int, request: Request):
    user = getattr(request.state, "user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    if user.get("user_id") == user_id:
        raise HTTPException(400, "Cannot delete yourself")
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM users WHERE id = %s RETURNING id", [user_id])
        if not cur.fetchone():
            raise HTTPException(404, "User not found")
    return {"ok": True}

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


# ── Health check (public — no auth required) ─────────────────────────────────

# ── RentCast (vacancy signals) ────────────────────────────────────────────────

@app.post("/api/rentcast/run")
def trigger_rentcast(county: Optional[str] = None, request: Request = None):
    """Run RentCast listing fetch + matching. Weekly cron or manual trigger."""
    user = getattr(request.state, "user", None) if request else None
    if user and user.get("role") != "admin":
        raise HTTPException(403, "Admin only")

    from rentcast import run_rentcast, run_all_counties
    if county:
        return run_rentcast(county)
    return run_all_counties()


@app.get("/api/health")
def health_check():
    """Production health check — DB, pipeline status, per-county stats, alerts config."""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
            db_ok = True
    except Exception:
        db_ok = False

    last_runs = {}
    counties = {}
    total_leads = 0
    enriched = 0
    try:
        with get_cursor() as cur:
            # Last run per county
            cur.execute("""
                SELECT DISTINCT ON (county) county, status, started_at, finished_at,
                    leads_scored, records_processed, error_message
                FROM pipeline_runs
                WHERE status IN ('completed', 'failed')
                ORDER BY county, started_at DESC
            """)
            for row in cur.fetchall():
                duration = None
                if row["started_at"] and row["finished_at"]:
                    duration = str(row["finished_at"] - row["started_at"]).split(".")[0]
                last_runs[row["county"]] = {
                    "status": row["status"],
                    "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                    "duration": duration,
                    "leads_scored": row["leads_scored"],
                    "error": row["error_message"],
                }

            # Per-county stats
            cur.execute("""
                SELECT county,
                    COUNT(*) as total,
                    COUNT(CASE WHEN enriched_at IS NOT NULL THEN 1 END) as enriched,
                    COUNT(CASE WHEN email IS NOT NULL OR phone IS NOT NULL THEN 1 END) as has_contact
                FROM leads GROUP BY county
            """)
            for row in cur.fetchall():
                counties[row["county"]] = {
                    "total_leads": row["total"],
                    "enriched": row["enriched"],
                    "with_contact": row["has_contact"],
                }
                total_leads += row["total"]
                enriched += row["enriched"]

            # Active users
            cur.execute("SELECT COUNT(*) as c FROM users WHERE active = TRUE")
            user_count = cur.fetchone()["c"]
    except Exception:
        user_count = 0

    alerts_configured = bool(os.getenv("ALERT_SMTP_USER") or os.getenv("ALERT_SLACK_WEBHOOK"))

    return {
        "healthy": db_ok,
        "database": "connected" if db_ok else "unreachable",
        "total_leads": total_leads,
        "enriched_leads": enriched,
        "active_users": user_count,
        "alerts_configured": alerts_configured,
        "counties": counties,
        "last_pipeline_runs": last_runs,
    }


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
    county: Optional[str] = None,
    city: Optional[str] = None,
    min_score: int = 0,
    status: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "score_desc",
):
    conditions = []
    params = []

    if county:
        conditions.append("l.county = %s")
        params.append(county)
    if city:
        conditions.append("l.city = %s")
        params.append(city)
    if min_score:
        conditions.append("l.score >= %s")
        params.append(min_score)
    if status:
        if status == "new":
            # Only enriched new leads — no point showing unenriched ones
            conditions.append("l.status = 'new' AND l.enriched_at IS NOT NULL")
        elif status == "pipeline":
            conditions.append("l.status IN ('contacted', 'follow_up', 'meeting')")
        elif status == "closed":
            conditions.append("l.status IN ('converted', 'not_interested')")
        else:
            conditions.append("l.status = %s")
            params.append(status)
    if search:
        conditions.append("(l.owner_name ILIKE %s OR l.property_address ILIKE %s OR l.city ILIKE %s)")
        q = f"%{search}%"
        params.extend([q, q, q])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    order_map = {
        "score_desc": "l.score DESC, l.id ASC",
        "score_asc": "l.score ASC, l.id ASC",
        "name_asc": "l.owner_name ASC, l.id ASC",
        "newest": "l.created_at DESC, l.id ASC",
    }
    order = order_map.get(sort, "l.score DESC, l.id ASC")

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
                        'lat', lp.lat, 'lng', lp.lng,
                        'days_on_market', rl.days_on_market,
                        'listing_price', rl.price
                      )) FROM lead_properties lp
                      LEFT JOIN rental_listings rl ON
                        UPPER(REGEXP_REPLACE(rl.address, '(Apt|Unit|Suite|Ste|#)\s*', '# ', 'gi'))
                        = UPPER(REGEXP_REPLACE(lp.address, '(APT|UNIT|SUITE|STE|#)\s*', '# ', 'gi'))
                        AND rl.days_on_market BETWEEN 1 AND 180
                        AND rl.fetched_at > NOW() - INTERVAL '10 days'
                      WHERE lp.lead_id = l.id),
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
def update_lead_status(lead_id: int, body: StatusUpdate, request: Request):
    valid = {"new", "contacted", "follow_up", "meeting", "converted", "not_interested"}
    if body.status not in valid:
        raise HTTPException(400, f"Invalid status. Must be one of: {valid}")
    user = getattr(request.state, "user", {})
    with get_cursor(commit=True) as cur:
        cur.execute("SELECT status FROM leads WHERE id = %s", [lead_id])
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Lead not found")
        old_status = row["status"]
        cur.execute(
            "UPDATE leads SET status = %s, updated_at = NOW() WHERE id = %s",
            [body.status, lead_id],
        )
        cur.execute("""
            INSERT INTO lead_activity (lead_id, user_id, action, detail)
            VALUES (%s, %s, 'status_change', %s)
        """, [lead_id, user.get("user_id"), f"{old_status} → {body.status}"])
    return {"ok": True, "status": body.status}


@app.get("/api/leads/{lead_id}/activity")
def lead_activity(lead_id: int):
    with get_cursor() as cur:
        cur.execute("""
            SELECT la.*, u.name as user_name
            FROM lead_activity la
            LEFT JOIN users u ON u.id = la.user_id
            WHERE la.lead_id = %s
            ORDER BY la.created_at DESC
            LIMIT 50
        """, [lead_id])
        return cur.fetchall()


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


# ── Usage Analytics (admin only) ──────────────────────────────────────────────

@app.get("/api/analytics/usage")
def usage_analytics(request: Request, days: int = Query(30, ge=1, le=365)):
    user = getattr(request.state, "user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Admin only")

    with get_cursor() as cur:
        cutoff = f"{days} days"

        # Per-user activity summary with status breakdowns
        cur.execute("""
            SELECT u.id, u.name, u.email, u.last_login,
                (SELECT COUNT(*) FROM lead_activity la WHERE la.user_id = u.id
                    AND la.action = 'email_generated'
                    AND la.created_at > NOW() - %s::interval) as emails_generated,
                (SELECT COUNT(*) FROM lead_activity la WHERE la.user_id = u.id
                    AND la.action = 'status_change' AND la.detail LIKE '%%contacted'
                    AND la.created_at > NOW() - %s::interval) as marked_contacted,
                (SELECT COUNT(*) FROM lead_activity la WHERE la.user_id = u.id
                    AND la.action = 'status_change' AND la.detail LIKE '%%follow_up'
                    AND la.created_at > NOW() - %s::interval) as marked_follow_up,
                (SELECT COUNT(*) FROM lead_activity la WHERE la.user_id = u.id
                    AND la.action = 'status_change' AND la.detail LIKE '%%meeting'
                    AND la.created_at > NOW() - %s::interval) as marked_meeting,
                (SELECT COUNT(*) FROM lead_activity la WHERE la.user_id = u.id
                    AND la.action = 'status_change' AND la.detail LIKE '%%converted'
                    AND la.created_at > NOW() - %s::interval) as marked_converted,
                (SELECT COUNT(*) FROM lead_activity la WHERE la.user_id = u.id
                    AND la.action = 'status_change' AND la.detail LIKE '%%not_interested'
                    AND la.created_at > NOW() - %s::interval) as marked_not_interested
            FROM users u WHERE u.active = TRUE
            ORDER BY emails_generated DESC
        """, [cutoff, cutoff, cutoff, cutoff, cutoff, cutoff])
        user_stats = [dict(r) for r in cur.fetchall()]

        # Recent activity feed
        cur.execute("""
            SELECT la.action, la.detail, la.created_at,
                u.name as user_name, l.owner_name as lead_name
            FROM lead_activity la
            LEFT JOIN users u ON u.id = la.user_id
            LEFT JOIN leads l ON l.id = la.lead_id
            WHERE la.created_at > NOW() - %s::interval
            ORDER BY la.created_at DESC
            LIMIT 100
        """, [cutoff])
        recent = [dict(r) for r in cur.fetchall()]

        # Daily stats
        cur.execute("""
            SELECT DATE(created_at) as day,
                COUNT(*) as total_actions,
                COUNT(CASE WHEN action = 'status_change' THEN 1 END) as status_changes,
                COUNT(CASE WHEN action = 'email_generated' THEN 1 END) as emails_generated
            FROM lead_activity
            WHERE created_at > NOW() - %s::interval
            GROUP BY DATE(created_at)
            ORDER BY day DESC
        """, [cutoff])
        daily = [dict(r) for r in cur.fetchall()]

        # Total emails generated (all time)
        cur.execute("SELECT COUNT(*) as c FROM outreach WHERE channel = 'ai_draft'")
        total_emails = cur.fetchone()["c"]

    return {
        "days": days,
        "user_stats": user_stats,
        "recent_activity": recent,
        "daily_stats": daily,
        "total_emails_generated": total_emails,
    }


# ── AI Email Generation (Claude) ─────────────────────────────────────────────

class GenerateEmailRequest(BaseModel):
    lead_id: int
    tone: Optional[str] = "professional"  # professional, friendly, direct

DAILY_GENERATION_LIMIT = 50  # per user per day

@app.post("/api/outreach/generate")
def generate_email(body: GenerateEmailRequest, request: Request):
    """Generate a personalized outreach email using Claude AI. Max 50/day per user."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(501, "ANTHROPIC_API_KEY not configured")

    user = getattr(request.state, "user", {})
    user_id = user.get("user_id")

    # Rate limit: 50 generations per user per day
    with get_cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) as c FROM outreach
            WHERE channel = 'ai_draft'
            AND created_at > NOW() - INTERVAL '24 hours'
            AND lead_id IN (SELECT id FROM leads)
        """)
        count = cur.fetchone()["c"]
        if count >= DAILY_GENERATION_LIMIT:
            raise HTTPException(429, f"Daily generation limit reached ({DAILY_GENERATION_LIMIT}/day)")

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
    from insights import get_insights_for_lead, build_llm_context
    client = anthropic.Anthropic(api_key=api_key)

    props_list = "\n".join(f"  - {p['address']}, {p['city']}" for p in properties) if properties else "  (address on file)"

    # Generate data-driven insights for this lead
    insight_obj = get_insights_for_lead(dict(lead))
    insight_context = build_llm_context(insight_obj) if insight_obj else ""

    # Use contact person name if available, otherwise owner name
    contact_name = lead.get('company') or lead['owner_name']
    # If contact is a person name, use first name only for greeting
    name_parts = contact_name.split()
    greeting_name = name_parts[0] if name_parts and not any(kw in contact_name.upper() for kw in ['LLC', 'TRUST', 'LP', 'INC', 'CORP']) else contact_name

    prompt = f"""Write a property management outreach letter for All County Property Management (Boulder County, Colorado).

ADDRESSING:
- Write to: {greeting_name} (their name is {contact_name})
- They own: {lead['owner_name']}
- Use their FIRST NAME in the greeting, not the LLC/trust name

THEIR SITUATION:
- Properties owned: {lead['property_count']}
- Property addresses:
{props_list}
- Located in: {lead['mailing_state'] or 'CO'}
{"- They manage remotely from out of state" if 'OUT_OF_STATE' in (lead['badges'] or []) else ""}
{"- They don't live near their properties" if 'ABSENTEE' in (lead['badges'] or []) else ""}

{insight_context}

TONE: {body.tone}

{"APPROACH: This lead has ACTIVE STRUGGLE signals (vacancy, pricing issues). Lead with an observation about their situation. Be empathetic, not salesy." if insight_context else "APPROACH: This lead has NO struggle signals — they might be doing fine or already have a PM. Do NOT assume they have a problem. Instead, offer something valuable: a free rental market analysis for their area, a local market insight, or a Colorado rental compliance update. The goal is to start a conversation, not diagnose a problem they might not have."}

RULES:
- Under 90 words. 2-3 short paragraphs.
- Address them by first name ({greeting_name}), NEVER by LLC name
{"- Weave ONE observation about their situation naturally" if insight_context else "- Offer ONE specific piece of value (market data, compliance tip, rental trend)"}
- Do NOT quote specific percentages or exact statistics
- Do NOT assume they need help or are struggling
- Reference a specific property address
- End with a casual question
- Sign off as [Your Name], All County Property Management — Boulder County
- No subject line
- Sound like a helpful neighbor, not a sales pitch
- NEVER say "I noticed", "we offer", "our services", or "property management company"
- NEVER say "I know managing from out of state is hard" — they might have it handled"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    generated_text = message.content[0].text

    # Log the generation + activity
    with get_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO outreach (lead_id, channel, body, status, created_at)
            VALUES (%s, 'ai_draft', %s, 'draft', NOW())
        """, [body.lead_id, generated_text])
        cur.execute("""
            INSERT INTO lead_activity (lead_id, user_id, action, detail)
            VALUES (%s, %s, 'email_generated', %s)
        """, [body.lead_id, user_id, f"tone: {body.tone}"])

    remaining = DAILY_GENERATION_LIMIT - count - 1
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
