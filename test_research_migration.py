"""Verify the additive migration twice on an isolated SQLite database."""

from sqlalchemy import create_engine, inspect

from migrate_add_research_core import ADDITIVE_TABLES, migrate


engine = create_engine("sqlite://")
first = migrate(engine)
second = migrate(engine)
tables = set(inspect(engine).get_table_names())

assert {table.name for table in ADDITIVE_TABLES}.issubset(tables)
assert "experiments" not in tables and "results" not in tables and "prompts" not in tables
assert first["definitions"] >= 60
assert second["created"] == 0

print("PASS: additive migration is isolated and idempotent on temporary SQLite")
