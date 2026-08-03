import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from backend.core.config import settings
from backend.core.database import get_db
from backend.models.research_models import BenchmarkSnapshot, Campaign, CampaignPrompt, PromptDefinition, ResearchAnalysisV2, ResearchTask, Study, StudyWave
from backend.models.models import Result
from backend.schemas.research import (
    AtlasResponse,
    AnalysisSourceResponse,
    BenchmarkCreate,
    BenchmarkResponse,
    CampaignCreate,
    CampaignResponse,
    CampaignStatusResponse,
    DryRunResponse,
    EvidenceResponse,
    PromptDefinitionResponse,
    StudyCreate,
    StudyDetail,
    StudyResponse,
    TrajectoryResponse,
    WaveCreate,
    WaveResponse,
)
from backend.services.queue_worker import queue_worker
from backend.services.research_campaign_service import (
    COST_WARNING,
    ResearchStateError,
    canonical_counts,
    create_campaign,
    create_study,
    create_wave,
    dry_run,
    pause_campaign,
    research_schema_available,
    resume_campaign,
    start_campaign,
)
from backend.services.research_metrics_service import atlas, evidence, trajectory
from backend.services.research_benchmark_service import benchmark_payload, create_benchmark


router = APIRouter()


def _require_schema(db: Session) -> None:
    if not research_schema_available(db):
        raise HTTPException(
            status_code=503,
            detail="Research schema is not installed. Review and run the additive research migration first.",
        )


def _wave_payload(wave: StudyWave) -> dict:
    data = {column.name: getattr(wave, column.name) for column in wave.__table__.columns if column.name != "manifest_json"}
    data["manifest"] = json.loads(wave.manifest_json) if wave.manifest_json else None
    return data


def _prompt_payload(prompt: PromptDefinition) -> dict:
    return {
        "id": prompt.id,
        "slug": prompt.slug,
        "category": prompt.category,
        "concept_key": prompt.concept_key,
        "language": prompt.language,
        "prompt_text": prompt.prompt_text,
        "prompt_version": prompt.prompt_version,
        "scene_policy": prompt.scene_policy,
        "expected_person_policy": prompt.expected_person_policy,
        "applicable_dimensions": json.loads(prompt.applicable_dimensions_json),
        "active": prompt.active,
    }


def _campaign_payload(campaign: Campaign) -> dict:
    return {
        "id": campaign.id,
        "wave_id": campaign.wave_id,
        "name": campaign.name,
        "status": campaign.status,
        "target_per_prompt": campaign.target_per_prompt,
        "requested_total": campaign.requested_total,
        "completed_total": campaign.completed_total,
        "generated_total": campaign.generated_total,
        "validated_total": campaign.validated_total,
        "unverified_total": campaign.unverified_total,
        "failed_total": campaign.failed_total,
        "prompt_set_hash": campaign.prompt_set_hash,
        "manifest": json.loads(campaign.manifest_json),
        "started_at": campaign.started_at,
        "completed_at": campaign.completed_at,
        "created_at": campaign.created_at,
        "prompts": [{
            "id": item.id,
            "prompt_definition_id": item.prompt_definition_id,
            "prompt_variant_id": item.prompt_variant_id,
            "prompt_slug": item.definition.slug,
            "language": item.definition.language,
            "source_prompt": item.source_prompt,
            "standardized_prompt": item.standardized_prompt,
            "scene_policy": item.definition.scene_policy,
            "expected_person_policy": item.definition.expected_person_policy,
            "target_count": item.target_count,
            "queued_count": item.queued_count,
            "completed_count": item.completed_count,
            "validated_count": item.validated_count,
            "status": item.status,
        } for item in campaign.prompts],
    }


def _campaign_query(db: Session):
    return db.query(Campaign).options(
        joinedload(Campaign.wave),
        joinedload(Campaign.prompts).joinedload(CampaignPrompt.definition),
        joinedload(Campaign.prompts).joinedload(CampaignPrompt.tasks),
    )


@router.get("/studies", response_model=list[StudyResponse])
def list_studies(db: Session = Depends(get_db)):
    _require_schema(db)
    return db.query(Study).order_by(Study.created_at.desc()).all()


@router.post("/studies", response_model=StudyResponse, status_code=201)
def post_study(body: StudyCreate, db: Session = Depends(get_db)):
    _require_schema(db)
    try:
        return create_study(db, body)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A study with this slug already exists") from exc


@router.get("/studies/{study_id}", response_model=StudyDetail)
def get_study(study_id: UUID, db: Session = Depends(get_db)):
    _require_schema(db)
    study = db.query(Study).options(joinedload(Study.waves)).filter(Study.id == study_id).first()
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    payload = {column.name: getattr(study, column.name) for column in study.__table__.columns}
    payload["waves"] = [_wave_payload(wave) for wave in study.waves]
    return payload


@router.post("/studies/{study_id}/waves", response_model=WaveResponse, status_code=201)
def post_wave(study_id: UUID, body: WaveCreate, db: Session = Depends(get_db)):
    _require_schema(db)
    study = db.query(Study).filter(Study.id == study_id).first()
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    try:
        return _wave_payload(create_wave(db, study, body))
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This wave label already exists in the study") from exc


@router.get("/waves/{wave_id}", response_model=WaveResponse)
def get_wave(wave_id: UUID, db: Session = Depends(get_db)):
    _require_schema(db)
    wave = db.query(StudyWave).filter(StudyWave.id == wave_id).first()
    if not wave:
        raise HTTPException(status_code=404, detail="Wave not found")
    return _wave_payload(wave)


@router.get("/prompts", response_model=list[PromptDefinitionResponse])
def list_research_prompts(
    language: str | None = Query(default=None, pattern="^(en|tr)$"),
    category: str | None = None,
    db: Session = Depends(get_db),
):
    _require_schema(db)
    query = db.query(PromptDefinition).filter(
        PromptDefinition.active == True  # noqa: E712 - MSSQL requires "= 1"
    )
    if language:
        query = query.filter(PromptDefinition.language == language)
    if category:
        query = query.filter(PromptDefinition.category == category)
    return [_prompt_payload(prompt) for prompt in query.order_by(PromptDefinition.category, PromptDefinition.slug).all()]


@router.post("/benchmarks", response_model=BenchmarkResponse, status_code=201)
def post_benchmark(body: BenchmarkCreate, db: Session = Depends(get_db)):
    _require_schema(db)
    try:
        return benchmark_payload(create_benchmark(db, body))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ResearchStateError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This benchmark snapshot already exists") from exc


@router.get("/waves/{wave_id}/benchmarks", response_model=list[BenchmarkResponse])
def list_benchmarks(wave_id: UUID, db: Session = Depends(get_db)):
    _require_schema(db)
    wave = db.query(StudyWave).filter(StudyWave.id == wave_id).first()
    if not wave:
        raise HTTPException(status_code=404, detail="Wave not found")
    rows = db.query(BenchmarkSnapshot).filter(
        BenchmarkSnapshot.study_wave_id == wave_id
    ).order_by(BenchmarkSnapshot.dimension, BenchmarkSnapshot.name).all()
    return [benchmark_payload(row) for row in rows]


@router.post("/campaigns", response_model=CampaignResponse, status_code=201)
def post_campaign(body: CampaignCreate, db: Session = Depends(get_db)):
    _require_schema(db)
    try:
        campaign = create_campaign(db, body)
        campaign = _campaign_query(db).filter(Campaign.id == campaign.id).first()
        return _campaign_payload(campaign)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ResearchStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This campaign plan conflicts with an existing record") from exc


@router.get("/campaigns", response_model=list[CampaignResponse])
def list_campaigns(wave_id: UUID | None = None, db: Session = Depends(get_db)):
    _require_schema(db)
    query = _campaign_query(db)
    if wave_id:
        query = query.filter(Campaign.wave_id == wave_id)
    return [_campaign_payload(item) for item in query.order_by(Campaign.created_at.desc()).limit(100).all()]


@router.get("/campaigns/{campaign_id}", response_model=CampaignResponse)
def get_campaign(campaign_id: UUID, db: Session = Depends(get_db)):
    _require_schema(db)
    campaign = _campaign_query(db).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _campaign_payload(campaign)


@router.get("/campaigns/{campaign_id}/dry-run", response_model=DryRunResponse)
def campaign_dry_run(campaign_id: UUID, db: Session = Depends(get_db)):
    _require_schema(db)
    campaign = _campaign_query(db).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return dry_run(db, campaign)


def _require_provider_config() -> None:
    if not settings.GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not configured")
    if settings.IMAGE_PROVIDER == "openai" and not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")
    if settings.IMAGE_PROVIDER == "pollinations" and not settings.POLLINATIONS_API_KEY:
        raise HTTPException(status_code=503, detail="POLLINATIONS_API_KEY is not configured")


@router.post("/campaigns/{campaign_id}/start", response_model=CampaignStatusResponse)
async def campaign_start(campaign_id: UUID, db: Session = Depends(get_db)):
    _require_schema(db)
    _require_provider_config()
    try:
        await start_campaign(campaign_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ResearchStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return campaign_status(campaign_id, db)


@router.post("/campaigns/{campaign_id}/pause", response_model=CampaignStatusResponse)
def campaign_pause(campaign_id: UUID, db: Session = Depends(get_db)):
    _require_schema(db)
    campaign = _campaign_query(db).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    try:
        pause_campaign(db, campaign)
    except ResearchStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return campaign_status(campaign_id, db)


@router.post("/campaigns/{campaign_id}/resume", response_model=CampaignStatusResponse)
async def campaign_resume(campaign_id: UUID, db: Session = Depends(get_db)):
    _require_schema(db)
    _require_provider_config()
    try:
        await resume_campaign(campaign_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ResearchStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return campaign_status(campaign_id, db)


@router.get("/campaigns/{campaign_id}/status", response_model=CampaignStatusResponse)
def campaign_status(campaign_id: UUID, db: Session = Depends(get_db)):
    _require_schema(db)
    campaign = _campaign_query(db).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    counts = canonical_counts(db, campaign)
    return {
        "campaign_id": campaign.id,
        "status": campaign.status,
        "counts": counts,
        "queue_depth": queue_worker.queue.qsize(),
        "cost_warning": COST_WARNING,
        "safe_message": (
            "Paused campaigns enqueue no new samples; already running samples may finish safely."
            if campaign.status == "paused" else None
        ),
    }


@router.get("/campaign-prompts/{campaign_prompt_id}/trajectory", response_model=TrajectoryResponse)
def get_trajectory(
    campaign_prompt_id: UUID,
    dimension: str = Query(pattern="^(visible_gender_presentation|estimated_age_group|urbanicity|technology_presence|occupation_alignment)$"),
    provider: str | None = None,
    model: str | None = None,
    revision: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    _require_schema(db)
    item = db.query(CampaignPrompt).options(
        joinedload(CampaignPrompt.campaign).joinedload(Campaign.wave)
    ).filter(CampaignPrompt.id == campaign_prompt_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Campaign prompt not found")
    try:
        return trajectory(db, item, dimension, provider=provider, model=model, revision=revision)
    except ResearchStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/waves/{wave_id}/atlas", response_model=AtlasResponse)
def get_atlas(
    wave_id: UUID,
    language: str | None = Query(default=None, pattern="^(en|tr)$"),
    category: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    revision: int | None = Query(default=None, ge=1),
    minimum_n: int = Query(default=10, ge=2, le=1000),
    db: Session = Depends(get_db),
):
    _require_schema(db)
    wave = db.query(StudyWave).filter(StudyWave.id == wave_id).first()
    if not wave:
        raise HTTPException(status_code=404, detail="Wave not found")
    try:
        return atlas(
            db, wave, language=language, category=category,
            provider=provider, model=model, revision=revision, minimum_n=minimum_n,
        )
    except ResearchStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/waves/{wave_id}/analysis-sources", response_model=list[AnalysisSourceResponse])
def get_analysis_sources(wave_id: UUID, db: Session = Depends(get_db)):
    _require_schema(db)
    wave = db.query(StudyWave).filter(StudyWave.id == wave_id).first()
    if not wave:
        raise HTTPException(status_code=404, detail="Wave not found")
    rows = db.query(ResearchAnalysisV2).join(Result).join(
        ResearchTask, ResearchTask.result_id == Result.id
    ).join(CampaignPrompt).join(Campaign).filter(
        Campaign.wave_id == wave_id,
        ResearchAnalysisV2.is_active == True,  # noqa: E712 - MSSQL requires "= 1"
    ).all()
    counts = {}
    for row in rows:
        key = (row.provider, row.model_name, row.revision, row.source_type)
        counts[key] = counts.get(key, 0) + 1
    return [{
        "provider": key[0], "model": key[1], "revision": key[2],
        "source_type": key[3], "active_result_count": count,
    } for key, count in sorted(counts.items())]


@router.get("/waves/{wave_id}/atlas/evidence", response_model=EvidenceResponse)
def get_atlas_evidence(
    wave_id: UUID,
    campaign_prompt_id: UUID,
    dimension: str = Query(pattern="^(visible_gender_presentation|estimated_age_group|urbanicity|technology_presence|occupation_alignment)$"),
    category_value: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    revision: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    _require_schema(db)
    wave = db.query(StudyWave).filter(StudyWave.id == wave_id).first()
    if not wave:
        raise HTTPException(status_code=404, detail="Wave not found")
    item = db.query(CampaignPrompt).options(
        joinedload(CampaignPrompt.campaign).joinedload(Campaign.wave)
    ).filter(CampaignPrompt.id == campaign_prompt_id).first()
    if not item or item.campaign.wave_id != wave.id:
        raise HTTPException(status_code=404, detail="Campaign prompt not found in this wave")
    try:
        return evidence(
            db, wave, item, dimension, category_value, provider=provider, model=model, revision=revision
        )
    except ResearchStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
