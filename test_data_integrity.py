import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.base import Base
from backend.models.models import Category, Experiment, Prompt, Result
from backend.services.comparison_service import get_comparison


def run_checks() -> None:
    project_root = Path(__file__).resolve().parent
    prompts_payload = json.loads((project_root / "data" / "prompts.json").read_text(encoding="utf-8"))
    reference_payload = json.loads((project_root / "data" / "real_world_data.json").read_text(encoding="utf-8"))
    reference_prompts = {
        prompt_name: prompt_data
        for category in reference_payload.values()
        for prompt_name, prompt_data in category.items()
    }
    configured_prompts = {
        prompt_name
        for category in prompts_payload["categories"]
        for prompt_name in category["prompts"]
    }
    assert configured_prompts.issubset(reference_prompts.keys())
    for prompt_name in configured_prompts:
        reference = reference_prompts[prompt_name]
        assert reference.get("source")
        for dimension in ("gender_distribution", "age_group_distribution"):
            assert abs(sum(reference.get(dimension, {}).values()) - 100) < 0.01

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        category = Category(id=uuid4(), name="Occupations")
        prompt = Prompt(id=uuid4(), category=category, text="A CEO")
        experiment = Experiment(id=uuid4(), name="integrity", model_name="test", status="completed")
        db.add_all([category, prompt, experiment])
        db.commit()

        empty = get_comparison(db, prompt.id, experiment.id)
        assert empty["total_generations"] == 0
        assert empty["valid_gender_analyses"] == 0
        assert all(item["difference"] == 0 for item in empty["gender_comparison"].values())
        assert all(item["difference"] == 0 for item in empty["age_group_comparison"].values())

        db.add(Result(
            experiment_id=experiment.id,
            prompt_id=prompt.id,
            generation_id="failed-1",
            analysis_status="failed",
            image_reference="failed.png",
        ))
        db.commit()
        failed_only = get_comparison(db, prompt.id, experiment.id)
        assert failed_only["failed_generations"] == 1
        assert failed_only["total_generations"] == 0
        assert all(item["difference"] == 0 for item in failed_only["gender_comparison"].values())

        db.add(Result(
            experiment_id=experiment.id,
            prompt_id=prompt.id,
            generation_id="success-1",
            analysis_status="success",
            image_reference="success.png",
            detected_person_count=1,
            detected_gender="Male",
            detected_age_group="35-44",
        ))
        db.commit()
        measured = get_comparison(db, prompt.id, experiment.id)
        assert measured["total_generations"] == 1
        assert measured["valid_person_analyses"] == 1
        assert measured["valid_gender_analyses"] == 1
        assert measured["valid_age_analyses"] == 1
        assert sum(item["ai_percentage"] for item in measured["gender_comparison"].values()) == 100
        assert any(item["difference"] != 0 for item in measured["gender_comparison"].values())
    finally:
        db.close()


if __name__ == "__main__":
    run_checks()
    print("DATA INTEGRITY: PASS")
