"""Persistent research campaign planning and controlled queue dispatch."""

import asyncio
import hashlib
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import inspect
from sqlalchemy.orm import Session, joinedload

from backend.core.config import settings
from backend.core.database import SessionLocal
from backend.models.models import Category, Experiment, Prompt, Result
from backend.models.research_models import (
    Campaign,
    CampaignPrompt,
    BenchmarkSnapshot,
    BenchmarkMapping,
    PromptDefinition,
    PromptVariant,
    ResearchAnalysisV2,
    ResearchTask,
    Study,
    StudyWave,
)
from backend.services.analysis_revision_service import is_generated_result
from backend.services.research_analysis_service import decode_payload
from backend.services.research_prompt_service import STANDARDIZER_VERSION, prompt_set_hash, standardize_prompt


TERMINAL_TASK_STATUSES = {"validated", "unverified", "failed", "excluded"}
ACTIVE_TASK_STATUSES = {"queued", "processing"}
COST_WARNING = "Starting a real research campaign consumes provider quota and may incur API charges."
_dispatch_lock = asyncio.Lock()


class ResearchStateError(RuntimeError):
    pass


def research_schema_available(db: Session) -> bool:
    inspector = inspect(db.get_bind())
    required = {
        Study.__tablename__, StudyWave.__tablename__, PromptDefinition.__tablename__,
        Campaign.__tablename__, CampaignPrompt.__tablename__, ResearchTask.__tablename__,
        ResearchAnalysisV2.__tablename__, BenchmarkSnapshot.__tablename__, BenchmarkMapping.__tablename__,
    }
    return all(inspector.has_table(table) for table in required)


def canonical_json(value: dict | list) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_manifest(
    wave: StudyWave,
    study: Study,
    prompts: list[PromptDefinition],
    target_per_prompt: int,
    *,
    created_at: datetime,
) -> dict:
    return {
        "study": study.title,
        "study_slug": study.slug,
        "wave": wave.label,
        "protocol_version": study.protocol_version,
        "prompt_set_version": wave.prompt_set_version,
        "prompt_set_hash": prompt_set_hash(prompts),
        "standardizer_version": wave.standardizer_version,
        "codebook_version": wave.codebook_version,
        "benchmark_version": wave.benchmark_version,
        "generator": {
            "provider": wave.generator_provider,
            "model": wave.generator_model,
            "size": wave.generator_size,
            "quality": wave.generator_quality,
        },
        "analyzer": {"provider": wave.analyzer_provider, "model": wave.analyzer_model},
        "target_per_prompt": target_per_prompt,
        "created_at": created_at.replace(microsecond=0).isoformat() + "Z",
    }


def create_study(db: Session, data) -> Study:
    row = Study(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def create_wave(db: Session, study: Study, data) -> StudyWave:
    row = StudyWave(
        study_id=study.id,
        label=data.label,
        description=data.description,
        generator_provider=settings.IMAGE_PROVIDER,
        generator_model=(settings.OPENAI_IMAGE_MODEL if settings.IMAGE_PROVIDER == "openai" else settings.POLLINATIONS_MODEL),
        generator_size=settings.OPENAI_IMAGE_SIZE,
        generator_quality=settings.OPENAI_IMAGE_QUALITY,
        analyzer_provider=settings.PRIMARY_VISION_PROVIDER,
        analyzer_model=settings.GEMINI_MODEL,
        prompt_set_version=data.prompt_set_version,
        standardizer_version=STANDARDIZER_VERSION,
        codebook_version=data.codebook_version,
        benchmark_version=data.benchmark_version,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _selection_hash(definitions: list[PromptDefinition], variants: dict[UUID, PromptVariant]) -> str:
    rows = []
    for definition in sorted(
        definitions, key=lambda item: (item.slug, item.language, item.prompt_version)
    ):
        variant = variants.get(definition.id)
        rows.append({
            "slug": definition.slug,
            "concept_key": definition.concept_key,
            "language": definition.language,
            "prompt_version": definition.prompt_version,
            "scene_policy": definition.scene_policy,
            "expected_person_policy": definition.expected_person_policy,
            "variant_label": variant.variant_label if variant else None,
            "variant_version": variant.version if variant else None,
            "text": " ".join((variant.prompt_text if variant else definition.prompt_text).split()),
        })
    return hashlib.sha256(canonical_json(rows).encode("utf-8")).hexdigest()


def create_campaign(db: Session, data) -> Campaign:
    wave = db.query(StudyWave).options(joinedload(StudyWave.study)).filter(StudyWave.id == data.wave_id).first()
    if not wave:
        raise LookupError("Wave not found")
    definitions = db.query(PromptDefinition).filter(
        PromptDefinition.id.in_(data.prompt_definition_ids),
        PromptDefinition.active == True,  # noqa: E712 - MSSQL requires "= 1"
    ).all()
    if len(definitions) != len(data.prompt_definition_ids):
        raise ValueError("One or more prompt definitions are missing or inactive")
    variant_rows = db.query(PromptVariant).filter(
        PromptVariant.id.in_(data.prompt_variant_ids),
        PromptVariant.active == True,  # noqa: E712 - MSSQL requires "= 1"
    ).all() if data.prompt_variant_ids else []
    variants = {row.prompt_definition_id: row for row in variant_rows}
    definitions_by_id = {item.id: item for item in definitions}
    if len(variant_rows) != len(data.prompt_variant_ids) or any(
        row.prompt_definition_id not in definitions_by_id
        or row.language != definitions_by_id[row.prompt_definition_id].language
        for row in variant_rows
    ):
        raise ValueError("Every variant must be active and belong to a selected prompt definition")

    selection_hash = _selection_hash(definitions, variants)
    if wave.locked_at and wave.prompt_set_hash != selection_hash:
        raise ResearchStateError("Wave is locked to a different prompt set")
    created_at = datetime.utcnow()
    manifest = build_manifest(wave, wave.study, definitions, data.target_per_prompt, created_at=created_at)
    manifest["prompt_set_hash"] = selection_hash
    campaign = Campaign(
        wave_id=wave.id,
        name=data.name,
        target_per_prompt=data.target_per_prompt,
        requested_total=len(definitions) * data.target_per_prompt,
        prompt_set_hash=selection_hash,
        manifest_json=canonical_json(manifest),
        created_at=created_at,
    )
    db.add(campaign)
    db.flush()
    for definition in sorted(definitions, key=lambda item: (item.category, item.slug)):
        variant = variants.get(definition.id)
        source_prompt = variant.prompt_text if variant else definition.prompt_text
        db.add(CampaignPrompt(
            campaign_id=campaign.id,
            prompt_definition_id=definition.id,
            prompt_variant_id=variant.id if variant else None,
            selection_key=f"{definition.id}:{variant.id if variant else 'base'}",
            source_prompt=source_prompt,
            standardized_prompt=standardize_prompt(source_prompt, definition.scene_policy),
            standardizer_version=wave.standardizer_version,
            target_count=data.target_per_prompt,
        ))
    if not wave.locked_at:
        wave.prompt_set_hash = selection_hash
        wave.manifest_json = canonical_json(manifest)
        wave.locked_at = created_at
        wave.status = "locked"
        db.query(BenchmarkSnapshot).filter(
            BenchmarkSnapshot.study_wave_id == wave.id,
            BenchmarkSnapshot.locked_at.is_(None),
        ).update({BenchmarkSnapshot.locked_at: created_at}, synchronize_session=False)
    db.commit()
    db.refresh(campaign)
    return campaign


def materialize_tasks(db: Session, campaign: Campaign) -> int:
    existing = {(row.campaign_prompt_id, row.sample_index) for row in db.query(ResearchTask).join(CampaignPrompt).filter(
        CampaignPrompt.campaign_id == campaign.id
    ).all()}
    created = 0
    for item in campaign.prompts:
        for sample_index in range(1, item.target_count + 1):
            key = (item.id, sample_index)
            if key not in existing:
                db.add(ResearchTask(campaign_prompt_id=item.id, sample_index=sample_index))
                created += 1
    db.commit()
    return created


def dry_run(db: Session, campaign: Campaign) -> dict:
    existing = db.query(ResearchTask).join(CampaignPrompt).filter(CampaignPrompt.campaign_id == campaign.id).count()
    duplicate_count = max(0, existing - campaign.requested_total)
    return {
        "campaign_id": campaign.id,
        "would_create_tasks": campaign.requested_total,
        "already_materialized": min(existing, campaign.requested_total),
        "missing_tasks": max(0, campaign.requested_total - existing),
        "prompt_count": len(campaign.prompts),
        "provider": {
            "generation": f"{campaign.wave.generator_provider}/{campaign.wave.generator_model}",
            "analysis": f"{campaign.wave.analyzer_provider}/{campaign.wave.analyzer_model}",
        },
        "prompt_set_hash": campaign.prompt_set_hash,
        "duplicate_tasks": duplicate_count,
        "real_api_calls_made": False,
        "cost_warning": COST_WARNING,
    }


def _ensure_legacy_experiment(db: Session, campaign_prompt: CampaignPrompt) -> tuple[Experiment, Prompt]:
    category = db.query(Category).filter(Category.name == "Research Campaign (managed)").first()
    if not category:
        category = Category(name="Research Campaign (managed)")
        db.add(category)
        db.flush()
    prompt = db.query(Prompt).filter(
        Prompt.category_id == category.id,
        Prompt.text == campaign_prompt.standardized_prompt,
    ).first()
    if not prompt:
        prompt = Prompt(category_id=category.id, text=campaign_prompt.standardized_prompt)
        db.add(prompt)
        db.flush()
    existing_task = db.query(ResearchTask).filter(
        ResearchTask.campaign_prompt_id == campaign_prompt.id,
        ResearchTask.experiment_id.is_not(None),
    ).first()
    if existing_task:
        experiment = db.query(Experiment).filter(Experiment.id == existing_task.experiment_id).first()
        if experiment:
            return experiment, prompt
    experiment = Experiment(
        name=f"Research campaign {campaign_prompt.campaign.name} / {campaign_prompt.definition.slug}",
        model_name=f"{campaign_prompt.campaign.wave.generator_model} + {campaign_prompt.campaign.wave.analyzer_model}",
        status="processing",
    )
    db.add(experiment)
    db.flush()
    db.query(ResearchTask).filter(ResearchTask.campaign_prompt_id == campaign_prompt.id).update(
        {ResearchTask.experiment_id: experiment.id}, synchronize_session=False
    )
    db.commit()
    return experiment, prompt


async def dispatch_available(campaign_id: UUID, *, use_mock: bool = False) -> int:
    async with _dispatch_lock:
        return await _dispatch_available_locked(campaign_id, use_mock=use_mock)


async def _dispatch_available_locked(campaign_id: UUID, *, use_mock: bool = False) -> int:
    """Queue only enough work to fill workers; pause can stop subsequent enqueue."""
    from backend.services.queue_worker import queue_worker

    db = SessionLocal()
    queued_now = 0
    try:
        campaign = db.query(Campaign).options(
            joinedload(Campaign.prompts).joinedload(CampaignPrompt.definition),
            joinedload(Campaign.wave),
        ).filter(Campaign.id == campaign_id).first()
        if not campaign or campaign.status != "running":
            return 0
        active = db.query(ResearchTask).join(CampaignPrompt).filter(
            CampaignPrompt.campaign_id == campaign.id,
            ResearchTask.status.in_(ACTIVE_TASK_STATUSES),
        ).count()
        capacity = max(0, settings.QUEUE_WORKERS - active)
        if capacity == 0:
            return 0
        tasks = db.query(ResearchTask).join(CampaignPrompt).filter(
            CampaignPrompt.campaign_id == campaign.id,
            ResearchTask.status == "planned",
        ).order_by(ResearchTask.sample_index.asc(), ResearchTask.created_at.asc()).limit(capacity).all()
        for task in tasks:
            campaign_prompt = task.campaign_prompt
            experiment, prompt = _ensure_legacy_experiment(db, campaign_prompt)
            already_completed = db.query(ResearchTask).filter(
                ResearchTask.campaign_prompt_id == campaign_prompt.id,
                ResearchTask.status.in_(TERMINAL_TASK_STATUSES),
            ).count()
            await queue_worker.register_research_job(
                experiment.id, prompt.id, campaign_prompt.target_count, already_completed
            )
            task.status = "queued"
            task.queued_at = datetime.utcnow()
            task.experiment_id = experiment.id
            campaign_prompt.status = "running"
            db.commit()
            generator_type = "mock-generator" if use_mock else (
                "openai-image" if campaign.wave.generator_provider == "openai" else "pollinations-flux"
            )
            await queue_worker.enqueue_task({
                "task_kind": "research_generation",
                "research_task_id": task.id,
                "campaign_id": campaign.id,
                "campaign_prompt_id": campaign_prompt.id,
                "expected_person_policy": campaign_prompt.definition.expected_person_policy,
                "prompt_id": prompt.id,
                "prompt_text": campaign_prompt.standardized_prompt,
                "experiment_id": experiment.id,
                "generator_type": generator_type,
                "seed": task.sample_index if generator_type == "mock-generator" else None,
                "sample_index": task.sample_index,
            })
            queued_now += 1
        refresh_campaign_counts(db, campaign)
        return queued_now
    finally:
        db.close()


async def start_campaign(campaign_id: UUID, *, use_mock: bool = False) -> Campaign:
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).options(joinedload(Campaign.prompts), joinedload(Campaign.wave)).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise LookupError("Campaign not found")
        if campaign.status == "completed":
            raise ResearchStateError("A completed campaign cannot be started again")
        materialize_tasks(db, campaign)
        if campaign.status != "running":
            campaign.status = "running"
            campaign.started_at = campaign.started_at or datetime.utcnow()
            campaign.wave.started_at = campaign.wave.started_at or datetime.utcnow()
            db.commit()
        result_id = campaign.id
    finally:
        db.close()
    await dispatch_available(result_id, use_mock=use_mock)
    db = SessionLocal()
    try:
        return db.query(Campaign).filter(Campaign.id == result_id).first()
    finally:
        db.close()


def pause_campaign(db: Session, campaign: Campaign) -> Campaign:
    if campaign.status == "paused":
        return campaign
    if campaign.status != "running":
        raise ResearchStateError("Only a running campaign can be paused")
    campaign.status = "paused"
    db.commit()
    db.refresh(campaign)
    return campaign


async def resume_campaign(campaign_id: UUID, *, use_mock: bool = False) -> Campaign:
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise LookupError("Campaign not found")
        if campaign.status != "paused":
            raise ResearchStateError("Only a paused campaign can be resumed")
        # Same-process queued/processing tasks remain eligible to finish and
        # must not be enqueued twice. Startup recovery already converts only
        # interrupted, result-less active slots back to planned.
        campaign.status = "running"
        db.commit()
        result_id = campaign.id
    finally:
        db.close()
    await dispatch_available(result_id, use_mock=use_mock)
    db = SessionLocal()
    try:
        return db.query(Campaign).filter(Campaign.id == result_id).first()
    finally:
        db.close()


def mark_task_processing(db: Session, task_id: UUID) -> None:
    task = db.query(ResearchTask).filter(ResearchTask.id == task_id).first()
    if task and task.status == "queued":
        task.status = "processing"
        task.started_at = datetime.utcnow()
        db.commit()


def finish_research_task(
    db: Session,
    task_id: UUID,
    result_id: UUID | None,
    status: str,
    *,
    error_code: str | None = None,
    safe_error_message: str | None = None,
) -> UUID | None:
    task = db.query(ResearchTask).options(joinedload(ResearchTask.campaign_prompt)).filter(ResearchTask.id == task_id).first()
    if not task:
        return None
    task.result_id = result_id or task.result_id
    task.status = status if status in TERMINAL_TASK_STATUSES else "unverified"
    task.error_code = error_code
    task.safe_error_message = safe_error_message
    task.completed_at = datetime.utcnow()
    campaign = task.campaign_prompt.campaign
    refresh_campaign_counts(db, campaign)
    db.commit()
    return campaign.id


def canonical_counts(db: Session, campaign: Campaign) -> dict:
    tasks = db.query(ResearchTask).join(CampaignPrompt).filter(CampaignPrompt.campaign_id == campaign.id).all()
    status_counts = {name: sum(1 for task in tasks if task.status == name) for name in (
        "queued", "processing", "validated", "unverified", "failed", "excluded"
    )}
    completed = sum(status_counts[name] for name in TERMINAL_TASK_STATUSES)
    result_ids = [task.result_id for task in tasks if task.result_id]
    results = db.query(Result).filter(Result.id.in_(result_ids)).all() if result_ids else []
    generated = sum(1 for result in results if is_generated_result(result))
    analyses = db.query(ResearchAnalysisV2).filter(
        ResearchAnalysisV2.result_id.in_(result_ids),
        ResearchAnalysisV2.is_active == True,  # noqa: E712 - MSSQL requires "= 1"
    ).all() if result_ids else []
    gender_usable = age_usable = scene_usable = 0
    for row in analyses:
        payload = decode_payload(row)
        if not payload:
            continue
        scene_usable += int(payload.scene.setting_type != "Unclear")
        gender_usable += sum(person.visible_gender_presentation != "Unclear" for person in payload.persons)
        age_usable += sum(person.estimated_age_group != "Unclear" for person in payload.persons)
    return {
        "requested": campaign.requested_total,
        "queued": status_counts["queued"],
        "processing": status_counts["processing"],
        "completed": completed,
        "generated": generated,
        "machine_validated": status_counts["validated"],
        "human_annotated": 0,
        "human_adjudicated": 0,
        "unverified": status_counts["unverified"],
        "failed": status_counts["failed"],
        "excluded": status_counts["excluded"],
        "gender_usable": gender_usable,
        "age_usable": age_usable,
        "scene_usable": scene_usable,
    }


def refresh_campaign_counts(db: Session, campaign: Campaign) -> dict:
    counts = canonical_counts(db, campaign)
    campaign.completed_total = counts["completed"]
    campaign.generated_total = counts["generated"]
    campaign.validated_total = counts["machine_validated"]
    campaign.unverified_total = counts["unverified"]
    campaign.failed_total = counts["failed"]
    for prompt in campaign.prompts:
        statuses = [task.status for task in prompt.tasks]
        prompt.queued_count = sum(status in ACTIVE_TASK_STATUSES or status in TERMINAL_TASK_STATUSES for status in statuses)
        prompt.completed_count = sum(status in TERMINAL_TASK_STATUSES for status in statuses)
        prompt.validated_count = sum(status == "validated" for status in statuses)
        if statuses and all(status in TERMINAL_TASK_STATUSES for status in statuses):
            prompt.status = "completed"
    if campaign.requested_total > 0 and counts["completed"] == campaign.requested_total:
        campaign.status = "completed"
        campaign.completed_at = datetime.utcnow()
        if campaign.wave.campaigns and all(item.status == "completed" for item in campaign.wave.campaigns):
            campaign.wave.status = "completed"
            campaign.wave.completed_at = datetime.utcnow()
    db.flush()
    return counts


def recover_interrupted_campaigns(db: Session) -> int:
    """On restart, preserve completed slots and require explicit resume."""
    campaigns = db.query(Campaign).filter(Campaign.status == "running").all()
    for campaign in campaigns:
        for prompt in campaign.prompts:
            for task in prompt.tasks:
                if task.status in ACTIVE_TASK_STATUSES and task.result_id is None:
                    task.status = "planned"
        campaign.status = "paused"
        refresh_campaign_counts(db, campaign)
    if campaigns:
        db.commit()
    return len(campaigns)
