"""Crypto + env de hardening (sem PyJWT — HMAC stdlib)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any


def app_env() -> str:
    return (os.getenv("APP_ENV") or os.getenv("VOOAI_ENV") or "dev").strip().lower()


def is_prod() -> bool:
    return app_env() in ("prod", "production", "staging")


def auth_secret() -> str:
    secret = (os.getenv("VOOAI_AUTH_SECRET") or "").strip()
    if is_prod():
        # Em prod não reaproveita o token admin: vazar um não pode permitir forjar sessão.
        if len(secret) < 32:
            raise RuntimeError("VOOAI_AUTH_SECRET (>= 32 chars) obrigatório em produção.")
        return secret
    return secret or (os.getenv("VOOAI_ADMIN_TOKEN") or "").strip() or "dev-insecure-vooai-auth-secret-change-me"


def access_ttl_sec() -> int:
    try:
        return max(60, int(os.getenv("VOOAI_ACCESS_TTL_SEC", "900")))  # 15 min
    except ValueError:
        return 900


def refresh_ttl_sec() -> int:
    try:
        return max(3600, int(os.getenv("VOOAI_REFRESH_TTL_SEC", str(7 * 24 * 3600))))
    except ValueError:
        return 7 * 24 * 3600


def magic_ttl_sec() -> int:
    try:
        return max(60, int(os.getenv("VOOAI_MAGIC_TTL_SEC", "1800")))  # 30 min
    except ValueError:
        return 1800


def cors_origins() -> list[str]:
    raw = (os.getenv("VOOAI_CORS_ORIGINS") or "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    if is_prod():
        return ["https://vooai.magnasoluto.com.br"]
    return [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "https://vooai.magnasoluto.com.br",
    ]


def allow_topup_stub() -> bool:
    if is_prod():
        return False
    raw = (os.getenv("VOOAI_ALLOW_TOPUP_STUB") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def search_require_auth() -> bool:
    """Em prod, exige login mesmo com billing off (protege SerpAPI no box)."""
    raw = (os.getenv("VOOAI_SEARCH_REQUIRE_AUTH") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return is_prod()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210_000)
    return f"pbkdf2_sha256$210000${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(dk).decode()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded or not password:
        return False
    try:
        algo, iters_s, salt_b64, hash_b64 = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iters = int(iters_s)
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(hash_b64.encode())
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + pad).encode())


def mint_access_token(*, user_id: int, email: str, session_id: str | None = None) -> tuple[str, int]:
    now = int(time.time())
    exp = now + access_ttl_sec()
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": str(user_id), "email": email, "iat": now, "exp": exp, "typ": "access"}
    if session_id:
        payload["sid"] = session_id
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(auth_secret().encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url(sig)}", exp


def parse_access_token(token: str, *, allow_expired: bool = False) -> dict[str, Any] | None:
    try:
        h, p, s = token.split(".", 2)
        expected = hmac.new(auth_secret().encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64url_decode(s)):
            return None
        payload = json.loads(_b64url_decode(p))
        if payload.get("typ") != "access":
            return None
        if not allow_expired and int(payload.get("exp") or 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_magic_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"
