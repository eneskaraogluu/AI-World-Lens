"""Persistent experiment work ledger used by serverless deployments."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid

from backend.models.base import Base


class ExperimentJob(Base):
    __tablename__ = "experiment_jobs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    experiment_id = Column(Uuid(as_uuid=True), ForeignKey("experiments.id"), nullable=False, unique=True, index=True)
    prompt_id = Column(Uuid(as_uuid=True), ForeignKey("prompts.id"), nullable=False, index=True)
    job_type = Column(String(40), nullable=False, default="generation")
    status = Column(String(40), nullable=False, default="processing", index=True)
    total = Column(Integer, nullable=False)
    completed = Column(Integer, nullable=False, default=0)
    generated = Column(Integer, nullable=False, default=0)
    succeeded = Column(Integer, nullable=False, default=0)
    unverified = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    last_error = Column(String(1000), nullable=True)
    fallback_reason = Column(String(120), nullable=True)
    safe_message = Column(String(1000), nullable=True)
    analysis_provider = Column(String(50), nullable=False, default="gemini")
    analysis_model = Column(String(120), nullable=False)
    analysis_revision = Column(Integer, nullable=False, default=1)
    failure_breakdown_json = Column(Text, nullable=False, default='{"generation":0,"analysis":0,"worker":0}')
    events_json = Column(Text, nullable=False, default="[]")
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExperimentTask(Base):
    __tablename__ = "experiment_tasks"
    __table_args__ = (
        UniqueConstraint("experiment_id", "sample_index", "task_kind", name="uq_experiment_task_slot"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    experiment_id = Column(Uuid(as_uuid=True), ForeignKey("experiments.id"), nullable=False, index=True)
    sample_index = Column(Integer, nullable=False)
    task_kind = Column(String(40), nullable=False, default="generation")
    status = Column(String(40), nullable=False, default="pending", index=True)
    payload_json = Column(Text, nullable=False)
    locked_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
