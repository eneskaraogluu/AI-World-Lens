from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session
from uuid import UUID

from backend.core.database import get_db
from backend.schemas.experiment import ExperimentCreate, ExperimentResponse
from backend.schemas.run import ReanalyzeExperimentRequest, RunExperimentRequest
from backend.services.experiment_service import create_experiment, get_experiment
from backend.models.models import Experiment, Prompt, Result
from backend.core.config import settings
from backend.services.analysis_revision_service import (
    analysis_history_available,
    effective_analyses,
    experiment_provider_metadata,
    is_generated_result,
    is_local_generated_result,
    next_revision,
)

router = APIRouter()


@router.get("/")
def list_experiments(prompt_id: UUID | None = None, db: Session = Depends(get_db)):
    query = db.query(Experiment)
    if prompt_id:
        query = query.join(Result).filter(
            Result.prompt_id == prompt_id,
            or_(Result.model_name.is_(None), Result.model_name != "mock-generator"),
        )
    experiments = query.distinct().order_by(Experiment.created_at.desc()).limit(50).all()
    payload = []
    for experiment in experiments:
        result_count = db.query(Result).filter(
            Result.experiment_id == experiment.id,
            or_(Result.model_name.is_(None), Result.model_name != "mock-generator"),
        ).count()
        payload.append({
            "id": str(experiment.id),
            "name": experiment.name,
            "model_name": experiment.model_name,
            "status": experiment.status,
            "result_count": result_count,
            "created_at": experiment.created_at,
            **experiment_provider_metadata(db, experiment.id),
        })
    return payload

@router.post("/", response_model=ExperimentResponse)
def create_new_experiment(exp_in: ExperimentCreate, db: Session = Depends(get_db)):
    exp = create_experiment(db, exp_in)
    return exp

@router.get("/{exp_id}", response_model=ExperimentResponse)
def read_experiment(exp_id: UUID, db: Session = Depends(get_db)):
    exp = get_experiment(db, exp_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return exp

from backend.services.experiment_manager import experiment_manager
from backend.services.queue_worker import (
    ActivePromptRunError,
    ActiveReanalysisError,
    queue_worker,
)
from backend.schemas.research import ExperimentTrajectoryResponse
from backend.services.research_metrics_service import experiment_trajectory
from backend.services.research_campaign_service import research_schema_available
from backend.models.research_models import ResearchTask

@router.post("/{exp_id}/run")
async def run_experiment(exp_id: UUID, req: RunExperimentRequest, db: Session = Depends(get_db)):
    exp = get_experiment(db, exp_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
        
    prompt = db.query(Prompt).filter(Prompt.id == req.prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    if not settings.GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not configured")
    if settings.IMAGE_PROVIDER == "openai" and not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")
    if settings.IMAGE_PROVIDER == "pollinations" and not settings.POLLINATIONS_API_KEY:
        raise HTTPException(status_code=503, detail="POLLINATIONS_API_KEY is not configured")

    use_mock = False
    
    # Send tasks to queue asynchronously and return immediately
    try:
        await experiment_manager.run_experiment_async(
            db=db,
            experiment_id=exp_id,
            prompt_id=prompt.id,
            prompt_text=prompt.text,
            iterations=req.iterations,
            use_mock=use_mock
        )
    except ActivePromptRunError as exc:
        exp.status = "rejected"
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    
    return {
        "message": f"Successfully queued {req.iterations} iterations for prompt '{prompt.text}'",
        "status": "processing"
    }


@router.get("/{exp_id}/trajectory", response_model=ExperimentTrajectoryResponse)
def read_experiment_trajectory(exp_id: UUID, db: Session = Depends(get_db)):
    exp = get_experiment(db, exp_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiment_trajectory(db, exp_id)


@router.get("/{exp_id}/status")
async def read_experiment_status(exp_id: UUID, db: Session = Depends(get_db)):
    exp = get_experiment(db, exp_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")

    job = await queue_worker.get_job(exp_id)
    if job:
        return job
    interrupted = exp.status in {"running", "processing", "reanalyzing"}
    return {
        "experiment_id": str(exp.id),
        "status": "failed" if interrupted else exp.status,
        "total": 0,
        "completed": 0,
        "succeeded": 0,
        "failed": 0,
        "last_error": None,
        "failure_breakdown": {"generation": 0, "analysis": 0, "worker": 0},
        "events": [],
        "safe_message": (
            "The in-memory task was interrupted. Saved images and the last active analysis revision were preserved."
            if interrupted else None
        ),
        **experiment_provider_metadata(db, exp.id),
    }


@router.post("/{exp_id}/reanalyze")
async def reanalyze_experiment(
    exp_id: UUID,
    req: ReanalyzeExperimentRequest,
    db: Session = Depends(get_db),
):
    experiment = get_experiment(db, exp_id)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if req.provider.strip().lower() != "openai":
        raise HTTPException(status_code=400, detail="Only the 'openai' fallback provider is supported")
    if settings.FALLBACK_VISION_PROVIDER != "openai" or not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OpenAI Vision fallback is not configured")
    if not analysis_history_available(db):
        raise HTTPException(
            status_code=503,
            detail="Analysis revision storage is not installed. Run the additive migration first.",
        )
    current_job = await queue_worker.get_job(exp_id)
    if current_job and current_job.get("status") in {"processing", "reanalyzing"}:
        raise HTTPException(status_code=409, detail="This experiment already has active work")

    results = db.query(Result).filter(
        Result.experiment_id == exp_id,
        or_(Result.model_name.is_(None), Result.model_name != "mock-generator"),
    ).order_by(Result.created_at.asc()).all()
    generated = [result for result in results if is_generated_result(result)]
    analyzable = [result for result in generated if is_local_generated_result(result)]
    if not analyzable:
        raise HTTPException(status_code=409, detail="This experiment has no local generated images to analyze")
    if len(analyzable) != len(generated):
        raise HTTPException(
            status_code=409,
            detail="All generated images must be local PNG, JPEG, or WEBP files for a consistent fallback revision",
        )
    prompt_ids = {result.prompt_id for result in analyzable}
    if len(prompt_ids) != 1:
        raise HTTPException(status_code=409, detail="Experiment results do not have one consistent prompt")

    revision = next_revision(db, exp_id)
    fallback_reason = (current_job or {}).get("fallback_reason") or "gemini_unavailable"
    try:
        await queue_worker.register_reanalysis_job(
            exp_id, next(iter(prompt_ids)), len(analyzable), revision, fallback_reason
        )
    except ActiveReanalysisError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    experiment.status = "reanalyzing"
    db.commit()
    research_result_ids = set()
    if research_schema_available(db):
        research_result_ids = {row[0] for row in db.query(ResearchTask.result_id).filter(
            ResearchTask.result_id.in_([result.id for result in analyzable])
        ).all()}
    for index, result in enumerate(analyzable, start=1):
        await queue_worker.enqueue_task({
            "task_kind": "reanalysis",
            "experiment_id": exp_id,
            "prompt_id": result.prompt_id,
            "result_id": result.id,
            "image_reference": result.image_reference,
            "sample_index": index,
            "provider": "openai",
            "revision": revision,
            "fallback_reason": fallback_reason,
            "research_analysis_v2": result.id in research_result_ids,
        })
    return {
        "experiment_id": str(exp_id),
        "status": "reanalyzing",
        "analysis_provider": "openai",
        "analysis_model": settings.OPENAI_VISION_MODEL,
        "analysis_revision": revision,
        "total": len(analyzable),
        "completed": 0,
        "succeeded": 0,
        "unverified": 0,
    }


@router.get("/{exp_id}/results")
def read_experiment_results(exp_id: UUID, db: Session = Depends(get_db)):
    experiment = get_experiment(db, exp_id)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")
    results = db.query(Result).filter(
        Result.experiment_id == exp_id,
        or_(Result.model_name.is_(None), Result.model_name != "mock-generator"),
    ).order_by(Result.created_at.asc()).all()
    if not results:
        return []
    prompt_id = results[0].prompt_id
    analyses, metadata = effective_analyses(db, prompt_id, exp_id)
    by_result = {analysis.result.id: analysis for analysis in analyses}
    payload = []
    for result in results:
        generated = is_generated_result(result)
        analysis = by_result.get(result.id)
        analysis_status = analysis.status if analysis else "failed" if not generated else "unverified"
        payload.append({
            "result_id": str(result.id),
            "image_reference": result.image_reference if generated else None,
            "generation_status": "success" if generated else "failed",
            "analysis_status": analysis_status,
            "detected_gender": analysis.detected_gender if analysis else None,
            "detected_age_group": analysis.detected_age_group if analysis else None,
            "detected_person_count": analysis.detected_person_count if analysis else 0,
            "analysis_provider": analysis.provider if analysis else metadata.get("analysis_provider"),
            "analysis_model": analysis.model_name if analysis else metadata.get("analysis_model"),
            "quality_assessed": analysis.quality_assessed if analysis else False,
            "quality_status": analysis.error_code if analysis and analysis.quality_assessed else "legacy_not_assessed",
            "exclusion_reason": analysis.safe_error_message if analysis and analysis.status != "success" else None,
            "display_message": (
                None if analysis_status == "success"
                else analysis.safe_error_message if analysis and analysis.safe_error_message
                else "Image generation did not complete." if not generated
                else "The saved image has not been validated."
            ),
            "created_at": result.created_at,
        })
    return payload
