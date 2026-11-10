"""Cache de cotações `/search` — Redis (box/prod) com fallback em memória (dev local).

Janela padrão: 20 minutos (VOOAI_QUOTE_CACHE_TTL_SEC=1200).

Por quê 20 min?
- Tarifas Google Flights no mesmo trecho+data costumam ficar estáveis dezenas de minutos;
  reconsultar a cada refresh queima crédito SerpAPI sem mudar o sinal COMPRAR/AGUARDAR.
- Abaixo de ~10 min: pouco ganho de frescor, muito gasto.
- Acima de ~45–60 min: risco de preço/oferta stale e decisão errada.
- 15–30 min é a faixa usual em comparadores; 20 min é o meio calibrado.
- SerpAPI também pode servir cache server-side (crédito free), mas o cache nosso
  evita latência (até 60s×N) e rate-limit nosso — Redis é a fonte de verdade local.

Chave: trecho canônico (IATAs ordenados) + datas + trip + flex.
Hit → não chama SerpAPI; resposta traz cache_hit=true.
O cliente ainda é debitado — o hit é margem nossa, não desconto.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("vooai.quote_cache")

DEFAULT_TTL_SEC = 1200  # 20 minutos
KEY_PREFIX = "vooai:quote:v1:"

_memory: dict[str, tuple[float, str]] = {}
_memory_lock = threading.Lock()
_redis_client = None
_redis_failed = False


def cache_ttl_sec() -> int:
    raw = os.getenv("VOOAI_QUOTE_CACHE_TTL_SEC", str(DEFAULT_TTL_SEC))
    try:
        return max(60, int(raw))  # piso 1 min
    except ValueError:
        return DEFAULT_TTL_SEC


def redis_url() -> str | None:
    url = (os.getenv("REDIS_URL") or os.getenv("VOOAI_REDIS_URL") or "").strip()
    return url or None


def _get_redis():
    global _redis_client, _redis_failed
    # Re-tenta após falha (não sticky eterno — box compartilha rede)
    if _redis_failed and _redis_client is None:
        # cooldown simples via atributo no módulo
        last = getattr(_get_redis, "_last_try", 0.0)
        if time.time() - last < 5.0:
            return None
        _get_redis._last_try = time.time()  # type: ignore[attr-defined]
        _redis_failed = False
    if _redis_client is not None:
        return _redis_client
    url = redis_url()
    if not url:
        return None
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=1.5,
            socket_timeout=2.0,
            health_check_interval=30,
            max_connections=20,
        )
        client.ping()
        _redis_client = client
        _redis_failed = False
        logger.info("quote_cache: Redis conectado (%s)", url.split("@")[-1])
        return _redis_client
    except Exception as exc:  # noqa: BLE001
        _redis_failed = True
        _redis_client = None
        _get_redis._last_try = time.time()  # type: ignore[attr-defined]
        logger.warning("quote_cache: Redis indisponível (%s) — usando memória", exc)
        return None


def redis_ok() -> bool:
    client = _get_redis()
    if client is None:
        return False
    try:
        client.ping()
        return True
    except Exception:
        return False


def backend_name() -> str:
    if redis_ok():
        return "redis"
    return "memory"


def make_cache_key(
    *,
    iatas_origin: list[str],
    iatas_destination: list[str],
    date: str,
    return_date: str | None,
    flex_dates: str,
) -> str:
    o = ",".join(sorted({i.upper() for i in iatas_origin}))
    d = ",".join(sorted({i.upper() for i in iatas_destination}))
    flex = (flex_dates or "off").strip().lower()
    raw = f"{o}|{d}|{date}|{return_date or ''}|{flex}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"{KEY_PREFIX}{digest}"


def get(key: str) -> dict[str, Any] | None:
    ttl = cache_ttl_sec()
    client = _get_redis()
    if client is not None:
        try:
            blob = client.get(key)
            if not blob:
                return None
            data = json.loads(blob)
            if isinstance(data, dict):
                return data
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("quote_cache get redis fail: %s", exc)

    now = time.time()
    with _memory_lock:
        hit = _memory.get(key)
        if not hit:
            return None
        expires, blob = hit
        if expires < now:
            _memory.pop(key, None)
            return None
        try:
            data = json.loads(blob)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            _memory.pop(key, None)
            return None


def set(key: str, payload: dict[str, Any], *, ttl: int | None = None) -> None:
    ttl = ttl if ttl is not None else cache_ttl_sec()
    # Não cachear metadados voláteis de request anterior
    to_store = {k: v for k, v in payload.items() if k not in ("cache_hit", "cache_backend", "cache_ttl_sec")}
    blob = json.dumps(to_store, ensure_ascii=False, default=str)
    client = _get_redis()
    if client is not None:
        try:
            client.setex(key, ttl, blob)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("quote_cache set redis fail: %s", exc)

    with _memory_lock:
        _memory[key] = (time.time() + ttl, blob)
        # GC leve
        if len(_memory) > 2000:
            now = time.time()
            dead = [k for k, (exp, _) in _memory.items() if exp < now]
            for k in dead[:500]:
                _memory.pop(k, None)


def wrap_cached_payload(payload: dict[str, Any], *, hit: bool) -> dict[str, Any]:
    out = dict(payload)
    out["cache_hit"] = hit
    out["cache_backend"] = backend_name()
    out["cache_ttl_sec"] = cache_ttl_sec()
    return out
