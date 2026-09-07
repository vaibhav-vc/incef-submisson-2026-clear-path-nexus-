"""Makes `import app...` work when pytest is run from backend/.

Without this, pytest's rootdir handling means the test suite only imports
correctly if the package is installed. Keeping it here means `pytest` just
works from a fresh clone.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def configured_test_evidence_signing_key(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(
        settings,
        "EVIDENCE_SIGNING_KEY",
        "unit-test-evidence-signing-key-0123456789",
        raising=False,
    )
    monkeypatch.setattr(settings, "EVIDENCE_SIGNING_KEY_ID", "test-current-key", raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_VERIFICATION_KEYS", {}, raising=False)
