"""Idempotent container bootstrap for a fresh persistent database."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.database import SessionLocal, engine
from backend.models.base import Base
from backend.models import models as legacy_models  # noqa: F401
from backend.models import presentation_models as presentation_models  # noqa: F401
from backend.models import research_models as research_models  # noqa: F401
from backend.services.research_prompt_service import seed_prompt_catalogue
from scripts.load_prompts import load_prompts, project_root


def bootstrap() -> None:
    Base.metadata.create_all(bind=engine)
    load_prompts(str(Path(project_root) / "data" / "prompts.json"))
    db = SessionLocal()
    try:
        seed_prompt_catalogue(db)
    finally:
        db.close()
    print("Container database is ready.")


if __name__ == "__main__":
    bootstrap()
