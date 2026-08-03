"""Offline composition-quality gate coverage; no provider or real DB calls."""

import asyncio
import os
from uuid import uuid4

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["DATABASE_URL"] = "sqlite://"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.services.queue_worker as queue_module
from backend.models.base import Base
from backend.models.models import Category, Experiment, Prompt, Result
from backend.services.analysis_revision_service import effective_analyses
from backend.services.comparison_service import get_comparison
from backend.services.queue_worker import QueueWorker
from backend.services.openai_generator import OpenAIImageGenerator
from backend.services.vision_base import VisionAnalysisOutcome, demographic_quality_decision


class FakeGenerator:
    model_name = "fake-composition-generator"
    model_version = "composition-v2-test"

    def __init__(self):
        self.calls = 0

    async def generate_image(self, _prompt, _seed):
        self.calls += 1
        return f"quality-{self.calls}.png", 1, None


class FakeAnalyzer:
    provider_name = "gemini"
    model_name = "fake-quality-analyzer"

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def analyze_image(self, _reference):
        value = self.outcomes[self.calls]
        self.calls += 1
        return VisionAnalysisOutcome(value, 1)


def analysis(**overrides):
    value = {
        "detected_age_group": "25-34",
        "detected_gender": "Female",
        "detected_person_count": 1,
        "framing_status": "complete",
        "face_visibility": "clear",
        "demographic_codable": True,
        "quality_flags": [],
    }
    value.update(overrides)
    return value


async def run_checks():
    standardized = OpenAIImageGenerator._standardize_prompt("A doctor")
    for instruction in (
        "medium-wide environmental portrait",
        "top of the head to at least mid-thigh",
        "face must be unobscured",
        "Do not apply blur",
        "Do not crop the head",
        "Do not use an extreme close-up",
    ):
        assert instruction in standardized
    assert "A doctor" in standardized and "force gender" in standardized

    cases = [
        analysis(),
        analysis(face_visibility="blurred", quality_flags=["face_blurred"]),
        analysis(framing_status="head_cropped", quality_flags=["head_cropped"]),
        analysis(face_visibility="not_visible", demographic_codable=False, quality_flags=["face_obscured"]),
        analysis(detected_person_count=2, demographic_codable=False, quality_flags=["multiple_primary_people"]),
        {"detected_age_group": "25-34", "detected_gender": "Female", "detected_person_count": 1},
    ]
    decisions = [demographic_quality_decision(item) for item in cases]
    assert decisions[0][0] is True
    assert decisions[1][1] == "face_blurred"
    assert decisions[2][1] == "head_cropped"
    assert decisions[3][1] == "face_not_visible"
    assert decisions[4][1] == "multiple_primary_people"
    assert decisions[5][0] is False, "Missing quality fields must not default to success"

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    category = Category(id=uuid4(), name="Quality Test")
    prompt = Prompt(id=uuid4(), category=category, text="A doctor")
    experiment = Experiment(id=uuid4(), name="Quality gate", model_name="fake", status="running")
    db.add_all([category, prompt, experiment])
    db.commit()

    worker = QueueWorker()
    generator = FakeGenerator()
    analyzer = FakeAnalyzer(cases)
    worker._generator_instances["openai-image"] = generator
    original_factory = queue_module.SessionLocal
    original_analyzer = queue_module.vision_analyzer
    queue_module.SessionLocal = factory
    queue_module.vision_analyzer = analyzer
    try:
        await worker.register_job(experiment.id, prompt.id, len(cases))
        events = []
        for index in range(len(cases)):
            task = {
                "prompt_text": prompt.text,
                "prompt_id": prompt.id,
                "experiment_id": experiment.id,
                "generator_type": "openai-image",
                "seed": None,
                "sample_index": index + 1,
                "quality_retry_limit": 0,
            }
            succeeded, error, failure_type, event = await worker._process_generation_task(task)
            await worker._complete_task(task, succeeded, error, failure_type, event)
            events.append(event)
    finally:
        queue_module.SessionLocal = original_factory
        queue_module.vision_analyzer = original_analyzer

    assert generator.calls == 6 and analyzer.calls == 6, "One exclusion must not stop later tasks"
    assert [event["status"] for event in events] == ["success", "unverified", "unverified", "unverified", "unverified", "unverified"]
    assert "face not clearly visible" in events[1]["reason"].lower()
    assert "head cropped" in events[2]["reason"].lower()
    job = await worker.get_job(experiment.id)
    assert job["succeeded"] == 1 and job["unverified"] == 5
    comparison = get_comparison(db, prompt.id, experiment.id)
    assert comparison["validated_samples"] == 1
    assert comparison["unverified_samples"] == 5
    assert comparison["valid_gender_analyses"] == 1
    assert comparison["valid_age_analyses"] == 1
    assert comparison["gender_comparison"]["Female"]["ai_percentage"] == 100.0

    # A presentation composition failure gets exactly one replacement attempt.
    replacement_generator = FakeGenerator()
    replacement_analyzer = FakeAnalyzer([
        analysis(framing_status="head_cropped", quality_flags=["head_cropped"]),
        analysis(),
    ])
    worker._generator_instances["openai-image"] = replacement_generator
    queue_module.SessionLocal = factory
    queue_module.vision_analyzer = replacement_analyzer
    try:
        succeeded, error, failure_type, replacement_event = await worker._process_generation_task({
            "prompt_text": prompt.text,
            "prompt_id": prompt.id,
            "experiment_id": experiment.id,
            "generator_type": "openai-image",
            "seed": None,
            "sample_index": 7,
        })
    finally:
        queue_module.SessionLocal = original_factory
        queue_module.vision_analyzer = original_analyzer
    assert succeeded is True and error is None and failure_type is None
    assert replacement_generator.calls == 2 and replacement_analyzer.calls == 2
    assert replacement_event["status"] == "success"
    assert replacement_event["composition_retry_count"] == 1
    assert replacement_event["image_reference"] == "quality-2.png"

    legacy_experiment = Experiment(id=uuid4(), name="Legacy", model_name="legacy", status="completed")
    db.add(legacy_experiment)
    db.add(Result(
        experiment_id=legacy_experiment.id, prompt_id=prompt.id,
        image_reference="legacy.png", model_name="legacy-image",
        analysis_status="success", detected_person_count=1,
        detected_gender="Male", detected_age_group="35-44",
    ))
    db.commit()
    legacy, _ = effective_analyses(db, prompt.id, legacy_experiment.id)
    assert len(legacy) == 1 and legacy[0].status == "success"
    assert legacy[0].quality_assessed is False, "Legacy quality must not be invented"
    db.close()


if __name__ == "__main__":
    asyncio.run(run_checks())
    print("QUALITY GATE: PASS")
