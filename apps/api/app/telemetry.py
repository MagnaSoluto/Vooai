"""Telemetria de produto (visitas + funil) — sem PII nem tokens."""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from typing import Any

from .db import connection

ALLOWED_EVENTS = frozenset(
    {
        "pageview",
        "search",
        "search_denied",
        "login",
        "register",
        "topup",
    }
)

ALLOWED_PROP_KEYS = frozenset(
    {
        "path",
        "referrer_host",
        "origin_iata",
        "dest_iata",
        "trip_type",
        "has_return",
        "flex",
        "lead_days_bucket",
        "results_n",
        "method",
        "status",
        "amount_bucket",
        "saldos_bucket",
        "http_status",
        "source",
    }
)

_IATA_RE = re.compile(r"^[A-Z]{3}$")
_PATH_RE = re.compile(r"^/[A-Za-z0-9_./\-]*$")


def telemetry_enabled() -> bool:
    raw = (os.getenv("VOOAI_TELEMETRY_ENABLED") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def amount_bucket(brl: float | int | None) -> str | None:
    if brl is None:
        return None
    try:
        v = float(brl)
    except (TypeError, ValueError):
        return None
    if v < 5:
        return "0-5"
    if v < 10:
        return "5-10"
    if v < 50:
        return "10-50"
    if v < 100:
        return "50-100"
    return "100+"


def saldos_bucket(n: int | None) -> str | None:
    if n is None:
        return None
    try:
        v = int(n)
    except (TypeError, ValueError):
        return None
    if v < 10:
        return "0-10"
    if v < 50:
        return "10-50"
    if v < 200:
        return "50-200"
    return "200+"


def lead_days_bucket(travel_iso: str | None, *, today: date | None = None) -> str | None:
    if not travel_iso:
        return None
    try:
        d = date.fromisoformat(str(travel_iso)[:10])
    except ValueError:
        return None
    base = today or datetime.now(timezone.utc).date()
    delta = (d - base).days
    if delta < 0:
        return "past"
    if delta <= 7:
        return "0-7"
    if delta <= 21:
        return "8-21"
    if delta <= 60:
        return "22-60"
    return "60+"


def _clean_props(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, val in raw.items():
        k = str(key)[:40]
        if k not in ALLOWED_PROP_KEYS:
            continue
        if val is None:
            continue
        if isinstance(val, bool):
            out[k] = val
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            if abs(float(val)) > 1_000_000:
                continue
            out[k] = val
        elif isinstance(val, str):
            s = val.strip()[:120]
            if k == "path":
                if not _PATH_RE.match(s):
                    continue
                out[k] = s.split("?", 1)[0][:80]
            elif k in ("origin_iata", "dest_iata"):
                u = s.upper()
                if _IATA_RE.match(u):
                    out[k] = u
            elif k == "referrer_host":
                host = s.lower().replace("https://", "").replace("http://", "").split("/")[0]
                if host and len(host) < 80 and " " not in host:
                    out[k] = host
            else:
                # enums curtos
                out[k] = s[:40]
        else:
            continue
    return out


def record_event(
    name: str,
    props: dict[str, Any] | None = None,
    *,
    authenticated: bool = False,
    session_anon: str | None = None,
    source: str = "api",
) -> bool:
    """Persiste um evento. Fail-open: erros não sobem."""
    if not telemetry_enabled():
        return False
    event = (name or "").strip().lower()[:40]
    if event not in ALLOWED_EVENTS:
        return False
    clean = _clean_props(props or {})
    if source and "source" not in clean:
        clean["source"] = str(source)[:40]
    anon = None
    if session_anon:
        anon = re.sub(r"[^A-Za-z0-9\-_]", "", str(session_anon))[:64] or None
    try:
        payload = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
        with connection() as conn:
            conn.execute(
                """
                INSERT INTO product_events (name, props_json, authenticated, session_anon)
                VALUES (?, ?, ?, ?)
                """,
                (event, payload, 1 if authenticated else 0, anon),
            )
        return True
    except Exception:
        return False


def record_batch(
    items: list[dict[str, Any]],
    *,
    default_authenticated: bool = False,
    default_session_anon: str | None = None,
) -> int:
    ok = 0
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        if record_event(
            str(item.get("name") or ""),
            item.get("props") if isinstance(item.get("props"), dict) else {},
            authenticated=bool(item.get("authenticated", default_authenticated)),
            session_anon=item.get("session_anon") or default_session_anon,
            source="web",
        ):
            ok += 1
    return ok


def summary(days: int = 7) -> dict[str, Any]:
    days = max(1, min(int(days), 90))
    with connection() as conn:
        if conn.kind == "postgres":
            rows = conn.fetchall(
                """
                SELECT name, COUNT(*)::int AS n
                FROM product_events
                WHERE created_at >= NOW() - (? * INTERVAL '1 day')
                GROUP BY name
                ORDER BY n DESC
                """,
                (days,),
            )
            total_row = conn.fetchone(
                """
                SELECT COUNT(*)::int AS n
                FROM product_events
                WHERE created_at >= NOW() - (? * INTERVAL '1 day')
                """,
                (days,),
            )
        else:
            rows = conn.fetchall(
                """
                SELECT name, COUNT(*) AS n
                FROM product_events
                WHERE created_at >= datetime('now', ?)
                GROUP BY name
                ORDER BY n DESC
                """,
                (f"-{days} days",),
            )
            total_row = conn.fetchone(
                """
                SELECT COUNT(*) AS n
                FROM product_events
                WHERE created_at >= datetime('now', ?)
                """,
                (f"-{days} days",),
            )
    by_name = {str(r["name"]): int(r["n"]) for r in rows}
    return {
        "days": days,
        "total": int(total_row["n"]) if total_row else 0,
        "by_name": by_name,
        "enabled": telemetry_enabled(),
    }
