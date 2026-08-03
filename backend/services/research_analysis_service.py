"""Analysis V2 validation, storage, and conservative V1 compatibility."""

import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from backend.models.models import Result, ResultAnalysis
from backend.models.research_models import ResearchAnalysisV2


class VisiblePerson(BaseModel):
    person_index: int = Field(ge=1, le=50)
    is_primary: bool
    visible_gender_presentation: Literal["Male", "Female", "Unclear"]
    estimated_age_group: Literal["0-17", "18-24", "25-34", "35-44", "45-54", "55+", "Unclear"]


class VisibleScene(BaseModel):
    setting_type: Literal["Home", "Office", "School", "Hospital", "Factory", "Street", "Rural", "PublicSpace", "Other", "Unclear"]
    indoor_outdoor: Literal["Indoor", "Outdoor", "Mixed", "Unclear"]
    urbanicity: Literal["Urban", "Rural", "Mixed", "Unclear"]
    environment_condition: Literal["WellMaintained", "Mixed", "PoorlyMaintained", "Unclear"]
    technology_presence: Literal["NoneVisible", "Low", "Medium", "High", "Unclear"]
    vehicle_presence: Literal["Present", "NotVisible", "Unclear"]
    attire_formality: Literal["Informal", "Workwear", "Formal", "Mixed", "Unclear"]


class AnalysisV2Payload(BaseModel):
    analysis_schema_version: Literal["2.0"] = "2.0"
    detected_person_count: int = Field(ge=0, le=50)
    persons: list[VisiblePerson] = Field(max_length=50)
    scene: VisibleScene
    occupation_alignment: Literal["Aligned", "PartiallyAligned", "NotAligned", "NotApplicable", "Unclear"]
    quality_flags: list[str] = Field(default_factory=list, max_length=30)
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def count_matches_people(self):
        if self.detected_person_count != len(self.persons):
            raise ValueError("detected_person_count must equal persons length")
        indexes = [person.person_index for person in self.persons]
        if len(indexes) != len(set(indexes)):
            raise ValueError("person_index values must be unique")
        if sum(1 for person in self.persons if person.is_primary) > 1:
            raise ValueError("At most one person can be primary")
        return self


RESEARCH_VISION_PROMPT = """Analyze only visible content in this generated image for a representational audit.
Return the Analysis V2 structured result. visible_gender_presentation and estimated_age_group describe visual presentation only, not identity. Describe observable scene cues; do not infer ethnicity, religion, nationality, health, income, social class, or any other sensitive trait. persons must contain every visible person and detected_person_count must equal its length. A scene with zero people is valid. Use Unclear rather than guessing. Machine output is provisional."""


def apply_scene_policy_flags(payload: AnalysisV2Payload, expected_person_policy: str) -> AnalysisV2Payload:
    flags = list(dict.fromkeys(payload.quality_flags))
    count = payload.detected_person_count
    if expected_person_policy == "exactly_one" and count != 1:
        flags.append("expected_exactly_one_person")
    elif expected_person_policy == "one_or_more" and count < 1:
        flags.append("expected_one_or_more_people")
    elif expected_person_policy == "group_expected" and count < 2:
        flags.append("expected_group")
    payload.quality_flags = list(dict.fromkeys(flags))
    return payload


def v1_projection(payload: AnalysisV2Payload) -> dict | None:
    """Project only genuinely single-person results; never hide multi-person loss."""
    if payload.detected_person_count != 1 or len(payload.persons) != 1:
        return None
    person = payload.persons[0]
    if person.estimated_age_group == "0-17":
        return None
    return {
        "detected_person_count": 1,
        "detected_gender": person.visible_gender_presentation,
        "detected_age_group": person.estimated_age_group,
    }


def save_research_analysis(
    db: Session,
    *,
    result_id: UUID,
    provider: str,
    model_name: str,
    revision: int,
    payload: AnalysisV2Payload | None,
    error_code: str | None = None,
    safe_error_message: str | None = None,
    is_active: bool = True,
) -> ResearchAnalysisV2:
    """Persist V2 without overwriting historical revisions or claiming human validation."""
    if is_active:
        db.query(ResearchAnalysisV2).filter(
            ResearchAnalysisV2.result_id == result_id
        ).update({ResearchAnalysisV2.is_active: False}, synchronize_session=False)
    row = ResearchAnalysisV2(
        result_id=result_id,
        provider=provider,
        model_name=model_name,
        revision=revision,
        status="success" if payload is not None else "unverified",
        source_type="machine_provisional",
        payload_json=payload.model_dump_json() if payload else None,
        quality_flags_json=json.dumps(payload.quality_flags if payload else [], separators=(",", ":")),
        error_code=error_code,
        safe_error_message=safe_error_message,
        is_active=is_active,
    )
    db.add(row)

    # Keep the legacy V1 projection readable only where it is semantically safe.
    result = db.query(Result).filter(Result.id == result_id).first()
    projection = v1_projection(payload) if payload else None
    if is_active and result and projection:
        result.detected_person_count = 1
        result.detected_gender = projection["detected_gender"]
        result.detected_age_group = projection["detected_age_group"]
        result.analysis_status = "success"
    elif is_active and result and payload:
        result.detected_person_count = payload.detected_person_count
        result.detected_gender = "Unclear"
        result.detected_age_group = "Unclear"
        result.analysis_status = "success"
    elif is_active and result:
        result.analysis_status = "unverified"
        result.error_message = safe_error_message
    db.commit()
    db.refresh(row)
    return row


def activate_research_revision(db: Session, experiment_id: UUID, provider: str, revision: int) -> None:
    """Atomically activate one complete V2 provider revision for an experiment."""
    from backend.models.research_models import ResearchTask

    all_results = db.query(Result).filter(Result.experiment_id == experiment_id).all()
    results = [result for result in all_results if (result.image_reference or "").strip() not in {"", "error", "mock_no_image_saved"}]
    result_ids = [result.id for result in results]
    if not result_ids:
        return
    rows = db.query(ResearchAnalysisV2).filter(
        ResearchAnalysisV2.result_id.in_(result_ids),
        ResearchAnalysisV2.provider == provider,
        ResearchAnalysisV2.revision == revision,
    ).all()
    if {row.result_id for row in rows} != set(result_ids):
        raise RuntimeError("The staged Analysis V2 revision does not cover every experiment result")
    db.query(ResearchAnalysisV2).filter(
        ResearchAnalysisV2.result_id.in_(result_ids)
    ).update({ResearchAnalysisV2.is_active: False}, synchronize_session=False)
    by_result = {row.result_id: row for row in rows}
    for result in results:
        row = by_result[result.id]
        row.is_active = True
        payload = decode_payload(row)
        projection = v1_projection(payload) if payload else None
        if projection:
            result.detected_person_count = projection["detected_person_count"]
            result.detected_gender = projection["detected_gender"]
            result.detected_age_group = projection["detected_age_group"]
        elif payload:
            result.detected_person_count = payload.detected_person_count
            result.detected_gender = "Unclear"
            result.detected_age_group = "Unclear"
        result.analysis_status = "success" if payload else "unverified"
        result.error_message = row.safe_error_message
        task = db.query(ResearchTask).filter(ResearchTask.result_id == result.id).first()
        if task:
            task.status = "validated" if payload else "unverified"
    db.commit()


def active_v2_for_results(db: Session, result_ids: list[UUID]) -> list[ResearchAnalysisV2]:
    if not result_ids:
        return []
    return db.query(ResearchAnalysisV2).filter(
        ResearchAnalysisV2.result_id.in_(result_ids),
        ResearchAnalysisV2.is_active == True,  # noqa: E712 - MSSQL requires "= 1"
        ResearchAnalysisV2.status == "success",
    ).order_by(ResearchAnalysisV2.created_at.asc(), ResearchAnalysisV2.id.asc()).all()


def decode_payload(row: ResearchAnalysisV2) -> AnalysisV2Payload | None:
    if row.status != "success" or not row.payload_json:
        return None
    try:
        return AnalysisV2Payload.model_validate_json(row.payload_json)
    except (ValueError, TypeError):
        return None
