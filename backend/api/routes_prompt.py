from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from backend.core.database import get_db
from backend.schemas.prompt import PromptResponse
from backend.services.prompt_service import get_all_prompts

router = APIRouter()

@router.get("", response_model=List[PromptResponse])
def read_prompts(category_id: Optional[UUID] = None, db: Session = Depends(get_db)):
    prompts = get_all_prompts(db, category_id=category_id)
    return prompts
