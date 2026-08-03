from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from sqlalchemy import func, inspect, or_
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.models.models import Result, ResultAnalysis
from backend.services.vision_base import (
    QUALITY_POLICY_VERSION,
    VisionAnalysisOutcome,
    demographic_quality_decision,
)


@dataclass(frozen=True)
class EffectiveAnalysis:
    result: Result
    status: str
    detected_age_group: str | None
    detected_gender: str | None
    detected_person_count: int
    provider: str
    model_name: str
    revision: int
    error_code: str | None = None
    safe_error_message: str | None = None
    quality_assessed: bool = False


def analysis_history_available(db: Session) -> bool:
    return inspect(db.get_bind()).has_table(ResultAnalysis.__tablename__)


def is_generated_result(result: Result) -> bool:
    reference = (result.image_reference or "").strip()
    return bool(reference and reference not in {"error", "mock_no_image_saved"})


def is_local_generated_result(result: Result) -> bool:
    if not is_generated_result(result):
        return False
    reference = (result.image_reference or "").lower()
    return not reference.startswith(("http://", "https://")) and reference.endswith(
        (".png", ".jpg", ".jpeg", ".webp")
    )


def next_revision(db: Session, experiment_id: UUID) -> int:
    if not analysis_history_available(db):
        return 2
    maximum = db.query(func.max(ResultAnalysis.revision)).join(Result).filter(
        Result.experiment_id == experiment_id
    ).scalar()
    return int(maximum or 1) + 1


def save_analysis_revision(
    db: Session,
    result_id: UUID,
    provider: str,
    model_name: str,
    revision: int,
    outcome: VisionAnalysisOutcome,
    *,
    is_active: bool,
    fallback_reason: str | None = None,
    enforce_quality: bool = True,
) -> ResultAnalysis | None:
    if not analysis_history_available(db):
        return None
    quality_ok, quality_code, quality_message = demographic_quality_decision(outcome.data)
    accepted = outcome.succeeded and (quality_ok or not enforce_quality)
    row = ResultAnalysis(
        result_id=result_id,
        provider=provider,
        model_name=model_name,
        revision=revision,
        status="success" if accepted else "unverified",
        detected_age_group=outcome.data.get("detected_age_group", "Unclear"),
        detected_gender=outcome.data.get("detected_gender", "Unclear"),
        detected_person_count=outcome.data.get("detected_person_count", 0),
        analysis_duration=outcome.duration_ms,
        error_code=outcome.error.error_code if outcome.error else quality_code if enforce_quality else None,
        safe_error_message=outcome.error.safe_message if outcome.error else quality_message if enforce_quality else None,
        fallback_reason=fallback_reason,
        is_active=is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def activate_revision(
    db: Session,
    experiment_id: UUID,
    provider: str,
    revision: int,
) -> None:
    """Atomically switch every generated result to one staged provider revision."""
    result_ids = [row[0] for row in db.query(Result.id).filter(
        Result.experiment_id == experiment_id
    ).all()]
    if not result_ids:
        return
    staged = db.query(ResultAnalysis).filter(
        ResultAnalysis.result_id.in_(result_ids),
        ResultAnalysis.provider == provider,
        ResultAnalysis.revision == revision,
    ).all()
    staged_ids = {row.result_id for row in staged}
    generated_ids = {
        row.id for row in db.query(Result).filter(Result.id.in_(result_ids)).all()
        if is_generated_result(row) and row.model_name != "mock-generator"
    }
    if staged_ids != generated_ids:
        raise RuntimeError("The staged revision does not cover every generated result")

    db.query(ResultAnalysis).filter(
        ResultAnalysis.result_id.in_(result_ids)
    ).update({ResultAnalysis.is_active: False}, synchronize_session=False)
    for analysis in staged:
        analysis.is_active = True
        result = analysis.result
        result.detected_age_group = analysis.detected_age_group
        result.detected_gender = analysis.detected_gender
        result.detected_person_count = analysis.detected_person_count
        result.analysis_duration = analysis.analysis_duration
        result.analysis_status = analysis.status
        result.error_message = analysis.safe_error_message
    db.commit()


def _active_revision_rows(
    db: Session, experiment_id: UUID
) -> tuple[list[ResultAnalysis], str | None, str | None, int | None]:
    if not analysis_history_available(db):
        return [], None, None, None
    candidates = db.query(ResultAnalysis).join(Result).filter(
        Result.experiment_id == experiment_id,
        ResultAnalysis.is_active == True,  # noqa: E712 - MSSQL compiles this as "= 1"
    ).order_by(ResultAnalysis.revision.desc(), ResultAnalysis.created_at.desc()).all()
    if not candidates:
        return [], None, None, None
    head = candidates[0]
    rows = [
        row for row in candidates
        if row.provider == head.provider and row.revision == head.revision
    ]
    return rows, head.provider, head.model_name, head.revision


def effective_analyses(
    db: Session, prompt_id: UUID, experiment_id: UUID
) -> tuple[list[EffectiveAnalysis], dict]:
    results = db.query(Result).filter(
        Result.prompt_id == prompt_id,
        Result.experiment_id == experiment_id,
        or_(Result.model_name.is_(None), Result.model_name != "mock-generator"),
    ).order_by(Result.created_at.asc()).all()
    active_rows, provider, model_name, revision = _active_revision_rows(db, experiment_id)
    if active_rows:
        by_result = {row.result_id: row for row in active_rows}
        effective = []
        for result in results:
            analysis = by_result.get(result.id)
            if not analysis:
                continue
            effective.append(EffectiveAnalysis(
                result=result,
                status=analysis.status,
                detected_age_group=analysis.detected_age_group,
                detected_gender=analysis.detected_gender,
                detected_person_count=analysis.detected_person_count or 0,
                provider=analysis.provider,
                model_name=analysis.model_name,
                revision=analysis.revision,
                error_code=analysis.error_code,
                safe_error_message=analysis.safe_error_message,
                quality_assessed=bool(
                    analysis.error_code == f"{QUALITY_POLICY_VERSION}_pass"
                    or (analysis.error_code or "").startswith((
                        "face_", "head_", "multiple_", "no_visible_",
                        "incomplete_", "not_demographic_", "quality_",
                    ))
                ),
            ))
        metadata = {
            "analysis_provider": provider,
            "analysis_model": model_name,
            "analysis_revision": revision,
            "fallback_reason": next((row.fallback_reason for row in active_rows if row.fallback_reason), None),
        }
        return effective, metadata

    # Legacy compatibility: old successful Result rows predate analysis revisions.
    effective = [EffectiveAnalysis(
        result=result,
        status="success" if result.analysis_status == "success" else "unverified",
        detected_age_group=result.detected_age_group,
        detected_gender=result.detected_gender,
        detected_person_count=result.detected_person_count or 0,
        provider="gemini",
        model_name=settings.GEMINI_MODEL,
        revision=1,
        safe_error_message=(
            "The saved analysis was not completed."
            if result.analysis_status != "success" and is_generated_result(result)
            else None
        ),
        quality_assessed=False,
    ) for result in results if is_generated_result(result)]
    return effective, {
        "analysis_provider": "gemini" if effective else None,
        "analysis_model": settings.GEMINI_MODEL if effective else None,
        "analysis_revision": 1 if effective else None,
        "fallback_reason": None,
    }


def experiment_provider_metadata(db: Session, experiment_id: UUID) -> dict:
    rows, provider, model_name, revision = _active_revision_rows(db, experiment_id)
    if rows:
        fallback_reason = next((row.fallback_reason for row in rows if row.fallback_reason), None)
        return {
            "analysis_provider": provider,
            "analysis_model": model_name,
            "analysis_revision": revision,
            "fallback_reason": fallback_reason,
        }
    has_results = db.query(Result.id).filter(Result.experiment_id == experiment_id).first()
    return {
        "analysis_provider": "gemini" if has_results else None,
        "analysis_model": settings.GEMINI_MODEL if has_results else None,
        "analysis_revision": 1 if has_results else None,
        "fallback_reason": None,
    }
