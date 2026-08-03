from pydantic import BaseModel, Field
from uuid import UUID

class RunExperimentRequest(BaseModel):
    prompt_id: UUID
    iterations: int = Field(default=10, ge=1, le=10)


class ReanalyzeExperimentRequest(BaseModel):
    provider: str
