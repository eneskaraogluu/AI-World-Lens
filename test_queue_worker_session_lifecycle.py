"""Regression test for Result ids surviving commit/close in queue events."""

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.services.queue_worker as queue_module
from backend.models.base import Base
from backend.models.models import Category, Experiment, Prompt, ResultAnalysis
from backend.services.queue_worker import QueueWorker
from backend.services.vision_base import VisionAnalysisOutcome


class FakeGenerator:
    model_name = "fake-image"
    model_version = "test"

    async def generate_image(self, _prompt, _seed):
        return "generated/session-lifecycle.png", 1, None


class FakeVisionAnalyzer:
    provider_name = "fake-vision"
    model_name = "fake-vision-test"

    async def analyze_image(self, _image_reference):
        return VisionAnalysisOutcome(
            {
                "detected_age_group": "35-44",
                "detected_gender": "Male",
                "detected_person_count": 1,
                "framing_status": "complete",
                "face_visibility": "clear",
                "demographic_codable": True,
                "quality_flags": [],
            },
            1,
        )


async def exercise_queue_worker():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine)
    db = test_session()
    try:
        category = Category(name="Regression")
        db.add(category)
        db.flush()
        prompt = Prompt(category_id=category.id, text="An engineer")
        experiment = Experiment(name="Session lifecycle", model_name="fake")
        db.add_all([prompt, experiment])
        db.commit()
        prompt_id = prompt.id
        experiment_id = experiment.id
    finally:
        db.close()

    worker = QueueWorker()
    worker._generator_instances["openai-image"] = FakeGenerator()
    original_session = queue_module.SessionLocal
    original_analyzer = queue_module.vision_analyzer
    queue_module.SessionLocal = test_session
    queue_module.vision_analyzer = FakeVisionAnalyzer()
    try:
        succeeded, error, failure_type, event = await worker._process_generation_task(
            {
                "prompt_text": "An engineer",
                "prompt_id": prompt_id,
                "experiment_id": experiment_id,
                "generator_type": "openai-image",
                "seed": None,
                "sample_index": 1,
            }
        )
    finally:
        queue_module.SessionLocal = original_session
        queue_module.vision_analyzer = original_analyzer

    assert succeeded is True
    assert error is None
    assert failure_type is None
    assert event["status"] == "success"
    assert event["result_id"]
    verify_db = test_session()
    try:
        assert verify_db.query(ResultAnalysis).count() == 1
    finally:
        verify_db.close()


if __name__ == "__main__":
    asyncio.run(exercise_queue_worker())
    print("PASS: queue event keeps the Result id after analysis commit and session close")
