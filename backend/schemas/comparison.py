from pydantic import BaseModel
from typing import Dict, Optional
from uuid import UUID

class DistributionComparison(BaseModel):
    real_world_percentage: float
    ai_percentage: float
    difference: float

class ComparisonResponse(BaseModel):
    experiment_id: Optional[UUID] = None
    prompt_id: UUID
    prompt_text: str
    experiment_status: Optional[str] = None
    analysis_provider: Optional[str] = None
    analysis_model: Optional[str] = None
    analysis_revision: Optional[int] = None
    fallback_reason: Optional[str] = None
    requested_samples: int = 0
    generated_samples: int = 0
    validated_samples: int = 0
    unverified_samples: int = 0
    failed_samples: int = 0
    total_generations: int
    valid_person_analyses: int = 0
    valid_gender_analyses: int = 0
    valid_age_analyses: int = 0
    failed_generations: int = 0
    source: str
    avg_agreement_score: float = 0
    gender_comparison: Dict[str, DistributionComparison]
    age_group_comparison: Dict[str, DistributionComparison]
