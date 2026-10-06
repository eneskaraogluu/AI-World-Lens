"""Create and verify immutable, provider-free presentation snapshots."""

import hashlib
import json
import os
import shutil
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import inspect, or_
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.models.models import Experiment, Prompt, Result
from backend.models.presentation_models import PresentationBackup
from backend.services.analysis_revision_service import effective_analyses, is_generated_result
from backend.services.comparison_service import get_comparison
from backend.services.image_storage import blob_enabled, read_image_bytes_sync, save_image_bytes_sync
from backend.services.vision_base import guess_mime_type


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATIONS_ROOT = PROJECT_ROOT / "frontend" / "assets" / "generations"
BACKUP_ROOT = GENERATIONS_ROOT / "presentation_backups"
TERMINAL_STATUSES = {"completed", "failed", "rejected"}


class PresentationBackupError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def presentation_backup_schema_available(db: Session) -> bool:
    return inspect(db.get_bind()).has_table(PresentationBackup.__tablename__)


def canonical_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_image(reference: str) -> tuple[Path | None, bytes, str]:
    if not reference or reference.startswith(("http://", "https://")):
        raise PresentationBackupError("Presentation backups require managed image assets")
    try:
        if reference.startswith("blob:"):
            data = read_image_bytes_sync(reference)
            source = None
        else:
            relative = Path(reference)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe local image reference")
            source = (GENERATIONS_ROOT / relative).resolve()
            if GENERATIONS_ROOT.resolve() not in source.parents or not source.is_file():
                raise FileNotFoundError(relative.name)
            data = source.read_bytes()
    except (OSError, ValueError) as exc:
        raise PresentationBackupError("Generated image is missing or unreadable") from exc
    return source, data, guess_mime_type(data)


def _asset_extension(mime: str) -> str:
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime]


def _counts(results: list[Result], analyses) -> dict[str, int]:
    generated = sum(is_generated_result(result) for result in results)
    validated = sum(item.status == "success" for item in analyses)
    unverified = max(0, generated - validated)
    failed = max(0, len(results) - generated)
    return {
        "requested": len(results),
        "completed": len(results),
        "generated": generated,
        "validated": validated,
        "unverified": unverified,
        "failed": failed,
    }


def _readiness(counts: dict[str, int]) -> str:
    ideal = (
        counts["requested"] == 10
        and counts["completed"] == 10
        and counts["generated"] == 10
        and counts["validated"] == 10
        and counts["unverified"] == 0
        and counts["failed"] == 0
    )
    return "PRESENTATION_READY" if ideal else "READY_WITH_WARNINGS"


def _backup_payload(row: PresentationBackup, *, include_manifest: bool = False) -> dict:
    payload = {
        "id": str(row.id), "name": row.name,
        "source_experiment_id": str(row.source_experiment_id),
        "prompt_id": str(row.prompt_id), "prompt_text": row.prompt_text,
        "status": row.status, "is_active": row.is_active,
        "counts": {
            "requested": row.requested_count, "completed": row.completed_count,
            "generated": row.generated_count, "validated": row.validated_count,
            "unverified": row.unverified_count, "failed": row.failed_count,
        },
        "generation": {"provider": row.generator_provider, "model": row.generator_model},
        "analysis": {
            "provider": row.analyzer_provider, "model": row.analyzer_model,
            "revision_id": row.analysis_revision_id,
        },
        "manifest_version": row.manifest_version, "manifest_hash": row.manifest_hash,
        "created_at": row.created_at, "verified_at": row.verified_at,
        "last_replayed_at": row.last_replayed_at,
    }
    if include_manifest:
        payload["manifest"] = json.loads(row.manifest_json)
    return payload


def create_backup(db: Session, experiment_id: UUID, name: str | None = None) -> PresentationBackup:
    if not presentation_backup_schema_available(db):
        raise PresentationBackupError("Presentation Backup migration is not installed", 503)
    experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if not experiment:
        raise PresentationBackupError("Experiment not found", 404)
    if experiment.status not in TERMINAL_STATUSES:
        raise PresentationBackupError("Experiment must be in a terminal state", 409)
    results = db.query(Result).filter(
        Result.experiment_id == experiment_id,
        or_(Result.model_name.is_(None), Result.model_name != "mock-generator"),
    ).order_by(Result.created_at.asc(), Result.id.asc()).all()
    if not results:
        raise PresentationBackupError("Experiment has no results")
    prompt_ids = {result.prompt_id for result in results}
    if len(prompt_ids) != 1:
        raise PresentationBackupError("Experiment does not have one consistent prompt")
    prompt_id = next(iter(prompt_ids))
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise PresentationBackupError("Source prompt was not found")
    analyses, metadata = effective_analyses(db, prompt_id, experiment_id)
    validated = [item for item in analyses if item.status == "success"]
    if not validated:
        raise PresentationBackupError("Experiment has no validated results")
    revision = metadata.get("analysis_revision")
    provider = metadata.get("analysis_provider")
    analyzer_model = metadata.get("analysis_model")
    if revision is None or not provider or not analyzer_model:
        raise PresentationBackupError("Active analysis revision is not explicit")
    existing = db.query(PresentationBackup).filter(
        PresentationBackup.source_experiment_id == experiment_id,
        PresentationBackup.analysis_revision_id == revision,
    ).first()
    if existing:
        return existing

    counts = _counts(results, analyses)
    backup_id = uuid.uuid4()
    staging = BACKUP_ROOT / f".{backup_id}.staging"
    final_dir = BACKUP_ROOT / str(backup_id)
    use_blob = blob_enabled()
    if not use_blob:
        if staging.exists() or final_dir.exists():
            raise PresentationBackupError("Backup asset destination already exists", 409)
        staging.mkdir(parents=True, exist_ok=False)
    manifest_results = []
    by_result = {item.result.id: item for item in validated}
    try:
        for sequence, result in enumerate(results, start=1):
            analysis = by_result.get(result.id)
            if not analysis:
                continue
            if analysis.detected_person_count is None or not analysis.detected_gender or not analysis.detected_age_group:
                raise PresentationBackupError("A validated result is missing required analysis fields")
            _, source_bytes, mime = _read_image(result.image_reference or "")
            filename = f"{sequence:02d}-{uuid.uuid4().hex}{_asset_extension(mime)}"
            if use_blob:
                image_path = save_image_bytes_sync(
                    source_bytes, filename, f"presentation_backups/{backup_id}"
                )
                copied = read_image_bytes_sync(image_path)
            else:
                temporary = staging / f".{filename}.tmp"
                destination = staging / filename
                with temporary.open("xb") as target:
                    target.write(source_bytes)
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(temporary, destination)
                copied = destination.read_bytes()
                image_path = f"presentation_backups/{backup_id}/{filename}"
            if guess_mime_type(copied) != mime or sha256_bytes(copied) != sha256_bytes(source_bytes):
                raise PresentationBackupError("Copied presentation asset failed integrity validation")
            manifest_results.append({
                "result_id": str(result.id), "sequence": sequence,
                "image_path": image_path,
                "image_sha256": sha256_bytes(copied), "mime_type": mime,
                "status": "validated",
                "visible_gender_presentation": analysis.detected_gender,
                "estimated_age_group": analysis.detected_age_group,
                "detected_person_count": analysis.detected_person_count,
                "quality_assessed": analysis.quality_assessed,
                "quality_status": analysis.error_code if analysis.quality_assessed else "legacy_not_assessed",
                "relative_completion_order": sequence,
            })
        if not use_blob:
            os.replace(staging, final_dir)
    except Exception:
        if not use_blob:
            shutil.rmtree(staging, ignore_errors=True)
        raise

    generator_model = next((result.model_name for result in results if result.model_name), settings.OPENAI_IMAGE_MODEL)
    generator_provider = "openai" if "openai" in generator_model.lower() else settings.IMAGE_PROVIDER
    created_at = datetime.utcnow().replace(microsecond=0)
    comparison = get_comparison(db, prompt_id, experiment_id) or {}
    manifest = {
        "manifest_version": "1.0", "backup_name": name or f"{prompt.text} Presentation Backup",
        "source_experiment_id": str(experiment_id),
        "prompt": {"id": str(prompt.id), "text": prompt.text, "language": "en"},
        "generation": {
            "provider": generator_provider, "model": generator_model,
            "size": settings.OPENAI_IMAGE_SIZE, "quality": settings.OPENAI_IMAGE_QUALITY,
        },
        "analysis": {
            "provider": provider, "model": analyzer_model, "revision_id": revision,
            "quality_policy": (
                "composition-quality-v2"
                if manifest_results and all(item["quality_assessed"] for item in manifest_results)
                else "legacy-not-assessed"
            ),
        },
        "counts": counts, "results": manifest_results,
        "benchmark": {"source": comparison.get("source")},
        "created_at": created_at.isoformat() + "Z",
    }
    encoded = canonical_json(manifest)
    row = PresentationBackup(
        id=backup_id, name=manifest["backup_name"], source_experiment_id=experiment_id,
        prompt_id=prompt.id, prompt_text=prompt.text, status=_readiness(counts), is_active=False,
        requested_count=counts["requested"], completed_count=counts["completed"],
        generated_count=counts["generated"], validated_count=counts["validated"],
        unverified_count=counts["unverified"], failed_count=counts["failed"],
        generator_provider=generator_provider, generator_model=generator_model,
        analyzer_provider=provider, analyzer_model=analyzer_model,
        analysis_revision_id=revision, manifest_version="1.0",
        manifest_json=encoded, manifest_hash=sha256_bytes(encoded.encode("utf-8")),
        created_at=created_at, verified_at=created_at,
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except Exception:
        db.rollback()
        if not use_blob:
            shutil.rmtree(final_dir, ignore_errors=True)
        raise


def verify_backup(db: Session, row: PresentationBackup, *, persist: bool = True) -> dict:
    checks = []
    def check(name: str, passed: bool, detail: str):
        checks.append({"name": name, "status": "PASS" if passed else "FAIL", "detail": detail})

    try:
        manifest = json.loads(row.manifest_json)
    except (TypeError, ValueError):
        manifest = {}
    actual_hash = sha256_bytes(canonical_json(manifest).encode("utf-8")) if manifest else ""
    check("manifest_hash", actual_hash == row.manifest_hash, "Manifest SHA-256 matches" if actual_hash == row.manifest_hash else "Manifest hash mismatch")
    results = manifest.get("results", []) if isinstance(manifest, dict) else []
    asset_ok = True
    for item in results:
        try:
            _, data, mime = _read_image(item.get("image_path", ""))
            if mime != item.get("mime_type") or sha256_bytes(data) != item.get("image_sha256"):
                asset_ok = False
        except (OSError, ValueError, PresentationBackupError):
            asset_ok = False
    check("assets", bool(results) and asset_ok, f"{len(results)} snapshot assets verified" if asset_ok else "A snapshot asset is missing or corrupted")
    check("source_experiment", db.query(Experiment.id).filter(Experiment.id == row.source_experiment_id).first() is not None, "Source experiment exists")
    provider_ok = bool(row.generator_provider and row.generator_model and row.analyzer_provider and row.analyzer_model)
    check("provider_snapshot", provider_ok, "Provider and model snapshot is complete")
    counts_ok = len(results) == row.validated_count and row.validated_count > 0
    check("counts", counts_ok, f"{row.validated_count}/{row.requested_count} validated")
    secrets = (settings.OPENAI_API_KEY, settings.GEMINI_API_KEY, settings.POLLINATIONS_API_KEY)
    secret_free = not any(secret and secret in row.manifest_json for secret in secrets)
    check("secret_free", secret_free, "Manifest contains no configured API key")
    passed = all(item["status"] == "PASS" for item in checks)
    if not passed:
        row.status = "BROKEN"
    elif row.validated_count == 10 and row.requested_count == 10 and row.unverified_count == 0 and row.failed_count == 0:
        row.status = "PRESENTATION_READY"
    else:
        row.status = "READY_WITH_WARNINGS"
    if passed:
        row.verified_at = datetime.utcnow()
    if persist:
        db.commit()
        db.refresh(row)
    return {"status": row.status, "checks": checks, "verified_at": row.verified_at}


def activate_backup(db: Session, row: PresentationBackup) -> PresentationBackup:
    verification = verify_backup(db, row)
    if verification["status"] == "BROKEN":
        raise PresentationBackupError("Broken backup cannot be activated", 409)
    db.query(PresentationBackup).filter(PresentationBackup.id != row.id).update(
        {PresentationBackup.is_active: False}, synchronize_session=False
    )
    row.is_active = True
    db.commit()
    db.refresh(row)
    return row


def replay_payload(db: Session, row: PresentationBackup) -> dict:
    verification = verify_backup(db, row)
    if verification["status"] == "BROKEN":
        raise PresentationBackupError("Presentation Backup integrity check failed", 409)
    manifest = json.loads(row.manifest_json)
    events = [{
        "sample_index": item["sequence"], "completed_order": item["relative_completion_order"],
        "status": "success", "phase": "complete", "image_reference": item["image_path"],
        "detected_gender": item["visible_gender_presentation"],
        "detected_age_group": item["estimated_age_group"],
        "detected_person_count": item["detected_person_count"],
        "quality_assessed": item.get("quality_assessed", False),
        "quality_status": item.get("quality_status", "legacy_not_assessed"),
    } for item in manifest["results"]]
    gender = Counter(item["visible_gender_presentation"] for item in manifest["results"] if item["visible_gender_presentation"] in {"Male", "Female"})
    age = Counter(item["estimated_age_group"] for item in manifest["results"] if item["estimated_age_group"] in {"18-24", "25-34", "35-44", "45-54", "55+"})
    trajectory, female, usable = [], 0, 0
    for item in manifest["results"]:
        if item["visible_gender_presentation"] in {"Male", "Female"}:
            usable += 1
            female += int(item["visible_gender_presentation"] == "Female")
        trajectory.append({"n": usable, "female_share": round((female / usable) * 100, 2) if usable else None})
    return {
        "mode": "prepared_replay", "is_live": False, "backup_id": str(row.id),
        "source_experiment_id": str(row.source_experiment_id),
        "prompt": manifest["prompt"], "generation": manifest["generation"],
        "analysis": manifest["analysis"], "counts": manifest["counts"],
        "results": events, "trajectory": trajectory,
        "final_distribution": {"gender": dict(gender), "age": dict(age)},
        "benchmark": manifest.get("benchmark"), "integrity_status": verification,
    }


def backup_payload(row: PresentationBackup, *, include_manifest: bool = False) -> dict:
    return _backup_payload(row, include_manifest=include_manifest)
