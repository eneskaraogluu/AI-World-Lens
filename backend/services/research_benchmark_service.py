"""Controlled benchmark registry with distribution and mapping validation."""

import json
import math

from sqlalchemy.orm import Session

from backend.models.research_models import BenchmarkMapping, BenchmarkSnapshot, PromptDefinition, StudyWave
from backend.services.research_campaign_service import ResearchStateError, canonical_json


def normalize_distribution(values: dict[str, float]) -> dict[str, float]:
    if not values:
        raise ValueError("Benchmark distribution cannot be empty")
    if any(not key.strip() for key in values):
        raise ValueError("Benchmark categories cannot be empty")
    if any(not math.isfinite(value) or value < 0 for value in values.values()):
        raise ValueError("Benchmark shares must be finite and non-negative")
    total = sum(values.values())
    if abs(total - 100.0) <= 0.01:
        normalized = {key: value / 100 for key, value in values.items()}
    elif abs(total - 1.0) <= 0.0001:
        normalized = dict(values)
    else:
        raise ValueError("Benchmark distribution must total 1.0 or 100%")
    return {key: round(value, 8) for key, value in sorted(normalized.items())}


def create_benchmark(db: Session, data) -> BenchmarkSnapshot:
    wave = db.query(StudyWave).filter(StudyWave.id == data.study_wave_id).first()
    if not wave:
        raise LookupError("Wave not found")
    if wave.locked_at:
        raise ResearchStateError("Wave is locked; benchmark snapshots cannot be changed")
    prompts = db.query(PromptDefinition).filter(PromptDefinition.id.in_(data.prompt_definition_ids)).all()
    if len(prompts) != len(data.prompt_definition_ids):
        raise ValueError("One or more benchmark prompt mappings are invalid")
    distribution = normalize_distribution(data.distribution)
    snapshot = BenchmarkSnapshot(
        study_wave_id=wave.id,
        name=data.name,
        version=data.version,
        dimension=data.dimension,
        scope_type=data.scope_type,
        scope_key=data.scope_key,
        reference_year=data.reference_year,
        geographic_scope=data.geographic_scope,
        source_organization=data.source_organization,
        source_title=data.source_title,
        source_url=data.source_url,
        denominator_description=data.denominator_description,
        category_mapping_json=canonical_json(data.category_mapping),
        distribution_json=canonical_json(distribution),
        verification_status=data.verification_status,
        retrieved_at=data.retrieved_at,
    )
    db.add(snapshot)
    db.flush()
    for prompt in prompts:
        db.add(BenchmarkMapping(benchmark_snapshot_id=snapshot.id, prompt_definition_id=prompt.id))
    if wave.benchmark_version == "unconfigured":
        wave.benchmark_version = data.version
    elif wave.benchmark_version != data.version:
        raise ResearchStateError("Benchmark version does not match the wave protocol")
    db.commit()
    db.refresh(snapshot)
    return snapshot


def benchmark_payload(snapshot: BenchmarkSnapshot) -> dict:
    return {
        "id": snapshot.id,
        "study_wave_id": snapshot.study_wave_id,
        "name": snapshot.name,
        "version": snapshot.version,
        "dimension": snapshot.dimension,
        "scope_type": snapshot.scope_type,
        "scope_key": snapshot.scope_key,
        "reference_year": snapshot.reference_year,
        "geographic_scope": snapshot.geographic_scope,
        "source_organization": snapshot.source_organization,
        "source_title": snapshot.source_title,
        "source_url": snapshot.source_url,
        "denominator_description": snapshot.denominator_description,
        "category_mapping": json.loads(snapshot.category_mapping_json),
        "distribution": json.loads(snapshot.distribution_json),
        "verification_status": snapshot.verification_status,
        "retrieved_at": snapshot.retrieved_at,
        "created_at": snapshot.created_at,
        "locked_at": snapshot.locked_at,
        "prompt_definition_ids": [mapping.prompt_definition_id for mapping in snapshot.mappings],
    }
