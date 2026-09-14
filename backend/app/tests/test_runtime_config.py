from unittest.mock import patch

import pytest

from app.core.config import normalize_async_database_url, settings
from app.core.redis import create_redis_client


def test_supabase_database_url_is_normalized_for_asyncpg() -> None:
    raw = (
        "postgresql://postgres.project:p%40ss@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"
        "?sslmode=require&application_name=clearpath"
    )

    normalized = normalize_async_database_url(raw)

    assert normalized.startswith("postgresql+asyncpg://")
    assert "p%40ss" in normalized
    assert "ssl=require" in normalized
    assert "sslmode=" not in normalized
    assert "application_name=clearpath" in normalized


def test_supabase_transaction_pooler_is_rejected_before_startup() -> None:
    transaction_url = (
        "postgresql://postgres.project:password@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
        "?sslmode=require"
    )

    with pytest.raises(RuntimeError, match="transaction-pooler"):
        normalize_async_database_url(transaction_url)


def test_managed_redis_url_is_forwarded_without_losing_tls_or_credentials(
    monkeypatch,
) -> None:
    managed_url = "rediss://default:token@managed-redis.example:6380/2"
    monkeypatch.setattr(settings, "REDIS_URL", managed_url)

    with patch("app.core.redis.Redis.from_url") as from_url:
        create_redis_client(socket_connect_timeout=2)

    from_url.assert_called_once_with(managed_url, socket_connect_timeout=2)
