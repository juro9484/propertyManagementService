"""
Authentication — JWT-based login for the lead gen dashboard.

Roles:
  admin   — can create users, trigger pipeline, manage everything
  manager — can view leads, send outreach, update statuses
  viewer  — read-only access to leads and dashboard
"""

import os
import bcrypt
import jwt
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Request, HTTPException
from pydantic import BaseModel
from db import get_cursor

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production-please")
JWT_EXPIRY_HOURS = 72  # 3 days


# ── Models ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str

class CreateUserRequest(BaseModel):
    email: str
    name: str
    password: str
    role: str = "viewer"


# ── Password hashing ─────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_token(user_id: int, email: str, role: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired — please log in again")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


# ── Auth middleware ───────────────────────────────────────────────────────────

# Routes that don't require authentication
PUBLIC_PATHS = {"/api/auth/login", "/docs", "/openapi.json", "/redoc"}

def get_current_user(request: Request) -> Optional[dict]:
    """Extract and validate JWT from Authorization header.
    Returns user dict or raises 401.
    """
    path = request.url.path

    # Public routes
    if path in PUBLIC_PATHS or not path.startswith("/api/"):
        return None

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")

    token = auth_header.split(" ", 1)[1]
    return decode_token(token)


# ── User management ──────────────────────────────────────────────────────────

def login(email: str, password: str) -> dict:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email = %s AND active = TRUE", [email.lower()])
        user = cur.fetchone()

    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    token = create_token(user["id"], user["email"], user["role"])

    # Update last_login
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE users SET last_login = NOW() WHERE id = %s", [user["id"]])

    return {
        "token": token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": user["role"],
        },
    }


def create_user(email: str, name: str, password: str, role: str = "viewer") -> dict:
    hashed = hash_password(password)
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO users (email, name, password_hash, role) VALUES (%s, %s, %s, %s) RETURNING id",
            [email.lower(), name, hashed, role],
        )
        user_id = cur.fetchone()["id"]

    return {"id": user_id, "email": email.lower(), "name": name, "role": role}


def seed_admin():
    """Create default admin if no users exist."""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) as c FROM users")
        if cur.fetchone()["c"] > 0:
            return

    admin_email = os.getenv("ADMIN_EMAIL", "admin@allcounty.com")
    admin_pass = os.getenv("ADMIN_PASSWORD", "changeme123")
    create_user(admin_email, "Admin", admin_pass, "admin")
    print(f"[AUTH] Default admin created: {admin_email}")
