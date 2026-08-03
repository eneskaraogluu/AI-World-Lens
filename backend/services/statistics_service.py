from collections import Counter
from typing import Any, Dict
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.models.models import Prompt, Result
from backend.services.analysis_revision_service import effective_analyses, is_generated_result


GENDERS = {"Male", "Female"}
AGE_GROUPS = {"18-24", "25-34", "35-44", "45-54", "55+"}


def get_prompt_statistics(
    db: Session, prompt_id: UUID, experiment_id: UUID | None = None
) -> Dict[str, Any] | None:
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        return None
    if experiment_id is None:
        latest = db.query(Result.experiment_id).filter(
            Result.prompt_id == prompt_id,
            or_(Result.model_name.is_(None), Result.model_name != "mock-generator"),
        ).order_by(Result.created_at.desc()).first()
        experiment_id = latest[0] if latest else None

    if experiment_id is None:
        analyses, metadata, results = [], {}, []
    else:
        analyses, metadata = effective_analyses(db, prompt_id, experiment_id)
        results = db.query(Result).filter(
            Result.prompt_id == prompt_id,
            Result.experiment_id == experiment_id,
            or_(Result.model_name.is_(None), Result.model_name != "mock-generator"),
        ).all()

    generated_count = sum(1 for result in results if is_generated_result(result))
    generation_failed = len(results) - generated_count
    successful = [analysis for analysis in analyses if analysis.status == "success"]
    unverified = [analysis for analysis in analyses if analysis.status != "success"]
    gender_counts = Counter(
        analysis.detected_gender for analysis in successful
        if analysis.detected_person_count > 0 and analysis.detected_gender in GENDERS
    )
    age_counts = Counter(
        analysis.detected_age_group for analysis in successful
        if analysis.detected_person_count > 0 and analysis.detected_age_group in AGE_GROUPS
    )
    valid_people = sum(
        1 for analysis in successful if analysis.detected_person_count > 0
    )
    return {
        "prompt_id": prompt.id,
        "prompt_text": prompt.text,
        "experiment_id": experiment_id,
        "requested_samples": len(results),
        "generated_samples": generated_count,
        "validated_samples": len(successful),
        "unverified_samples": len(unverified),
        "failed_samples": generation_failed,
        "total_generations": len(successful),
        "valid_person_analyses": valid_people,
        "valid_gender_analyses": sum(gender_counts.values()),
        "valid_age_analyses": sum(age_counts.values()),
        "failed_generations": len(unverified) + generation_failed,
        "gender_distribution": dict(gender_counts),
        "age_group_distribution": dict(age_counts),
        "location_distribution": {},
        "socioeconomic_distribution": {},
        "avg_agreement_score": 0.0,
        **metadata,
    }
