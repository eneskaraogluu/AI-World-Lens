import json
import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.models.base import Base
from backend.models.models import Category, Experiment, Prompt, Result, ResultAnalysis
from backend.models.presentation_models import PresentationBackup
import backend.services.presentation_backup_service as service


PNG = b"\x89PNG\r\n\x1a\n" + b"presentation-backup-test"


def make_db():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def source_experiment(db, asset_root: Path, *, count=10, validated=10, status="completed", label="engineer"):
    category = db.query(Category).filter(Category.name == "Occupations").first()
    if not category:
        category = Category(name="Occupations")
        db.add(category)
        db.flush()
    prompt = Prompt(category_id=category.id, text=f"An {label} {uuid4().hex[:6]}")
    experiment = Experiment(name=f"Backup {label}", model_name="openai-image", status=status)
    db.add_all([prompt, experiment])
    db.flush()
    for index in range(1, count + 1):
        filename = f"{experiment.id}-{index}.png"
        (asset_root / filename).write_bytes(PNG + bytes([index]))
        result = Result(
            experiment_id=experiment.id, prompt_id=prompt.id,
            generation_id=f"gen-{index}", image_reference=filename,
            model_name="openai-image", analysis_status="success" if index <= validated else "unverified",
        )
        db.add(result)
        db.flush()
        db.add(ResultAnalysis(
            result_id=result.id, provider="gemini", model_name="gemini-test", revision=1,
            status="success" if index <= validated else "unverified",
            detected_age_group="25-34" if index <= validated else "Unclear",
            detected_gender="Female" if index % 2 == 0 else "Male",
            detected_person_count=1 if index <= validated else 0,
            is_active=True,
        ))
    db.commit()
    return experiment


def expect_error(callback, code):
    try:
        callback()
    except service.PresentationBackupError as exc:
        assert exc.status_code == code
    else:
        raise AssertionError("Expected PresentationBackupError")


def expect_integrity_error(db, row):
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    else:
        raise AssertionError("Expected database constraint to reject the row")


def clone_backup(row, **overrides):
    values = {
        column.name: getattr(row, column.name)
        for column in PresentationBackup.__table__.columns
        if column.name not in {"id", "created_at"}
    }
    values.update(id=uuid4(), is_active=False, **overrides)
    return PresentationBackup(**values)


def run():
    engine, db = make_db()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        original_generations, original_backups = service.GENERATIONS_ROOT, service.BACKUP_ROOT
        service.GENERATIONS_ROOT = root
        service.BACKUP_ROOT = root / "presentation_backups"
        try:
            processing = source_experiment(db, root, status="processing", label="processing")
            expect_error(lambda: service.create_backup(db, processing.id), 409)

            empty = source_experiment(db, root, validated=0, label="empty")
            expect_error(lambda: service.create_backup(db, empty.id), 422)

            complete = source_experiment(db, root, label="complete")
            first = service.create_backup(db, complete.id)
            assert first.status == "PRESENTATION_READY"
            assert first.validated_count == first.requested_count == 10
            assert first.verified_at is not None
            assert service.create_backup(db, complete.id).id == first.id
            assert db.query(PresentationBackup).filter(PresentationBackup.source_experiment_id == complete.id).count() == 1

            manifest = json.loads(first.manifest_json)
            assert first.manifest_hash == service.sha256_bytes(service.canonical_json(manifest).encode("utf-8"))
            assert "api_key" not in first.manifest_json.lower()
            verification = service.verify_backup(db, first)
            assert verification["status"] == "PRESENTATION_READY"
            assert all(item["status"] == "PASS" for item in verification["checks"])

            before_results = db.query(Result).count()
            replay = service.replay_payload(db, first)
            assert replay["mode"] == "prepared_replay" and replay["is_live"] is False
            assert len(replay["results"]) == len(replay["trajectory"]) == 10
            assert [item["sample_index"] for item in replay["results"]] == list(range(1, 11))
            assert replay["trajectory"][-1] == {"n": 10, "female_share": 50.0}
            assert replay["final_distribution"]["gender"] == {"Male": 5, "Female": 5}
            assert replay["final_distribution"]["age"] == {"25-34": 10}
            assert db.query(Result).count() == before_results

            expect_integrity_error(db, clone_backup(
                first,
                manifest_hash=service.sha256_bytes(b"duplicate-source-revision"),
            ))
            expect_integrity_error(db, clone_backup(
                first,
                source_experiment_id=uuid4(),
                analysis_revision_id=999,
                manifest_hash=service.sha256_bytes(b"missing-source"),
            ))

            partial = source_experiment(db, root, validated=8, label="partial")
            second = service.create_backup(db, partial.id)
            assert second.status == "READY_WITH_WARNINGS"
            assert (second.requested_count, second.validated_count, second.unverified_count) == (10, 8, 2)
            service.activate_backup(db, first)
            service.activate_backup(db, second)
            db.refresh(first)
            assert second.is_active is True and first.is_active is False
            assert db.query(PresentationBackup).count() == 2

            corrupt_path = root / json.loads(second.manifest_json)["results"][0]["image_path"]
            corrupt_path.write_bytes(b"not-an-image")
            broken = service.verify_backup(db, second)
            assert broken["status"] == "BROKEN"
            assert any(item["name"] == "assets" and item["status"] == "FAIL" for item in broken["checks"])

            missing_path = root / json.loads(first.manifest_json)["results"][0]["image_path"]
            missing_path.unlink()
            missing = service.verify_backup(db, first)
            assert missing["status"] == "BROKEN"
            assert any(item["name"] == "assets" and item["status"] == "FAIL" for item in missing["checks"])

            schema = inspect(engine)
            foreign_keys = schema.get_foreign_keys("presentation_backups")
            assert {item["referred_table"] for item in foreign_keys} == {"experiments", "prompts"}
            unique_names = {item["name"] for item in schema.get_unique_constraints("presentation_backups")}
            assert "uq_presentation_backup_source_revision" in unique_names
            unique_indexes = {item["name"] for item in schema.get_indexes("presentation_backups") if item["unique"]}
            assert "uq_presentation_backup_single_active" in unique_indexes
        finally:
            service.GENERATIONS_ROOT, service.BACKUP_ROOT = original_generations, original_backups
            db.close()


if __name__ == "__main__":
    run()
    print("PRESENTATION BACKUP: PASS")
