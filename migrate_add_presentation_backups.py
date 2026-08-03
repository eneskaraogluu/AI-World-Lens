"""Create only the additive Presentation Backup table.

Inspect this script and take the normal database backup before running it on
SQL Server. It does not alter or delete experiments, results, or image assets.
"""

from backend.core.database import engine
from backend.models import models as legacy_models  # noqa: F401
from backend.models.presentation_models import PresentationBackup


def migrate(bind=engine) -> None:
    PresentationBackup.__table__.create(bind=bind, checkfirst=True)
    for index in PresentationBackup.__table__.indexes:
        index.create(bind=bind, checkfirst=True)


if __name__ == "__main__":
    migrate()
    print("presentation_backups table is ready (existing data was not modified).")
