"""Additive persistence for verified, offline presentation replays."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, text

from backend.models.base import Base


class PresentationBackup(Base):
    __tablename__ = "presentation_backups"
    __table_args__ = (
        UniqueConstraint(
            "source_experiment_id", "analysis_revision_id",
            name="uq_presentation_backup_source_revision",
        ),
        Index(
            "uq_presentation_backup_single_active",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
            mssql_where=text("is_active = 1"),
            postgresql_where=text("is_active = true"),
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    source_experiment_id = Column(Uuid(as_uuid=True), ForeignKey("experiments.id"), nullable=False, index=True)
    prompt_id = Column(Uuid(as_uuid=True), ForeignKey("prompts.id"), nullable=False, index=True)
    prompt_text = Column(String(1000), nullable=False)
    status = Column(String(40), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=False, index=True)
    requested_count = Column(Integer, nullable=False)
    completed_count = Column(Integer, nullable=False)
    generated_count = Column(Integer, nullable=False)
    validated_count = Column(Integer, nullable=False)
    unverified_count = Column(Integer, nullable=False)
    failed_count = Column(Integer, nullable=False)
    generator_provider = Column(String(80), nullable=False)
    generator_model = Column(String(120), nullable=False)
    analyzer_provider = Column(String(80), nullable=False)
    analyzer_model = Column(String(120), nullable=False)
    analysis_revision_id = Column(Integer, nullable=False)
    benchmark_snapshot_id = Column(Uuid(as_uuid=True), nullable=True)
    manifest_version = Column(String(20), nullable=False, default="1.0")
    manifest_json = Column(Text, nullable=False)
    manifest_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    verified_at = Column(DateTime, nullable=True)
    last_replayed_at = Column(DateTime, nullable=True)
