from alembic.config import Config
from alembic.script import ScriptDirectory


def test_evidence_signing_metadata_is_the_migration_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_current_head() == "20260831_14"
