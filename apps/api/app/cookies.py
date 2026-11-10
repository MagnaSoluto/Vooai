"""Cookies de sessão (refresh HttpOnly)."""

from __future__ import annotations

import os

from fastapi import Response

from .security import is_prod, refresh_ttl_sec

REFRESH_COOKIE = "vooai_rt"


def cookie_secure() -> bool:
    raw = (os.getenv("VOOAI_COOKIE_SECURE") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return is_prod()


def cookie_path() -> str:
    return (os.getenv("VOOAI_COOKIE_PATH") or ("/api" if is_prod() else "/")).strip() or "/"


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        max_age=refresh_ttl_sec(),
        path=cookie_path(),
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE,
        path=cookie_path(),
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
    )


def attach_session_cookies(response: Response, payload: dict) -> dict:
    """Grava refresh em cookie HttpOnly e remove do JSON (não vaza para JS)."""
    rt = payload.get("refresh_token")
    if rt:
        set_refresh_cookie(response, str(rt))
    out = dict(payload)
    out.pop("refresh_token", None)
    out["refresh_via"] = "httpOnly_cookie"
    return out
