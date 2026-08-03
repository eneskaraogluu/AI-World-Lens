from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_
from uuid import UUID

from backend.core.database import get_db
from backend.schemas.comparison import ComparisonResponse
from backend.services.comparison_service import get_comparison
from backend.models.models import Result
from typing import List

router = APIRouter()

@router.get("/prompts/{prompt_id}", response_model=ComparisonResponse)
def read_comparison(prompt_id: UUID, experiment_id: UUID | None = None, db: Session = Depends(get_db)):
    comp = get_comparison(db, prompt_id, experiment_id)
    if comp is None:
        raise HTTPException(status_code=404, detail="Prompt or comparison data not found")
    return comp


@router.get("/experiments/{experiment_id}")
def read_experiment_comparison(experiment_id: UUID, db: Session = Depends(get_db)):
    result = db.query(Result).filter(
        Result.experiment_id == experiment_id
    ).order_by(Result.created_at.asc()).first()
    if not result:
        raise HTTPException(status_code=404, detail="Experiment has no results")
    comp = get_comparison(db, result.prompt_id, experiment_id)
    if comp is None:
        raise HTTPException(status_code=404, detail="Experiment comparison data not found")
    return comp

@router.get("/prompts/{prompt_id}/images", response_model=List[str])
def get_prompt_images(prompt_id: UUID, experiment_id: UUID | None = None, db: Session = Depends(get_db)):
    # Return all image references (both local .jpg files and http URLs)
    if experiment_id is None:
        latest = db.query(Result.experiment_id).filter(
            Result.prompt_id == prompt_id,
            or_(Result.model_name.is_(None), Result.model_name != "mock-generator"),
        ).order_by(Result.created_at.desc()).first()
        experiment_id = latest[0] if latest else None

    filters = [
        Result.prompt_id == prompt_id,
        Result.analysis_status == 'success',
        or_(Result.model_name.is_(None), Result.model_name != "mock-generator"),
        Result.image_reference != None,
        Result.image_reference != "mock_no_image_saved",
        Result.image_reference != "error"
    ]
    if experiment_id:
        filters.append(Result.experiment_id == experiment_id)
    results = db.query(Result.image_reference).filter(*filters).order_by(Result.created_at.desc()).limit(24).all()
    
    return [r[0] for r in results if r[0]]
