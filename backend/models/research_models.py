"""Additive ORM models for the Ortalama Dunya research programme.

These tables deliberately link *to* legacy experiments/results instead of
adding required columns to the existing tables.  An installation can therefore
keep serving the Live Demo before the research migration is applied.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import relationship

from backend.models.base import Base


class Study(Base):
    __tablename__ = "research_studies"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    slug = Column(String(120), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    theoretical_framework = Column(String(255), nullable=False)
    research_question = Column(Text, nullable=False)
    protocol_version = Column(String(40), nullable=False, default="1.0")
    status = Column(String(40), nullable=False, default="draft")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    waves = relationship("StudyWave", back_populates="study", cascade="all, delete-orphan")


class StudyWave(Base):
    __tablename__ = "research_study_waves"
    __table_args__ = (UniqueConstraint("study_id", "label", name="uq_research_wave_label"),)

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    study_id = Column(Uuid(as_uuid=True), ForeignKey("research_studies.id"), nullable=False, index=True)
    label = Column(String(80), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(40), nullable=False, default="draft")
    generator_provider = Column(String(80), nullable=False)
    generator_model = Column(String(120), nullable=False)
    generator_size = Column(String(40), nullable=False)
    generator_quality = Column(String(40), nullable=False)
    analyzer_provider = Column(String(80), nullable=False)
    analyzer_model = Column(String(120), nullable=False)
    prompt_set_version = Column(String(40), nullable=False, default="1.0")
    prompt_set_hash = Column(String(64), nullable=True)
    standardizer_version = Column(String(40), nullable=False, default="1.0")
    codebook_version = Column(String(40), nullable=False, default="1.0")
    benchmark_version = Column(String(40), nullable=False, default="unconfigured")
    manifest_json = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    locked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    study = relationship("Study", back_populates="waves")
    campaigns = relationship("Campaign", back_populates="wave", cascade="all, delete-orphan")


class PromptDefinition(Base):
    __tablename__ = "research_prompt_definitions"
    __table_args__ = (
        UniqueConstraint("slug", "language", "prompt_version", name="uq_research_prompt_definition"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(String(140), nullable=False, index=True)
    category = Column(String(80), nullable=False, index=True)
    concept_key = Column(String(140), nullable=False, index=True)
    language = Column(String(12), nullable=False, index=True)
    prompt_text = Column(String(1000), nullable=False)
    prompt_version = Column(String(40), nullable=False, default="1.0")
    scene_policy = Column(String(40), nullable=False)
    expected_person_policy = Column(String(40), nullable=False)
    applicable_dimensions_json = Column(Text, nullable=False, default="[]")
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    variants = relationship("PromptVariant", back_populates="definition", cascade="all, delete-orphan")


class PromptVariant(Base):
    __tablename__ = "research_prompt_variants"
    __table_args__ = (
        UniqueConstraint(
            "prompt_definition_id", "variant_label", "language", "version",
            name="uq_research_prompt_variant",
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_definition_id = Column(
        Uuid(as_uuid=True), ForeignKey("research_prompt_definitions.id"), nullable=False, index=True
    )
    variant_label = Column(String(80), nullable=False)
    prompt_text = Column(String(1000), nullable=False)
    language = Column(String(12), nullable=False)
    version = Column(String(40), nullable=False, default="1.0")
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    definition = relationship("PromptDefinition", back_populates="variants")


class Campaign(Base):
    __tablename__ = "research_campaigns"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wave_id = Column(Uuid(as_uuid=True), ForeignKey("research_study_waves.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    status = Column(String(40), nullable=False, default="draft", index=True)
    target_per_prompt = Column(Integer, nullable=False)
    requested_total = Column(Integer, nullable=False, default=0)
    completed_total = Column(Integer, nullable=False, default=0)
    generated_total = Column(Integer, nullable=False, default=0)
    validated_total = Column(Integer, nullable=False, default=0)
    unverified_total = Column(Integer, nullable=False, default=0)
    failed_total = Column(Integer, nullable=False, default=0)
    prompt_set_hash = Column(String(64), nullable=False)
    manifest_json = Column(Text, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    wave = relationship("StudyWave", back_populates="campaigns")
    prompts = relationship("CampaignPrompt", back_populates="campaign", cascade="all, delete-orphan")


class CampaignPrompt(Base):
    __tablename__ = "research_campaign_prompts"
    __table_args__ = (
        UniqueConstraint("campaign_id", "selection_key", name="uq_research_campaign_prompt"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(Uuid(as_uuid=True), ForeignKey("research_campaigns.id"), nullable=False, index=True)
    prompt_definition_id = Column(
        Uuid(as_uuid=True), ForeignKey("research_prompt_definitions.id"), nullable=False, index=True
    )
    prompt_variant_id = Column(
        Uuid(as_uuid=True), ForeignKey("research_prompt_variants.id"), nullable=True, index=True
    )
    selection_key = Column(String(255), nullable=False)
    source_prompt = Column(String(1000), nullable=False)
    standardized_prompt = Column(Text, nullable=False)
    standardizer_version = Column(String(40), nullable=False)
    target_count = Column(Integer, nullable=False)
    queued_count = Column(Integer, nullable=False, default=0)
    completed_count = Column(Integer, nullable=False, default=0)
    validated_count = Column(Integer, nullable=False, default=0)
    status = Column(String(40), nullable=False, default="planned")

    campaign = relationship("Campaign", back_populates="prompts")
    definition = relationship("PromptDefinition")
    variant = relationship("PromptVariant")
    tasks = relationship("ResearchTask", back_populates="campaign_prompt", cascade="all, delete-orphan")


class ResearchTask(Base):
    """Persistent idempotency ledger bridging research to legacy data."""

    __tablename__ = "research_tasks"
    __table_args__ = (
        UniqueConstraint("campaign_prompt_id", "sample_index", name="uq_research_task_slot"),
        UniqueConstraint("result_id", name="uq_research_task_result"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_prompt_id = Column(
        Uuid(as_uuid=True), ForeignKey("research_campaign_prompts.id"), nullable=False, index=True
    )
    sample_index = Column(Integer, nullable=False)
    status = Column(String(40), nullable=False, default="planned", index=True)
    experiment_id = Column(Uuid(as_uuid=True), ForeignKey("experiments.id"), nullable=True, index=True)
    result_id = Column(Uuid(as_uuid=True), ForeignKey("results.id"), nullable=True, index=True)
    error_code = Column(String(100), nullable=True)
    safe_error_message = Column(String(500), nullable=True)
    queued_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    campaign_prompt = relationship("CampaignPrompt", back_populates="tasks")
    experiment = relationship("Experiment")
    result = relationship("Result")


class ResearchAnalysisV2(Base):
    __tablename__ = "research_analysis_v2"
    __table_args__ = (
        UniqueConstraint("result_id", "provider", "revision", name="uq_research_analysis_revision"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    result_id = Column(Uuid(as_uuid=True), ForeignKey("results.id"), nullable=False, index=True)
    provider = Column(String(50), nullable=False)
    model_name = Column(String(120), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    analysis_schema_version = Column(String(20), nullable=False, default="2.0")
    status = Column(String(40), nullable=False, default="pending")
    source_type = Column(String(40), nullable=False, default="machine_provisional")
    payload_json = Column(Text, nullable=True)
    quality_flags_json = Column(Text, nullable=False, default="[]")
    error_code = Column(String(100), nullable=True)
    safe_error_message = Column(String(500), nullable=True)
    is_active = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    result = relationship("Result")


class BenchmarkSnapshot(Base):
    """Wave-scoped, source-labelled benchmark distribution; never invented."""

    __tablename__ = "research_benchmark_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "study_wave_id", "version", "dimension", "scope_type", "scope_key",
            name="uq_research_benchmark_snapshot",
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    study_wave_id = Column(Uuid(as_uuid=True), ForeignKey("research_study_waves.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    version = Column(String(40), nullable=False)
    dimension = Column(String(80), nullable=False)
    scope_type = Column(String(80), nullable=False)
    scope_key = Column(String(140), nullable=False)
    reference_year = Column(String(20), nullable=True)
    geographic_scope = Column(String(255), nullable=True)
    source_organization = Column(String(255), nullable=False)
    source_title = Column(String(500), nullable=False)
    source_url = Column(String(1000), nullable=True)
    denominator_description = Column(String(1000), nullable=False)
    category_mapping_json = Column(Text, nullable=False, default="{}")
    distribution_json = Column(Text, nullable=False)
    verification_status = Column(String(40), nullable=False, default="configured")
    retrieved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    locked_at = Column(DateTime, nullable=True)

    mappings = relationship("BenchmarkMapping", back_populates="snapshot", cascade="all, delete-orphan")


class BenchmarkMapping(Base):
    __tablename__ = "research_benchmark_mappings"
    __table_args__ = (
        UniqueConstraint("benchmark_snapshot_id", "prompt_definition_id", name="uq_research_benchmark_mapping"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    benchmark_snapshot_id = Column(
        Uuid(as_uuid=True), ForeignKey("research_benchmark_snapshots.id"), nullable=False, index=True
    )
    prompt_definition_id = Column(
        Uuid(as_uuid=True), ForeignKey("research_prompt_definitions.id"), nullable=False, index=True
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    snapshot = relationship("BenchmarkSnapshot", back_populates="mappings")
    prompt_definition = relationship("PromptDefinition")
