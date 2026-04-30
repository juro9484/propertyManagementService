"""Database connection and helpers."""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/allcounty")


def get_conn():
    return psycopg2.connect(DATABASE_URL)


@contextmanager
def get_cursor(commit=False):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
            if commit:
                conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Run schema.sql to create tables if they don't exist, then run migrations."""
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            # Migrations: update constraints to support new values
            cur.execute("""
                ALTER TABLE outreach DROP CONSTRAINT IF EXISTS outreach_channel_check;
                ALTER TABLE outreach ADD CONSTRAINT outreach_channel_check
                    CHECK (channel IN ('email', 'letter', 'sms', 'ai_draft'));
                ALTER TABLE outreach DROP CONSTRAINT IF EXISTS outreach_status_check;
                ALTER TABLE outreach ADD CONSTRAINT outreach_status_check
                    CHECK (status IN ('draft', 'queued', 'sent', 'delivered', 'opened', 'replied', 'bounced', 'failed'));
                ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_status_check;
                ALTER TABLE leads ADD CONSTRAINT leads_status_check
                    CHECK (status IN ('new', 'contacted', 'follow_up', 'meeting', 'converted', 'not_interested'));
                ALTER TABLE leads ADD COLUMN IF NOT EXISTS new_owner_since DATE;
                ALTER TABLE leads ADD COLUMN IF NOT EXISTS phone_dnc BOOLEAN DEFAULT FALSE;
                ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_status TEXT DEFAULT 'unverified';
                ALTER TABLE rental_listings ADD COLUMN IF NOT EXISTS rent_estimate INTEGER;
                ALTER TABLE rental_listings ADD COLUMN IF NOT EXISTS rent_range_low INTEGER;
                ALTER TABLE rental_listings ADD COLUMN IF NOT EXISTS rent_range_high INTEGER;
                ALTER TABLE rental_listings ADD COLUMN IF NOT EXISTS max_history_price INTEGER;
                ALTER TABLE rental_listings ADD COLUMN IF NOT EXISTS price_drop_pct NUMERIC(5,1);
            """)
        conn.commit()
        print("[DB] Schema initialized")
    finally:
        conn.close()
