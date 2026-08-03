from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from backend.schemas.category import CategoryResponse

class PromptBase(BaseModel):
    text: str
    category_id: UUID

class PromptResponse(PromptBase):
    id: UUID
    created_at: datetime
    # Return nested category info
    category: CategoryResponse

    class Config:
        from_attributes = True
