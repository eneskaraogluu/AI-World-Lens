from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class ExperimentCreate(BaseModel):
    name: str
    model_name: str

class ExperimentResponse(BaseModel):
    id: UUID
    name: str
    model_name: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
