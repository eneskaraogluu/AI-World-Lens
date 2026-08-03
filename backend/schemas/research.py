from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StudyCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=120)
    description: str | None = None
    theoretical_framework: str = "Cultivation-inspired representational audit"
    research_question: str = Field(min_length=10)
    protocol_version: str = "1.0"


class StudyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    slug: str
    description: str | None
    theoretical_framework: str
    research_question: str
    protocol_version: str
    status: str
    created_at: datetime
    updated_at: datetime


class WaveCreate(BaseModel):
    label: str = Field(min_length=2, max_length=80)
    description: str | None = None
    prompt_set_version: str = "1.0"
    codebook_version: str = "1.0"
    benchmark_version: str = "unconfigured"


class WaveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    study_id: UUID
    label: str
    description: str | None
    status: str
    generator_provider: str
    generator_model: str
    generator_size: str
    generator_quality: str
    analyzer_provider: str
    analyzer_model: str
    prompt_set_version: str
    prompt_set_hash: str | None
    standardizer_version: str
    codebook_version: str
    benchmark_version: str
    manifest: dict[str, Any] | None = None
    started_at: datetime | None
    completed_at: datetime | None
    locked_at: datetime | None
    created_at: datetime


class StudyDetail(StudyResponse):
    waves: list[WaveResponse] = []


class PromptDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    slug: str
    category: str
    concept_key: str
    language: str
    prompt_text: str
    prompt_version: str
    scene_policy: str
    expected_person_policy: str
    applicable_dimensions: list[str] = []
    active: bool


class CampaignCreate(BaseModel):
    wave_id: UUID
    name: str = Field(min_length=3, max_length=255)
    target_per_prompt: int = Field(ge=1, le=1000)
    prompt_definition_ids: list[UUID] = Field(min_length=1, max_length=200)
    prompt_variant_ids: list[UUID] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def unique_selections(self):
        if len(set(self.prompt_definition_ids)) != len(self.prompt_definition_ids):
            raise ValueError("prompt_definition_ids cannot contain duplicates")
        if len(set(self.prompt_variant_ids)) != len(self.prompt_variant_ids):
            raise ValueError("prompt_variant_ids cannot contain duplicates")
        return self


class CampaignPromptResponse(BaseModel):
    id: UUID
    prompt_definition_id: UUID
    prompt_variant_id: UUID | None
    prompt_slug: str
    language: str
    source_prompt: str
    standardized_prompt: str
    scene_policy: str
    expected_person_policy: str
    target_count: int
    queued_count: int
    completed_count: int
    validated_count: int
    status: str


class CampaignResponse(BaseModel):
    id: UUID
    wave_id: UUID
    name: str
    status: str
    target_per_prompt: int
    requested_total: int
    completed_total: int
    generated_total: int
    validated_total: int
    unverified_total: int
    failed_total: int
    prompt_set_hash: str
    manifest: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    prompts: list[CampaignPromptResponse]


class CanonicalCounts(BaseModel):
    requested: int = 0
    queued: int = 0
    processing: int = 0
    completed: int = 0
    generated: int = 0
    machine_validated: int = 0
    human_annotated: int = 0
    human_adjudicated: int = 0
    unverified: int = 0
    failed: int = 0
    excluded: int = 0
    gender_usable: int = 0
    age_usable: int = 0
    scene_usable: int = 0


class CampaignStatusResponse(BaseModel):
    campaign_id: UUID
    status: str
    counts: CanonicalCounts
    queue_depth: int
    cost_warning: str
    safe_message: str | None = None


class DryRunResponse(BaseModel):
    campaign_id: UUID
    would_create_tasks: int
    already_materialized: int
    missing_tasks: int
    prompt_count: int
    provider: dict[str, str]
    prompt_set_hash: str
    duplicate_tasks: int
    real_api_calls_made: Literal[False] = False
    cost_warning: str


class BenchmarkCreate(BaseModel):
    study_wave_id: UUID
    name: str = Field(min_length=3, max_length=255)
    version: str = Field(min_length=1, max_length=40)
    dimension: str = Field(min_length=2, max_length=80)
    scope_type: Literal["national_population", "occupation", "household", "setting", "other"]
    scope_key: str = Field(min_length=1, max_length=140)
    reference_year: str | None = Field(default=None, max_length=20)
    geographic_scope: str | None = Field(default=None, max_length=255)
    source_organization: str = Field(min_length=2, max_length=255)
    source_title: str = Field(min_length=3, max_length=500)
    source_url: str | None = Field(default=None, max_length=1000)
    denominator_description: str = Field(min_length=3, max_length=1000)
    category_mapping: dict[str, str] = Field(default_factory=dict)
    distribution: dict[str, float]
    verification_status: Literal["configured", "verified", "unverified_legacy"] = "configured"
    retrieved_at: datetime | None = None
    prompt_definition_ids: list[UUID] = Field(min_length=1, max_length=200)


class BenchmarkResponse(BaseModel):
    id: UUID
    study_wave_id: UUID
    name: str
    version: str
    dimension: str
    scope_type: str
    scope_key: str
    reference_year: str | None
    geographic_scope: str | None
    source_organization: str
    source_title: str
    source_url: str | None
    denominator_description: str
    category_mapping: dict[str, str]
    distribution: dict[str, float]
    verification_status: str
    retrieved_at: datetime | None
    created_at: datetime
    locked_at: datetime | None
    prompt_definition_ids: list[UUID]


class TrajectoryPoint(BaseModel):
    n: int
    completed_at: datetime
    shares: dict[str, float]
    unclear_count: int
    denominator: int


class TrajectoryResponse(BaseModel):
    campaign_prompt_id: UUID
    prompt: str
    dimension: str
    provider: str | None
    model: str | None
    revision: int | None
    denominator_rule: str
    reference: dict[str, Any] | None
    points: list[TrajectoryPoint]


class ExperimentTrajectoryResponse(BaseModel):
    experiment_id: UUID
    prompt_id: UUID | None
    prompt: str | None
    dimension: str
    provider: str | None
    model: str | None
    revision: int | None
    denominator_rule: str
    reference: dict[str, Any] | None
    points: list[TrajectoryPoint]


class AtlasCell(BaseModel):
    dimension: str
    label: str
    status: Literal["value", "no_reference", "insufficient_sample", "not_applicable"]
    value: float | None = None
    unit: str | None = None
    generated_share: float | None = None
    reference_share: float | None = None
    n: int
    denominator: int
    source: str | None = None


class AtlasRow(BaseModel):
    campaign_prompt_id: UUID
    prompt_definition_id: UUID
    prompt: str
    language: str
    category: str
    cells: list[AtlasCell]


class AtlasResponse(BaseModel):
    wave_id: UUID
    analysis_source: str
    minimum_n: int
    rows: list[AtlasRow]
    legend: dict[str, str]


class AnalysisSourceResponse(BaseModel):
    provider: str
    model: str
    revision: int
    source_type: str
    active_result_count: int


class EvidenceItem(BaseModel):
    result_id: UUID
    image_reference: str | None
    prompt: str
    standardized_prompt: str
    generation_provider: str
    generation_model: str
    generated_at: datetime
    machine_analysis: dict[str, Any] | None
    analyzer_provider: str | None
    analyzer_model: str | None
    analyzer_revision: int | None
    source_type: str | None
    quality_flags: list[str]
    included_in_metric: bool
    inclusion_reason: str


class EvidenceResponse(BaseModel):
    wave_id: UUID
    campaign_prompt_id: UUID
    dimension: str
    category_value: str | None
    items: list[EvidenceItem]
