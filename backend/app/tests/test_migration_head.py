import ast
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_supabase_data_api_lockdown_is_the_migration_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_current_head() == "20260913_15"


def test_supabase_lockdown_covers_every_application_table() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    lockdown = script.get_revision("20260913_15").module
    created_tables: set[str] = set()
    for path in Path("alembic/versions").glob("*.py"):
        if path.name.startswith("20260913_15"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_table"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                created_tables.add(node.args[0].value)

    assert set(lockdown.APPLICATION_TABLES) == created_tables
