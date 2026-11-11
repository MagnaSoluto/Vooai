"""Rate limit barato — Redis se disponível, senão memória."""

from __future__ import annotations

import ipaddress
import os
import threading
import time

from . import quote_cache

_mem: dict[str, list[float]] = {}
_lock = threading.Lock()


def rate_limit_per_minute() -> int:
    try:
        return max(1, int(os.getenv("VOOAI_RATE_LIMIT_PER_MIN", "30")))
    except ValueError:
        return 30


def client_ip(request) -> str:
    """IP real do cliente.

    Em prod a API só é alcançável pelo Caddy (rede docker interna), então
    `request.client.host` é sempre o IP do proxy. Só confiamos em
    X-Forwarded-For quando o peer é privado/loopback (o proxy), e usamos o
    último salto — o que o proxy acrescentou, não o que o cliente forjou.
    """
    peer = request.client.host if request.client else ""
    try:
        peer_ip = ipaddress.ip_address(peer)
        trusted = peer_ip.is_private or peer_ip.is_loopback
    except ValueError:
        trusted = False
    if trusted:
        xff = request.headers.get("x-forwarded-for") or ""
        hops = [h.strip() for h in xff.split(",") if h.strip()]
        if hops:
            try:
                return str(ipaddress.ip_address(hops[-1]))
            except ValueError:
                pass
    return peer or "anon"


def check_rate_limit(key: str, *, limit: int | None = None, window: float = 60.0) -> None:
    """Raises RuntimeError se excedido (main traduz para 429)."""
    limit = limit if limit is not None else rate_limit_per_minute()
    now = time.time()
    redis_key = f"vooai:rl:{key}"
    client = None
    try:
        # reuse quote_cache redis
        if quote_cache.redis_ok():
            import redis as _redis  # noqa: F401

            client = quote_cache._get_redis()
    except Exception:
        client = None

    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.zremrangebyscore(redis_key, 0, now - window)
            pipe.zadd(redis_key, {str(now): now})
            pipe.zcard(redis_key)
            pipe.expire(redis_key, int(window) + 5)
            _removed, _added, count, _exp = pipe.execute()
            if int(count) > limit:
                raise RuntimeError("Muitas tentativas. Aguarde um pouco e tente de novo.")
            return
        except RuntimeError:
            raise
        except Exception:
            pass

    with _lock:
        if len(_mem) > 20_000:  # evita crescer sem limite com chaves descartáveis
            for k in [k for k, v in _mem.items() if not v or v[-1] <= now - 3600]:
                _mem.pop(k, None)
        bucket = [t for t in _mem.get(key, []) if t > now - window]
        bucket.append(now)
        _mem[key] = bucket
        if len(bucket) > limit:
            raise RuntimeError("Muitas tentativas. Aguarde um pouco e tente de novo.")
