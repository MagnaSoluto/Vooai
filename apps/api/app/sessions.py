"""Sessões: password, magic-link, access JWT, refresh rotativo."""

from __future__ import annotations

import hmac
import logging
import os
import secrets
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
        conn.execute(
            "ALTER TABLE magic_links ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0"
        )
        conn.execute("ALTER TABLE magic_links ADD COLUMN IF NOT EXISTS password_hash TEXT")
        conn.execute("ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS session_id TEXT")
        conn.execute(
            "ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS session_started_at BIGINT"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_refresh_session ON refresh_tokens(session_id)"
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
        mcols = {r["name"] for r in conn.fetchall("PRAGMA table_info(magic_links)")}
        if "attempts" not in mcols:
            conn.execute(
                "ALTER TABLE magic_links ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"
            )
        if "password_hash" not in mcols:
            conn.execute("ALTER TABLE magic_links ADD COLUMN password_hash TEXT")
        rcols = {r["name"] for r in conn.fetchall("PRAGMA table_info(refresh_tokens)")}
        if "session_id" not in rcols:
            conn.execute("ALTER TABLE refresh_tokens ADD COLUMN session_id TEXT")
        if "session_started_at" not in rcols:
            conn.execute("ALTER TABLE refresh_tokens ADD COLUMN session_started_at INTEGER")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_refresh_session ON refresh_tokens(session_id)"
        )

# Tentativas erradas toleradas por código antes de queimá-lo (código tem 6 dígitos).
MAGIC_MAX_ATTEMPTS = 5
# Janela em que reapresentar um refresh já rotacionado é tratado como corrida
# entre abas (benigno) e não como roubo de token.
REFRESH_REUSE_GRACE_SEC = 30
# Mensagem única para cadastro/código: não revela se o e-mail já tem conta.
GENERIC_CODE_MESSAGE = "Se o e-mail for válido, enviamos um código de acesso."

_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    """Hash fixo para gastar o mesmo tempo de PBKDF2 quando o e-mail não existe."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
    return _DUMMY_HASH


def warm_auth() -> None:
    _dummy_hash()


def _now_sql() -> str:
    return "NOW()" if backend() == "postgres" else "datetime('now')"


def max_session_age_sec() -> int:
    """Vida absoluta de uma sessão (rotação de refresh não estende além disso)."""
    try:
        return max(3600, int(os.getenv("VOOAI_SESSION_MAX_AGE_SEC", str(30 * 24 * 3600))))
    except ValueError:
        return 30 * 24 * 3600


def ensure_auth_schema() -> None:
    init_db()
    with connection() as conn:
        _ensure_schema(conn)


def _insert_refresh(conn, *, user_id: int, session_id: str, started_at: int) -> str:
    refresh = new_refresh_token()
    expires_at = min(int(time.time()) + refresh_ttl_sec(), started_at + max_session_age_sec())
    if backend() == "postgres":
        conn.execute(
            """
            INSERT INTO refresh_tokens
              (user_id, token_hash, expires_at, session_id, session_started_at)
            VALUES (?, ?, to_timestamp(?), ?, ?)
            """,
            (user_id, hash_token(refresh), expires_at, session_id, started_at),
        )
    else:
        conn.execute(
            """
            INSERT INTO refresh_tokens
              (user_id, token_hash, expires_at, session_id, session_started_at)
            VALUES (?, ?, datetime(?, 'unixepoch'), ?, ?)
            """,
            (user_id, hash_token(refresh), expires_at, session_id, started_at),
        )
    return refresh


def _session_payload(
    user: User,
    *,
    conn=None,
    session_id: str | None = None,
    started_at: int | None = None,
) -> dict[str, Any]:
    """Emite access (com `sid`) + refresh da mesma sessão."""
    sid = session_id or secrets.token_urlsafe(18)
    started = started_at or int(time.time())
    if conn is None:
        with connection() as c:
            _ensure_schema(c)
            refresh = _insert_refresh(c, user_id=user.id, session_id=sid, started_at=started)
    else:
        refresh = _insert_refresh(conn, user_id=user.id, session_id=sid, started_at=started)
    access, exp = mint_access_token(user_id=user.id, email=user.email, session_id=sid)
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


def _validate_email(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email or len(email) < 5 or len(email) > 200:
        raise ValueError("E-mail inválido.")
    return email


def _validate_password(password: str) -> None:
    if len(password or "") < 8:
        raise ValueError("Senha mínima: 8 caracteres.")
    if len(password) > 200:
        raise ValueError("Senha muito longa.")


def login_with_password(email: str, password: str) -> dict[str, Any]:
    ensure_auth_schema()
    email = (email or "").strip().lower()
    with connection() as conn:
        _ensure_schema(conn)
        row = conn.fetchone(
            "SELECT id, password_hash FROM users WHERE lower(email) = lower(?)",
            (email,),
        )
        # Sempre roda PBKDF2 (mesmo sem usuário/senha) — tempo de resposta não revela a conta.
        stored = row["password_hash"] if row and row["password_hash"] else _dummy_hash()
        ok = verify_password(password, stored)
        if not row or not row["password_hash"] or not ok:
            raise ValueError("E-mail ou senha incorretos.")
        user = _user_from_id(conn, int(row["id"]))
    return _session_payload(user)


def _issue_code(email: str, *, password_hash: str | None = None) -> dict[str, Any]:
    """Gera código (invalida os anteriores), envia por e-mail. Resposta não revela a conta."""
    code = new_magic_code()
    expires_at = int(time.time()) + magic_ttl_sec()
    with connection(immediate=True) as conn:
        _ensure_schema(conn)
        # Só o código mais recente vale: pedir vários não multiplica as chances de acerto.
        conn.execute(
            f"UPDATE magic_links SET consumed_at = {_now_sql()}, password_hash = NULL "
            "WHERE email = ? AND consumed_at IS NULL",
            (email,),
        )
        if backend() == "postgres":
            conn.execute(
                """
                INSERT INTO magic_links (email, code_hash, expires_at, password_hash)
                VALUES (?, ?, to_timestamp(?), ?)
                """,
                (email, hash_token(code), expires_at, password_hash),
            )
        else:
            conn.execute(
                """
                INSERT INTO magic_links (email, code_hash, expires_at, password_hash)
                VALUES (?, ?, datetime(?, 'unixepoch'), ?)
                """,
                (email, hash_token(code), expires_at, password_hash),
            )
    sent = False
    try:
        sent = _send_magic_email(email, code)
    except Exception as exc:
        logger.warning("magic email fail: %s", exc)
        sent = False
    out: dict[str, Any] = {"status": "sent", "sent": True, "message": GENERIC_CODE_MESSAGE}
    if not sent:
        if not is_prod():
            # Em não-prod sem SMTP, devolve código para smoke/testes (nunca em prod).
            out["dev_code"] = code
        else:
            logger.error("magic: SMTP indisponível — código não enviado")
            if (os.getenv("VOOAI_MAGIC_ALLOW_UNSENT") or "").strip() in ("1", "true", "yes"):
                out["dev_code"] = code  # escape hatch ops — não usar em exposição pública
    return out


def request_magic_link(email: str) -> dict[str, Any]:
    ensure_auth_schema()
    return _issue_code(_validate_email(email))


def register_with_password(email: str, password: str) -> dict[str, Any]:
    """Cadastro com confirmação por código.

    Nunca cria a conta na hora nem diz se o e-mail já existe: guarda o hash da
    senha junto do código e só cria (ou, se a conta não tiver senha, define a
    senha) quando o dono do e-mail confirma o código. Mesma resposta sempre.
    """
    ensure_auth_schema()
    email = _validate_email(email)
    _validate_password(password)
    return _issue_code(email, password_hash=hash_password(password))


def verify_magic_link(email: str, code: str) -> dict[str, Any]:
    ensure_auth_schema()
    email = (email or "").strip().lower()
    code = (code or "").strip()
    if len(code) < 4:
        raise ValueError("Código inválido.")
    wrong_code = False
    payload: dict[str, Any] | None = None
    with connection(immediate=True) as conn:
        _ensure_schema(conn)
        lock = "FOR UPDATE" if backend() == "postgres" else ""
        not_expired = (
            "expires_at > NOW()"
            if backend() == "postgres"
            else "datetime(expires_at) > datetime('now')"
        )
        row = conn.fetchone(
            f"""
            SELECT id, code_hash, attempts, password_hash FROM magic_links
            WHERE email = ? AND consumed_at IS NULL AND {not_expired}
            ORDER BY id DESC LIMIT 1 {lock}
            """,
            (email,),
        )
        if not row:
            raise ValueError("Código inválido ou expirado.")
        mid = int(row["id"])
        if not hmac.compare_digest(str(row["code_hash"]), hash_token(code)):
            attempts = int(row["attempts"] or 0) + 1
            if attempts >= MAGIC_MAX_ATTEMPTS:
                conn.execute(
                    f"UPDATE magic_links SET attempts = ?, consumed_at = {_now_sql()}, "
                    "password_hash = NULL WHERE id = ?",
                    (attempts, mid),
                )
            else:
                conn.execute("UPDATE magic_links SET attempts = ? WHERE id = ?", (attempts, mid))
            wrong_code = True
        else:
            pending_pw = row["password_hash"]
            conn.execute(
                f"UPDATE magic_links SET consumed_at = {_now_sql()}, password_hash = NULL "
                "WHERE id = ?",
                (mid,),
            )
            user_row = conn.fetchone(
                "SELECT id, password_hash FROM users WHERE lower(email) = lower(?)", (email,)
            )
            if user_row:
                uid = int(user_row["id"])
                # Conta criada só por código ganha a senha escolhida; senha existente não muda.
                if pending_pw and not user_row["password_hash"]:
                    conn.execute(
                        "UPDATE users SET password_hash = ? WHERE id = ?", (pending_pw, uid)
                    )
            else:
                legacy = new_refresh_token()  # coluna token NOT NULL — nunca usada como sessão
                if backend() == "postgres":
                    created = conn.fetchone(
                        "INSERT INTO users (email, token, password_hash) VALUES (?, ?, ?) RETURNING id",
                        (email, legacy, pending_pw),
                    )
                    uid = int(created["id"])
                else:
                    cur = conn.execute(
                        "INSERT INTO users (email, token, password_hash) VALUES (?, ?, ?)",
                        (email, legacy, pending_pw),
                    )
                    uid = int(cur.lastrowid)
                conn.execute(
                    "INSERT INTO wallets (user_id, balance_brl, balance_saldos) VALUES (?, 0, 0)",
                    (uid,),
                )
            user = _user_from_id(conn, uid)
            payload = _session_payload(user, conn=conn)
    if wrong_code or payload is None:
        # Fora do `with`: a exceção dentro dele faria rollback do contador.
        raise ValueError("Código inválido ou expirado.")
    return payload


def _revoke_session(conn, session_id: str) -> None:
    conn.execute(
        f"UPDATE refresh_tokens SET revoked_at = {_now_sql()} "
        "WHERE session_id = ? AND revoked_at IS NULL",
        (session_id,),
    )


def refresh_session(refresh_token: str) -> dict[str, Any]:
    """Rotaciona o refresh. Reuso de token já rotacionado = roubo → derruba a sessão."""
    ensure_auth_schema()
    raw = (refresh_token or "").strip()
    if not raw:
        raise ValueError("Refresh token obrigatório.")
    th = hash_token(raw)
    reuse_detected = False
    payload: dict[str, Any] | None = None
    with connection(immediate=True) as conn:
        _ensure_schema(conn)
        if backend() == "postgres":
            row = conn.fetchone(
                """
                SELECT id, user_id, session_id, session_started_at,
                       (revoked_at IS NOT NULL) AS revoked,
                       (revoked_at > NOW() - (? * INTERVAL '1 second')) AS recent_revoke,
                       (expires_at > NOW()) AS alive
                FROM refresh_tokens WHERE token_hash = ? FOR UPDATE
                """,
                (REFRESH_REUSE_GRACE_SEC, th),
            )
        else:
            row = conn.fetchone(
                """
                SELECT id, user_id, session_id, session_started_at,
                       (revoked_at IS NOT NULL) AS revoked,
                       (datetime(revoked_at) > datetime('now', '-' || ? || ' seconds')) AS recent_revoke,
                       (datetime(expires_at) > datetime('now')) AS alive
                FROM refresh_tokens WHERE token_hash = ?
                """,
                (REFRESH_REUSE_GRACE_SEC, th),
            )
        if not row:
            raise ValueError("Refresh inválido ou expirado.")
        rid = int(row["id"])
        uid = int(row["user_id"])
        sid = row["session_id"]
        if row["revoked"]:
            if sid and not row["recent_revoke"]:
                logger.warning("refresh reuse detectado (user=%s) — sessão revogada", uid)
                _revoke_session(conn, sid)
                reuse_detected = True
        elif row["alive"]:
            started = int(row["session_started_at"] or time.time())
            conn.execute(
                f"UPDATE refresh_tokens SET revoked_at = {_now_sql()} WHERE id = ?", (rid,)
            )
            if int(time.time()) - started < max_session_age_sec():
                user = _user_from_id(conn, uid)
                payload = _session_payload(
                    user, conn=conn, session_id=sid or secrets.token_urlsafe(18), started_at=started
                )
    if reuse_detected or payload is None:
        raise ValueError("Refresh inválido ou expirado.")
    return payload


def revoke_refresh(refresh_token: str | None = None, *, session_id: str | None = None) -> None:
    """Logout da sessão atual (pelo refresh do cookie e/ou `sid` do access)."""
    ensure_auth_schema()
    with connection() as conn:
        _ensure_schema(conn)
        sids: set[str] = set()
        if session_id:
            sids.add(session_id)
        if refresh_token:
            th = hash_token(refresh_token.strip())
            row = conn.fetchone(
                "SELECT session_id FROM refresh_tokens WHERE token_hash = ?", (th,)
            )
            if row and row["session_id"]:
                sids.add(row["session_id"])
            conn.execute(
                f"UPDATE refresh_tokens SET revoked_at = {_now_sql()} "
                "WHERE token_hash = ? AND revoked_at IS NULL",
                (th,),
            )
        for sid in sids:
            _revoke_session(conn, sid)


def revoke_all_sessions(user_id: int) -> None:
    """Sair de todos os dispositivos."""
    ensure_auth_schema()
    with connection() as conn:
        _ensure_schema(conn)
        conn.execute(
            f"UPDATE refresh_tokens SET revoked_at = {_now_sql()} "
            "WHERE user_id = ? AND revoked_at IS NULL",
            (user_id,),
        )


def _session_active(user_id: int, session_id: str) -> bool:
    with connection() as conn:
        alive = (
            "expires_at > NOW()"
            if backend() == "postgres"
            else "datetime(expires_at) > datetime('now')"
        )
        row = conn.fetchone(
            f"""
            SELECT 1 AS ok FROM refresh_tokens
            WHERE session_id = ? AND user_id = ? AND revoked_at IS NULL AND {alive}
            LIMIT 1
            """,
            (session_id, user_id),
        )
        return bool(row)


def get_user_from_access(token: str) -> User | None:
    from .security import parse_access_token

    payload = parse_access_token(token)
    if not payload:
        # legado: token opaco em users.token (migração). Desligado em prod:
        # é um token sem expiração nem revogação.
        if is_prod() and (os.getenv("VOOAI_ALLOW_LEGACY_TOKEN") or "").strip() not in ("1", "true", "yes"):
            return None
        from .wallet import get_user_by_legacy_token

        return get_user_by_legacy_token(token)
    try:
        uid = int(payload["sub"])
    except Exception:
        return None
    sid = payload.get("sid")
    # Access sem sessão (emitido antes desta versão) → 401; o front renova pelo cookie.
    if not sid or not _session_active(uid, str(sid)):
        return None
    return get_user_by_id(uid)


def access_session_id(token: str | None) -> str | None:
    """`sid` de um access com assinatura válida (mesmo expirado) — usado só no logout."""
    from .security import parse_access_token

    if not token:
        return None
    payload = parse_access_token(token, allow_expired=True)
    return str(payload.get("sid")) if payload and payload.get("sid") else None


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
