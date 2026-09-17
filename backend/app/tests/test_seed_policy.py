"""Synthetic fixtures must never enter a real-only database via the seed CLI."""

import os
import subprocess
import sys
from unittest.mock import Mock

import pytest

from scripts import seed as seed_module


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("environment", "real_only", "demo_enabled", "message"),
    [
        ("development", True, True, "REAL_DATA_ONLY"),
        ("development", True, False, "REAL_DATA_ONLY"),
        ("development", False, False, "disabled"),
        ("production", False, True, "only in development"),
        ("staging", False, True, "only in development"),
        ("unknown", False, True, "only in development"),
    ],
)
async def test_seed_rejected_before_database_access(
    monkeypatch, environment, real_only, demo_enabled, message
):
    monkeypatch.setattr(seed_module.settings, "ENVIRONMENT", environment)
    monkeypatch.setattr(seed_module.settings, "REAL_DATA_ONLY", real_only)
    monkeypatch.setattr(seed_module.settings, "DEMO_DATA_ENABLED", demo_enabled)
    database = Mock(side_effect=AssertionError("Database must not be opened"))
    monkeypatch.setattr(seed_module, "AsyncSessionLocal", database)
    with pytest.raises(RuntimeError, match=message):
        await seed_module.seed()
    database.assert_not_called()


def test_conflicting_modes_rejected_during_configuration():
    environment = dict(os.environ)
    environment.update(
        ENVIRONMENT="development", REAL_DATA_ONLY="true", DEMO_DATA_ENABLED="true"
    )
    result = subprocess.run(
        [sys.executable, "-c", "import app.core.config"],
        env=environment, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "DEMO_DATA_ENABLED cannot be combined with REAL_DATA_ONLY" in result.stderr
