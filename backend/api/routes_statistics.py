from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from backend.core.database import get_db
from backend.schemas.statistics import PromptStatsResponse
from backend.services.statistics_service import get_prompt_statistics

router = APIRouter()

@router.get("/prompts/{prompt_id}", response_model=PromptStatsResponse)
def read_prompt_statistics(prompt_id: UUID, db: Session = Depends(get_db)):
    stats = get_prompt_statistics(db, prompt_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return stats
