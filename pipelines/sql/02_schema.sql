-- Schema billing + auth VooAI (Postgres). Idempotente.
--   psql "$VOOAI_DATABASE_URL" -f pipelines/sql/02_schema.sql

CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  token TEXT NOT NULL UNIQUE,
  password_hash TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;

CREATE TABLE IF NOT EXISTS wallets (
  user_id INTEGER PRIMARY KEY REFERENCES users(id),
  balance_brl DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (balance_brl >= -0.0001),
  balance_saldos INTEGER NOT NULL DEFAULT 0 CHECK (balance_saldos >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE wallets ADD COLUMN IF NOT EXISTS balance_saldos INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS ledger (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  kind TEXT NOT NULL CHECK (kind IN ('credit','debit','refund')),
  amount_brl DOUBLE PRECISION NOT NULL,
  balance_after DOUBLE PRECISION NOT NULL,
  amount_saldos INTEGER,
  balance_after_saldos INTEGER,
  reason TEXT,
  search_ref TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE ledger ADD COLUMN IF NOT EXISTS amount_saldos INTEGER;
ALTER TABLE ledger ADD COLUMN IF NOT EXISTS balance_after_saldos INTEGER;

CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger(user_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_search_ref ON ledger(search_ref);

CREATE TABLE IF NOT EXISTS pending_charges (
  cobranca_id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  amount_brl DOUBLE PRECISION NOT NULL,
  status TEXT NOT NULL DEFAULT 'pendente',
  external_reference TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  paid_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id);

CREATE TABLE IF NOT EXISTS magic_links (
  id SERIAL PRIMARY KEY,
  email TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_magic_email ON magic_links(email, created_at DESC);

CREATE TABLE IF NOT EXISTS product_events (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  props_json TEXT NOT NULL DEFAULT '{}',
  authenticated SMALLINT NOT NULL DEFAULT 0,
  session_anon TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_product_events_name ON product_events(name, created_at DESC);
