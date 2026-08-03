"""Offline API/queue integration using fake generation and fake vision."""

import os
import tempfile
import time
from pathlib import Path


db_file = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
db_file.close()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(db_file.name).as_posix()}"
os.environ["OPENAI_API_KEY"] = "offline-test-placeholder"
os.environ["GEMINI_API_KEY"] = "offline-test-placeholder"

from fastapi.testclient import TestClient

import backend.services.queue_worker as queue_module
from backend.core.config import settings
from backend.core.database import SessionLocal, engine
from backend.main import app
from backend.models.base import Base
from backend.models.models import Category, Prompt
from backend.services.vision_base import VisionAnalysisOutcome


TEST_MARKERS = ("integration",)


class FakeGenerator:
    model_name = "offline-fake-image"
    model_version = "1.0"

    async def generate_image(self, _prompt, _seed):
        return "offline-fake.png", 1, None


class FakeAnalyzer:
    provider_name = "fake-vision"
    model_name = "fake-vision-1"

    async def analyze_image(self, _reference):
        return VisionAnalysisOutcome({
            "detected_age_group": "25-34", "detected_gender": "Female",
            "detected_person_count": 1,
            "framing_status": "complete", "face_visibility": "clear",
            "demographic_codable": True, "quality_flags": [],
        }, 1)


def run():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        category = Category(name="Offline")
        db.add(category)
        db.flush()
        prompt = Prompt(category_id=category.id, text="A teacher")
        db.add(prompt)
        db.commit()
        prompt_id = str(prompt.id)
    finally:
        db.close()

    worker = queue_module.queue_worker
    original_generator = worker._generator_instances["openai-image"]
    original_analyzer = queue_module.vision_analyzer
    worker._generator_instances["openai-image"] = FakeGenerator()
    queue_module.vision_analyzer = FakeAnalyzer()
    try:
        with TestClient(app) as client:
            experiment = client.post("/api/experiments/", json={
                "name": "Offline fake API", "model_name": "offline-fake",
            })
            assert experiment.status_code == 200
            experiment_id = experiment.json()["id"]
            queued = client.post(f"/api/experiments/{experiment_id}/run", json={
                "prompt_id": prompt_id, "iterations": 1,
            })
            assert queued.status_code == 200
            status = None
            for _ in range(50):
                status = client.get(f"/api/experiments/{experiment_id}/status").json()
                if status["status"] in {"completed", "failed"}:
                    break
                time.sleep(.02)
            assert status and status["status"] == "completed"
            assert status["succeeded"] == 1
            results = client.get(f"/api/experiments/{experiment_id}/results").json()
            assert len(results) == 1 and results[0]["analysis_status"] == "success"
    finally:
        worker._generator_instances["openai-image"] = original_generator
        queue_module.vision_analyzer = original_analyzer
        engine.dispose()
        Path(db_file.name).unlink(missing_ok=True)


if __name__ == "__main__":
    run()
    print("MOCK API (OFFLINE): PASS")
