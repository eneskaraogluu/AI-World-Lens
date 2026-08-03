from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class CategoryBase(BaseModel):
    name: str

class CategoryResponse(CategoryBase):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True
