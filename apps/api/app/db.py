"""Billing DB — Postgres dedicado (`vooai`) com fallback SQLite local.

Prioridade:
  1) VOOAI_DATABASE_URL=postgresql://...@.../vooai  (box / docker)
  2) SQLite em VOOAI_DB_PATH / data/vooai_billing.sqlite (laptop sem Postgres)

Nunca use o DATABASE_URL do SDR (`.../sdr`) — misturaria schemas.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import urlparse

from .paths import data_root

_lock = threading.Lock()
_initialized = False
_pg_pool = None

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  token TEXT NOT NULL UNIQUE,
  password_hash TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS wallets (
  user_id INTEGER PRIMARY KEY REFERENCES users(id),
  balance_brl REAL NOT NULL DEFAULT 0 CHECK (balance_brl >= -0.0001),
  balance_saldos INTEGER NOT NULL DEFAULT 0 CHECK (balance_saldos >= 0),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  kind TEXT NOT NULL CHECK (kind IN ('credit','debit','refund')),
  amount_brl REAL NOT NULL,
  balance_after REAL NOT NULL,
  amount_saldos INTEGER,
  balance_after_saldos INTEGER,
  reason TEXT,
  search_ref TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger(user_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_search_ref ON ledger(search_ref);
CREATE TABLE IF NOT EXISTS pending_charges (
  cobranca_id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  amount_brl REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'pendente',
  external_reference TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  paid_at TEXT
);
CREATE TABLE IF NOT EXISTS refresh_tokens (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id);
CREATE TABLE IF NOT EXISTS magic_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  consumed_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_magic_email ON magic_links(email, created_at DESC);
CREATE TABLE IF NOT EXISTS product_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  props_json TEXT NOT NULL DEFAULT '{}',
  authenticated INTEGER NOT NULL DEFAULT 0,
  session_anon TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_product_events_name ON product_events(name, created_at DESC);
"""

SCHEMA_PG = """
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
"""


def billing_enabled() -> bool:
    raw = (os.getenv("VOOAI_BILLING_ENABLED") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def database_url() -> str | None:
    """Somente VOOAI_DATABASE_URL — nunca o DATABASE_URL do SDR."""
    url = (os.getenv("VOOAI_DATABASE_URL") or "").strip()
    return url or None


def backend() -> str:
    return "postgres" if database_url() else "sqlite"


def db_path() -> Path:
    env = os.getenv("VOOAI_DB_PATH", "").strip()
    if env:
        return Path(env).resolve()
    path = data_root() / "vooai_billing.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def db_label() -> str:
    url = database_url()
    if url:
        u = urlparse(url)
        return f"postgres://{u.hostname}:{u.port or 5432}{u.path}"
    return f"sqlite://{db_path()}"


@dataclass
class Row:
    _data: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class Conn:
    """Wrapper mínimo sqlite/psycopg com placeholders '?'."""

    def __init__(self, raw: Any, *, kind: str):
        self.raw = raw
        self.kind = kind

    def _sql(self, sql: str) -> str:
        if self.kind == "postgres":
            return sql.replace("?", "%s")
        return sql

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cur = self.raw.execute(self._sql(sql), tuple(params))
        return cur

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Row | None:
        cur = self.execute(sql, params)
        if self.kind == "postgres":
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description]
            return Row(dict(zip(cols, row)))
        row = cur.fetchone()
        if row is None:
            return None
        return Row(dict(row))

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[Row]:
        cur = self.execute(sql, params)
        if self.kind == "postgres":
            cols = [d.name for d in cur.description] if cur.description else []
            return [Row(dict(zip(cols, r))) for r in cur.fetchall()]
        return [Row(dict(r)) for r in cur.fetchall()]

    def lastrowid(self, cur: Any | None = None) -> int:
        if self.kind == "postgres":
            # caller should use RETURNING id
            raise RuntimeError("use RETURNING id no Postgres")
        return int(self.raw.execute("SELECT last_insert_rowid()").fetchone()[0])

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        self.raw.close()


@contextmanager
def connection(*, immediate: bool = False) -> Iterator[Conn]:
    init_db()
    url = database_url()
    if url:
        pool = _get_pg_pool(url)
        with pool.connection() as raw:
            conn = Conn(raw, kind="postgres")
            if immediate:
                conn.execute("BEGIN")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return

    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    conn = Conn(raw, kind="sqlite")
    if immediate:
        conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _get_pg_pool(url: str):
    global _pg_pool
    with _lock:
        if _pg_pool is not None:
            return _pg_pool
        from psycopg_pool import ConnectionPool

        _pg_pool = ConnectionPool(
            conninfo=url,
            min_size=1,
            max_size=8,
            timeout=10,
            open=True,
        )
        return _pg_pool


def _migrate_saldos(conn_kind: str, raw: Any) -> None:
    """Garante colunas de saldos + backfill a partir de balance_brl legado."""
    unit = 0.12
    if conn_kind == "postgres":
        with raw.cursor() as cur:
            cur.execute(
                "ALTER TABLE wallets ADD COLUMN IF NOT EXISTS balance_saldos INTEGER NOT NULL DEFAULT 0"
            )
            cur.execute("ALTER TABLE ledger ADD COLUMN IF NOT EXISTS amount_saldos INTEGER")
            cur.execute(
                "ALTER TABLE ledger ADD COLUMN IF NOT EXISTS balance_after_saldos INTEGER"
            )
            cur.execute(
                """
                UPDATE wallets
                SET balance_saldos = FLOOR(balance_brl / %s)::int
                WHERE COALESCE(balance_saldos, 0) = 0 AND balance_brl > 0
                """,
                (unit,),
            )
        return

    cols = {r[1] for r in raw.execute("PRAGMA table_info(wallets)").fetchall()}
    if "balance_saldos" not in cols:
        raw.execute(
            "ALTER TABLE wallets ADD COLUMN balance_saldos INTEGER NOT NULL DEFAULT 0"
        )
    lcols = {r[1] for r in raw.execute("PRAGMA table_info(ledger)").fetchall()}
    if "amount_saldos" not in lcols:
        raw.execute("ALTER TABLE ledger ADD COLUMN amount_saldos INTEGER")
    if "balance_after_saldos" not in lcols:
        raw.execute("ALTER TABLE ledger ADD COLUMN balance_after_saldos INTEGER")
    raw.execute(
        """
        UPDATE wallets
        SET balance_saldos = CAST(balance_brl / ? AS INTEGER)
        WHERE COALESCE(balance_saldos, 0) = 0 AND balance_brl > 0
        """,
        (unit,),
    )


def init_db() -> str:
    global _initialized
    with _lock:
        url = database_url()
        if url:
            import psycopg

            with psycopg.connect(url, autocommit=True) as raw:
                with raw.cursor() as cur:
                    for stmt in SCHEMA_PG.strip().split(";"):
                        s = stmt.strip()
                        if s:
                            cur.execute(s)
                _migrate_saldos("postgres", raw)
        else:
            path = db_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = sqlite3.connect(str(path))
            try:
                raw.executescript(SCHEMA_SQLITE)
                _migrate_saldos("sqlite", raw)
                raw.commit()
            finally:
                raw.close()
        _initialized = True
        return db_label()
