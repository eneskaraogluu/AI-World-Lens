from sqlalchemy import create_engine, inspect

from backend.models.base import Base
from backend.models.models import Experiment, Prompt  # noqa: F401
from migrate_add_presentation_backups import migrate


engine = create_engine("sqlite://")
# Only referenced legacy tables are prepared; the migration itself must add
# exactly the presentation table and remain idempotent.
Base.metadata.tables["categories"].create(engine)
Base.metadata.tables["prompts"].create(engine)
Base.metadata.tables["experiments"].create(engine)
migrate(engine)
migrate(engine)
tables = set(inspect(engine).get_table_names())
assert "presentation_backups" in tables
assert "results" not in tables
indexes = inspect(engine).get_indexes("presentation_backups")
assert any(item["name"] == "uq_presentation_backup_single_active" and item["unique"] for item in indexes)
print("PRESENTATION MIGRATION: PASS")
