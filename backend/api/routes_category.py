from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from backend.core.database import get_db
from backend.schemas.category import CategoryResponse
from backend.services.category_service import get_all_categories

router = APIRouter()

@router.get("/", response_model=List[CategoryResponse])
def read_categories(db: Session = Depends(get_db)):
    categories = get_all_categories(db)
    return categories
