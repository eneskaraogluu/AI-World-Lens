import os
import tempfile
from pathlib import Path
from uuid import uuid4


db_file = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
db_file.close()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(db_file.name).as_posix()}"
os.environ["OPENAI_API_KEY"] = "offline-openai-placeholder"
os.environ["GEMINI_API_KEY"] = "offline-gemini-placeholder"

from fastapi.testclient import TestClient

from backend.core.database import SessionLocal, engine
from backend.main import app
from backend.models.base import Base
from backend.models.models import Category, Experiment, Prompt, Result, ResultAnalysis
import backend.services.presentation_backup_service as service
from backend.services.queue_worker import queue_worker


PNG = b"\x89PNG\r\n\x1a\n" + b"api-presentation-backup"


def seed_source(asset_root: Path):
    db = SessionLocal()
    category = Category(name="Presentation")
    db.add(category)
    db.flush()
    prompt = Prompt(category_id=category.id, text="An engineer")
    experiment = Experiment(name="Complete source", model_name="openai-image", status="completed")
    db.add_all([prompt, experiment])
    db.flush()
    for index in range(1, 11):
        filename = f"api-{index}.png"
        (asset_root / filename).write_bytes(PNG + bytes([index]))
        result = Result(
            experiment_id=experiment.id, prompt_id=prompt.id,
            generation_id=f"api-{index}", image_reference=filename,
            model_name="openai-image", analysis_status="success",
        )
        db.add(result)
        db.flush()
        db.add(ResultAnalysis(
            result_id=result.id, provider="gemini", model_name="gemini-offline",
            revision=1, status="success", detected_age_group="25-34",
            detected_gender="Female" if index % 2 == 0 else "Male",
            detected_person_count=1, is_active=True,
        ))
    db.commit()
    result = experiment.id
    db.close()
    return result


def run():
    Base.metadata.create_all(engine)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        original_generations, original_backups = service.GENERATIONS_ROOT, service.BACKUP_ROOT
        service.GENERATIONS_ROOT, service.BACKUP_ROOT = root, root / "presentation_backups"
        try:
            experiment_id = seed_source(root)
            with TestClient(app) as client:
                empty_preflight = client.get("/api/presentation/preflight")
                assert empty_preflight.status_code == 200
                assert empty_preflight.json()["status"] == "NOT_READY"
                assert any(item["status"] == "FAIL" for item in empty_preflight.json()["checks"])
                missing = client.post(f"/api/presentation/backups/from-experiment/{uuid4()}", json={})
                assert missing.status_code == 404
                created = client.post(
                    f"/api/presentation/backups/from-experiment/{experiment_id}",
                    json={"name": "Engineer Presentation Backup"},
                )
                assert created.status_code == 200
                backup = created.json()
                assert backup["status"] == "PRESENTATION_READY"
                duplicate = client.post(f"/api/presentation/backups/from-experiment/{experiment_id}", json={})
                assert duplicate.json()["id"] == backup["id"]
                activated = client.post(f"/api/presentation/backups/{backup['id']}/activate")
                assert activated.status_code == 200 and activated.json()["is_active"] is True
                assert client.get("/api/presentation/backups/active").json()["id"] == backup["id"]
                preflight = client.get("/api/presentation/preflight").json()
                assert preflight["status"] == "PRESENTATION_READY"
                assert all(item["status"] == "PASS" for item in preflight["checks"])

                db = SessionLocal()
                before_results = db.query(Result).count()
                db.close()
                before_queue = queue_worker.queue.qsize()
                replay = client.get(f"/api/presentation/backups/{backup['id']}/replay")
                assert replay.status_code == 200
                body = replay.json()
                assert body["mode"] == "prepared_replay" and body["is_live"] is False
                assert len(body["results"]) == len(body["trajectory"]) == 10
                assert queue_worker.queue.qsize() == before_queue
                db = SessionLocal()
                assert db.query(Result).count() == before_results
                db.close()
                serialized = replay.text
                assert "offline-openai-placeholder" not in serialized
                assert "offline-gemini-placeholder" not in serialized
        finally:
            service.GENERATIONS_ROOT, service.BACKUP_ROOT = original_generations, original_backups
            engine.dispose()
            Path(db_file.name).unlink(missing_ok=True)


if __name__ == "__main__":
    run()
    print("PRESENTATION BACKUP API: PASS")
