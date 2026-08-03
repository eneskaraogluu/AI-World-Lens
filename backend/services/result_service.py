from sqlalchemy.orm import Session
from backend.models.models import Result
from uuid import UUID
from typing import Dict, Any

def save_result(db: Session, exp_id: UUID, prompt_id: UUID, analysis_data: Dict[str, Any]):
    db_result = Result(
        experiment_id=exp_id,
        prompt_id=prompt_id,
        generation_id=analysis_data.get("generation_id"),
        image_reference=analysis_data.get("image_reference"),
        detected_age_group=analysis_data.get("detected_age_group"),
        detected_gender=analysis_data.get("detected_gender"),
        detected_person_count=analysis_data.get("detected_person_count"),
        detected_location=analysis_data.get("detected_location"),
        detected_socioeconomic_status=analysis_data.get("detected_socioeconomic_status"),
        coder1_data=analysis_data.get("coder1_data"),
        coder2_data=analysis_data.get("coder2_data"),
        coder_agreement_score=analysis_data.get("coder_agreement_score"),
        analysis_status=analysis_data.get("analysis_status", "pending"),
        model_name=analysis_data.get("model_name"),
        model_version=analysis_data.get("model_version"),
        seed=analysis_data.get("seed"),
        generation_duration=analysis_data.get("generation_duration"),
        analysis_duration=analysis_data.get("analysis_duration"),
        error_message=analysis_data.get("error_message")
    )
    db.add(db_result)
    db.commit()
    db.refresh(db_result)
    return db_result
