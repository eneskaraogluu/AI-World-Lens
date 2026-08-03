"""Install the additive Ortalama Dunya research schema.

IMPORTANT: inspect this file and take the normal database backup before running
it against SQL Server.  It never drops, truncates, alters, or rewrites existing
tables.  Existing experiments, results, prompts, and images remain untouched.
"""

from backend.core.database import SessionLocal, engine
# Register referenced legacy table metadata without creating or altering it.
from backend.models import models as legacy_models  # noqa: F401
from backend.models.research_models import (
    BenchmarkSnapshot,
    BenchmarkMapping,
    Campaign,
    CampaignPrompt,
    PromptDefinition,
    PromptVariant,
    ResearchAnalysisV2,
    ResearchTask,
    Study,
    StudyWave,
)
from backend.services.research_prompt_service import seed_prompt_catalogue


ADDITIVE_TABLES = (
    Study.__table__,
    StudyWave.__table__,
    PromptDefinition.__table__,
    PromptVariant.__table__,
    Campaign.__table__,
    CampaignPrompt.__table__,
    ResearchTask.__table__,
    ResearchAnalysisV2.__table__,
    BenchmarkSnapshot.__table__,
    BenchmarkMapping.__table__,
)


def migrate(bind=engine) -> dict:
    for table in ADDITIVE_TABLES:
        table.create(bind=bind, checkfirst=True)
    db = SessionLocal(bind=bind)
    try:
        return seed_prompt_catalogue(db)
    finally:
        db.close()


if __name__ == "__main__":
    summary = migrate()
    print(
        "Research schema is ready; existing data was not modified. "
        f"Catalogue: {summary['concepts']} concepts / {summary['definitions']} language-specific definitions."
    )
