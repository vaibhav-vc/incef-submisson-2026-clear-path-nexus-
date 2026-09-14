from __future__ import annotations

from typing import Any

from redis.asyncio import Redis

from app.core.config import settings


def create_redis_client(**kwargs: Any) -> Redis:
    """Create a client from one URL so TLS, credentials, and DB are preserved."""

    return Redis.from_url(settings.REDIS_URL, **kwargs)
