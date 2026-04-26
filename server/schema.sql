-- All County Lead Generation — PostgreSQL Schema
-- Boulder County (extensible to Larimer/Fort Collins later)

-- ─── Raw property records from county assessor ───────────────────────────────
CREATE TABLE IF NOT EXISTS properties (
  folio         TEXT NOT NULL,
  county        TEXT NOT NULL DEFAULT 'boulder',   -- 'boulder' | 'larimer'
  owner_name    TEXT,
  property_address TEXT,
  city          TEXT,
  mailing_address  TEXT,
  mailing_city     TEXT,
  mailing_state    TEXT,
  mailing_zip      TEXT,
  account_type     TEXT,
  tax_area         TEXT,
  lat           DOUBLE PRECISION,
  lng           DOUBLE PRECISION,
  first_seen    DATE NOT NULL DEFAULT CURRENT_DATE,
  last_seen     DATE NOT NULL DEFAULT CURRENT_DATE,
  PRIMARY KEY (folio, county)
);

-- ─── Scored + enriched leads (one per unique owner) ──────────────────────────
CREATE TABLE IF NOT EXISTS leads (
  id            SERIAL PRIMARY KEY,
  owner_name    TEXT NOT NULL,
  county        TEXT NOT NULL DEFAULT 'boulder',
  score         INTEGER NOT NULL DEFAULT 0,
  badges        TEXT[] DEFAULT '{}',
  score_breakdown JSONB DEFAULT '{}',

  -- enrichment (Apollo)
  email         TEXT,
  phone         TEXT,
  linkedin      TEXT,
  company       TEXT,
  enriched_at   TIMESTAMPTZ,

  -- primary property reference
  primary_folio TEXT,
  property_address TEXT,
  city          TEXT,
  mailing_address  TEXT,
  mailing_city     TEXT,
  mailing_state    TEXT,
  mailing_zip      TEXT,
  property_count   INTEGER DEFAULT 1,

  -- workflow
  status        TEXT NOT NULL DEFAULT 'new'
                CHECK (status IN ('new', 'contacted', 'follow_up', 'meeting', 'converted', 'not_interested')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE (owner_name, county)
);

-- ─── Junction: which properties belong to which lead ─────────────────────────
CREATE TABLE IF NOT EXISTS lead_properties (
  lead_id       INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  folio         TEXT NOT NULL,
  county        TEXT NOT NULL DEFAULT 'boulder',
  address       TEXT,
  city          TEXT,
  lat           DOUBLE PRECISION,
  lng           DOUBLE PRECISION,
  PRIMARY KEY (lead_id, folio, county),
  FOREIGN KEY (folio, county) REFERENCES properties(folio, county)
);

-- ─── Outreach log ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outreach (
  id            SERIAL PRIMARY KEY,
  lead_id       INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  channel       TEXT NOT NULL CHECK (channel IN ('email', 'letter', 'sms', 'ai_draft')),
  subject       TEXT,
  body          TEXT,
  to_address    TEXT,          -- email addr or mailing addr depending on channel
  status        TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('draft', 'queued', 'sent', 'delivered', 'opened', 'replied', 'bounced', 'failed')),
  external_id   TEXT,          -- Lob letter ID, SendGrid message ID, etc.
  cost          NUMERIC(6,2),  -- cost in dollars
  sent_at       TIMESTAMPTZ,
  delivered_at  TIMESTAMPTZ,
  opened_at     TIMESTAMPTZ,
  reply_text    TEXT,
  replied_at    TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Pipeline run log (audit trail) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pipeline_runs (
  id            SERIAL PRIMARY KEY,
  county        TEXT NOT NULL,
  started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at   TIMESTAMPTZ,
  records_processed INTEGER DEFAULT 0,
  leads_scored      INTEGER DEFAULT 0,
  leads_enriched    INTEGER DEFAULT 0,
  new_owners_found  INTEGER DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'completed', 'failed')),
  error_message TEXT
);

-- ─── Users (app login) ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  id            SERIAL PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'viewer'
                CHECK (role IN ('admin', 'manager', 'viewer')),
  active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_login    TIMESTAMPTZ
);

-- ─── Lead activity log (who did what, when) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS lead_activity (
  id            SERIAL PRIMARY KEY,
  lead_id       INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  user_id       INTEGER REFERENCES users(id),
  action        TEXT NOT NULL,           -- 'status_change', 'email_generated', 'letter_sent', 'note'
  detail        TEXT,                    -- e.g. "new → contacted", or a note
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Indexes ────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_properties_owner ON properties (owner_name);
CREATE INDEX IF NOT EXISTS idx_properties_county ON properties (county);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads (score DESC);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads (status);
CREATE INDEX IF NOT EXISTS idx_leads_county ON leads (county);
CREATE INDEX IF NOT EXISTS idx_outreach_lead ON outreach (lead_id);
CREATE INDEX IF NOT EXISTS idx_outreach_status ON outreach (status);
