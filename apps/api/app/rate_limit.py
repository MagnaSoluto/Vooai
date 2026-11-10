"""Rate limit barato — Redis se disponível, senão memória."""

from __future__ import annotations

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


def check_rate_limit(key: str) -> None:
    """Raises RuntimeError se excedido (main traduz para 429)."""
    limit = rate_limit_per_minute()
    window = 60.0
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
                raise RuntimeError(f"Rate limit: máx. {limit} req/min. Tente em breve.")
            return
        except RuntimeError:
            raise
        except Exception:
            pass

    with _lock:
        bucket = [t for t in _mem.get(key, []) if t > now - window]
        bucket.append(now)
        _mem[key] = bucket
        if len(bucket) > limit:
            raise RuntimeError(f"Rate limit: máx. {limit} req/min. Tente em breve.")
