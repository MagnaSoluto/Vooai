"""Sessões: password, magic-link, access JWT, refresh rotativo."""

from __future__ import annotations

import logging
import os
import smtplib
import time
from email.message import EmailMessage
from typing import Any

from .db import backend, connection, init_db
from .security import (
    hash_password,
    hash_token,
    is_prod,
    magic_ttl_sec,
    mint_access_token,
    new_magic_code,
    new_refresh_token,
    refresh_ttl_sec,
    verify_password,
)
from .wallet import User, _user_from_id, get_user_by_id

logger = logging.getLogger("vooai.sessions")


def _ensure_schema(conn) -> None:
    """Migração leve idempotente (SQLite/Postgres)."""
    if backend() == "postgres":
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
              id SERIAL PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              token_hash TEXT NOT NULL UNIQUE,
              expires_at TIMESTAMPTZ NOT NULL,
              revoked_at TIMESTAMPTZ,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS magic_links (
              id SERIAL PRIMARY KEY,
              email TEXT NOT NULL,
              code_hash TEXT NOT NULL,
              expires_at TIMESTAMPTZ NOT NULL,
              consumed_at TIMESTAMPTZ,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_magic_email ON magic_links(email, created_at DESC)"
        )
    else:
        cols = {
            r["name"]
            for r in conn.fetchall("PRAGMA table_info(users)")
        }
        if "password_hash" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              token_hash TEXT NOT NULL UNIQUE,
              expires_at TEXT NOT NULL,
              revoked_at TEXT,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS magic_links (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              email TEXT NOT NULL,
              code_hash TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              consumed_at TEXT,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_magic_email ON magic_links(email, created_at DESC)"
        )


def ensure_auth_schema() -> None:
    init_db()
    with connection() as conn:
        _ensure_schema(conn)


def _session_payload(user: User) -> dict[str, Any]:
    access, exp = mint_access_token(user_id=user.id, email=user.email)
    refresh = new_refresh_token()
    expires_at = int(time.time()) + refresh_ttl_sec()
    with connection() as conn:
        _ensure_schema(conn)
        if backend() == "postgres":
            conn.execute(
                """
                INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
                VALUES (?, ?, to_timestamp(?))
                """,
                (user.id, hash_token(refresh), expires_at),
            )
        else:
            conn.execute(
                """
                INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
                VALUES (?, ?, datetime(?, 'unixepoch'))
                """,
                (user.id, hash_token(refresh), expires_at),
            )
    return {
        "user_id": user.id,
        "email": user.email,
        "balance_saldos": user.balance_saldos,
        "balance_brl": user.balance_brl,
        "token": access,
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": max(1, exp - int(time.time())),
        "token_type": "Bearer",
    }


def register_with_password(email: str, password: str) -> dict[str, Any]:
    ensure_auth_schema()
    email = email.strip().lower()
    if "@" not in email or len(email) < 5:
        raise ValueError("E-mail inválido.")
    if len(password) < 8:
        raise ValueError("Senha mínima: 8 caracteres.")
    pw = hash_password(password)
    legacy_token = new_refresh_token()  # coluna token ainda NOT NULL — não usar como sessão
    try:
        with connection() as conn:
            _ensure_schema(conn)
            if backend() == "postgres":
                row = conn.fetchone(
                    """
                    INSERT INTO users (email, token, password_hash)
                    VALUES (?, ?, ?) RETURNING id
                    """,
                    (email, legacy_token, pw),
                )
                uid = int(row["id"])
            else:
                cur = conn.execute(
                    "INSERT INTO users (email, token, password_hash) VALUES (?, ?, ?)",
                    (email, legacy_token, pw),
                )
                uid = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO wallets (user_id, balance_brl, balance_saldos) VALUES (?, 0, 0)",
                (uid,),
            )
            user = _user_from_id(conn, uid)
    except Exception as exc:
        msg = str(exc).lower()
        if "unique" in msg or "duplicate" in msg:
            raise ValueError("E-mail já cadastrado.") from exc
        raise
    return _session_payload(user)


def login_with_password(email: str, password: str) -> dict[str, Any]:
    ensure_auth_schema()
    email = email.strip().lower()
    with connection() as conn:
        _ensure_schema(conn)
        row = conn.fetchone(
            "SELECT id, password_hash FROM users WHERE lower(email) = lower(?)",
            (email,),
        )
        if not row or not verify_password(password, row["password_hash"]):
            raise ValueError("Credenciais inválidas.")
        user = _user_from_id(conn, int(row["id"]))
    return _session_payload(user)


def smtp_configured() -> bool:
    """True quando há host SMTP — necessário para código por e-mail em prod."""
    return bool((os.getenv("VOOAI_SMTP_HOST") or "").strip())


def _smtp_use_ssl(port: int) -> bool:
    raw = (os.getenv("VOOAI_SMTP_SSL") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    # Titan / HostGator: 465 = SMTPS implícito
    return port == 465


def _send_magic_email(email: str, code: str) -> bool:
    host = (os.getenv("VOOAI_SMTP_HOST") or "").strip()
    if not host:
        return False
    port = int(os.getenv("VOOAI_SMTP_PORT") or "465")
    user = (os.getenv("VOOAI_SMTP_USER") or "").strip()
    password = (os.getenv("VOOAI_SMTP_PASSWORD") or "").strip()
    from_addr = (os.getenv("VOOAI_SMTP_FROM") or user or "noreply@vooai.local").strip()
    from_name = (os.getenv("VOOAI_SMTP_FROM_NAME") or "VooAI").strip()
    msg = EmailMessage()
    msg["Subject"] = "Código de acesso VooAI"
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = email
    msg.set_content(
        f"Seu código VooAI: {code}\nVálido por {magic_ttl_sec() // 60} minutos.\n"
        "Se você não pediu, ignore este e-mail."
    )
    if _smtp_use_ssl(port):
        with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls()
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
    return True


def request_magic_link(email: str) -> dict[str, Any]:
    ensure_auth_schema()
    email = email.strip().lower()
    if "@" not in email or len(email) < 5:
        raise ValueError("E-mail inválido.")
    code = new_magic_code()
    expires_at = int(time.time()) + magic_ttl_sec()
    with connection() as conn:
        _ensure_schema(conn)
        if backend() == "postgres":
            conn.execute(
                """
                INSERT INTO magic_links (email, code_hash, expires_at)
                VALUES (?, ?, to_timestamp(?))
                """,
                (email, hash_token(code), expires_at),
            )
        else:
            conn.execute(
                """
                INSERT INTO magic_links (email, code_hash, expires_at)
                VALUES (?, ?, datetime(?, 'unixepoch'))
                """,
                (email, hash_token(code), expires_at),
            )
    sent = False
    try:
        sent = _send_magic_email(email, code)
    except Exception as exc:
        logger.warning("magic email fail: %s", exc)
        sent = False
    out: dict[str, Any] = {
        "status": "sent",
        "sent": bool(sent),
        "message": "Se o e-mail for válido, enviamos um código de acesso.",
    }
    # Em não-prod sem SMTP, devolve código para smoke/testes (nunca em prod).
    if not is_prod() and not sent:
        out["dev_code"] = code
        out["sent"] = True
    elif is_prod() and not sent:
        out["message"] = (
            "Código gerado, mas SMTP não está configurado. Use senha ou configure VOOAI_SMTP_*."
        )
        if (os.getenv("VOOAI_MAGIC_ALLOW_UNSENT") or "").strip() in ("1", "true", "yes"):
            # escape hatch ops — não usar em exposição pública
            out["dev_code"] = code
    return out


def verify_magic_link(email: str, code: str) -> dict[str, Any]:
    ensure_auth_schema()
    email = email.strip().lower()
    code = (code or "").strip()
    if len(code) < 4:
        raise ValueError("Código inválido.")
    with connection(immediate=True) as conn:
        _ensure_schema(conn)
        if backend() == "postgres":
            row = conn.fetchone(
                """
                SELECT id FROM magic_links
                WHERE email = ? AND code_hash = ? AND consumed_at IS NULL
                  AND expires_at > NOW()
                ORDER BY id DESC LIMIT 1
                """,
                (email, hash_token(code)),
            )
        else:
            row = conn.fetchone(
                """
                SELECT id FROM magic_links
                WHERE email = ? AND code_hash = ? AND consumed_at IS NULL
                  AND datetime(expires_at) > datetime('now')
                ORDER BY id DESC LIMIT 1
                """,
                (email, hash_token(code)),
            )
        if not row:
            raise ValueError("Código inválido ou expirado.")
        mid = int(row["id"])
        if backend() == "postgres":
            conn.execute(
                "UPDATE magic_links SET consumed_at = NOW() WHERE id = ?",
                (mid,),
            )
        else:
            conn.execute(
                "UPDATE magic_links SET consumed_at = datetime('now') WHERE id = ?",
                (mid,),
            )
        user_row = conn.fetchone("SELECT id FROM users WHERE lower(email) = lower(?)", (email,))
        if user_row:
            user = _user_from_id(conn, int(user_row["id"]))
        else:
            legacy = new_refresh_token()
            if backend() == "postgres":
                created = conn.fetchone(
                    "INSERT INTO users (email, token) VALUES (?, ?) RETURNING id",
                    (email, legacy),
                )
                uid = int(created["id"])
            else:
                cur = conn.execute(
                    "INSERT INTO users (email, token) VALUES (?, ?)",
                    (email, legacy),
                )
                uid = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO wallets (user_id, balance_brl, balance_saldos) VALUES (?, 0, 0)",
                (uid,),
            )
            user = _user_from_id(conn, uid)
    return _session_payload(user)


def refresh_session(refresh_token: str) -> dict[str, Any]:
    ensure_auth_schema()
    raw = (refresh_token or "").strip()
    if not raw:
        raise ValueError("Refresh token obrigatório.")
    th = hash_token(raw)
    with connection(immediate=True) as conn:
        _ensure_schema(conn)
        if backend() == "postgres":
            row = conn.fetchone(
                """
                SELECT id, user_id FROM refresh_tokens
                WHERE token_hash = ? AND revoked_at IS NULL AND expires_at > NOW()
                """,
                (th,),
            )
        else:
            row = conn.fetchone(
                """
                SELECT id, user_id FROM refresh_tokens
                WHERE token_hash = ? AND revoked_at IS NULL
                  AND datetime(expires_at) > datetime('now')
                """,
                (th,),
            )
        if not row:
            raise ValueError("Refresh inválido ou expirado.")
        rid = int(row["id"])
        uid = int(row["user_id"])
        if backend() == "postgres":
            conn.execute(
                "UPDATE refresh_tokens SET revoked_at = NOW() WHERE id = ?",
                (rid,),
            )
        else:
            conn.execute(
                "UPDATE refresh_tokens SET revoked_at = datetime('now') WHERE id = ?",
                (rid,),
            )
        user = _user_from_id(conn, uid)
    return _session_payload(user)


def revoke_refresh(refresh_token: str | None = None, *, user_id: int | None = None) -> None:
    ensure_auth_schema()
    with connection() as conn:
        _ensure_schema(conn)
        if refresh_token:
            th = hash_token(refresh_token.strip())
            if backend() == "postgres":
                conn.execute(
                    "UPDATE refresh_tokens SET revoked_at = NOW() WHERE token_hash = ?",
                    (th,),
                )
            else:
                conn.execute(
                    "UPDATE refresh_tokens SET revoked_at = datetime('now') WHERE token_hash = ?",
                    (th,),
                )
        if user_id is not None:
            if backend() == "postgres":
                conn.execute(
                    "UPDATE refresh_tokens SET revoked_at = NOW() WHERE user_id = ? AND revoked_at IS NULL",
                    (user_id,),
                )
            else:
                conn.execute(
                    "UPDATE refresh_tokens SET revoked_at = datetime('now') WHERE user_id = ? AND revoked_at IS NULL",
                    (user_id,),
                )


def get_user_from_access(token: str) -> User | None:
    from .security import parse_access_token

    payload = parse_access_token(token)
    if not payload:
        # legado: token opaco em users.token (migração)
        from .wallet import get_user_by_legacy_token

        return get_user_by_legacy_token(token)
    try:
        return get_user_by_id(int(payload["sub"]))
    except Exception:
        return None
