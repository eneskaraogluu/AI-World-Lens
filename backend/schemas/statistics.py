from pydantic import BaseModel
from typing import Dict
from uuid import UUID

class DistributionStats(BaseModel):
    category: str
    count: int

class PromptStatsResponse(BaseModel):
    prompt_id: UUID
    prompt_text: str
    total_generations: int
    gender_distribution: Dict[str, int]
    age_group_distribution: Dict[str, int]
