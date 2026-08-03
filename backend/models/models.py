import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, String, Integer, DateTime, ForeignKey, Uuid
from sqlalchemy.orm import relationship
from backend.models.base import Base

class Category(Base):
    __tablename__ = "categories"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    prompts = relationship("Prompt", back_populates="category", cascade="all, delete-orphan")

class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_id = Column(Uuid(as_uuid=True), ForeignKey("categories.id"), nullable=False)
    text = Column(String(1000), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    category = relationship("Category", back_populates="prompts")
    results = relationship("Result", back_populates="prompt", cascade="all, delete-orphan")

class Experiment(Base):
    __tablename__ = "experiments"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    model_name = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, default="running")
    created_at = Column(DateTime, default=datetime.utcnow)

    results = relationship("Result", back_populates="experiment", cascade="all, delete-orphan")

class Result(Base):
    __tablename__ = "results"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    experiment_id = Column(Uuid(as_uuid=True), ForeignKey("experiments.id"), nullable=False)
    prompt_id = Column(Uuid(as_uuid=True), ForeignKey("prompts.id"), nullable=False)
    
    generation_id = Column(String(255), nullable=True)
    image_reference = Column(String(1000), nullable=True)
    
    detected_age_group = Column(String(50), nullable=True)
    detected_gender = Column(String(50), nullable=True)
    detected_person_count = Column(Integer, nullable=True)
    
    # New columns for Academic Alignment
    detected_location = Column(String(100), nullable=True)
    detected_socioeconomic_status = Column(String(100), nullable=True)
    coder1_data = Column(String(2000), nullable=True) # Raw JSON from Coder 1
    coder2_data = Column(String(2000), nullable=True) # Raw JSON from Coder 2
    coder_agreement_score = Column(Integer, nullable=True) # e.g., 0-100% agreement
    
    # New columns for Advanced Architecture (Architectural Review)
    model_name = Column(String(100), nullable=True) # e.g., 'pollinations-flux'
    model_version = Column(String(50), nullable=True) # e.g., '1.0'
    seed = Column(Integer, nullable=True) # for reproducibility
    generation_duration = Column(Integer, nullable=True) # ms or seconds
    analysis_duration = Column(Integer, nullable=True) # ms or seconds
    error_message = Column(String(2000), nullable=True) # tracking why an API call failed
    
    analysis_status = Column(String(50), nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)

    experiment = relationship("Experiment", back_populates="results")
    prompt = relationship("Prompt", back_populates="results")
    analyses = relationship("ResultAnalysis", back_populates="result", cascade="all, delete-orphan")


class ResultAnalysis(Base):
    """Additive provider/revision history for a generated Result.

    Legacy Result demographic columns remain readable. New runs also write here,
    allowing a complete experiment to atomically switch analysis providers.
    """

    __tablename__ = "result_analyses"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    result_id = Column(Uuid(as_uuid=True), ForeignKey("results.id"), nullable=False, index=True)
    provider = Column(String(50), nullable=False)
    model_name = Column(String(100), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    status = Column(String(50), nullable=False, default="pending")
    detected_age_group = Column(String(50), nullable=True)
    detected_gender = Column(String(50), nullable=True)
    detected_person_count = Column(Integer, nullable=True)
    analysis_duration = Column(Integer, nullable=True)
    error_code = Column(String(100), nullable=True)
    safe_error_message = Column(String(500), nullable=True)
    fallback_reason = Column(String(100), nullable=True)
    is_active = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    result = relationship("Result", back_populates="analyses")
