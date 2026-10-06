"""Neon-backed task state for Vercel's request-scoped Python runtime.

The UI already polls the status endpoint sequentially. Each poll safely claims
and completes at most one durable task, so work survives cold starts and no
in-memory background coroutine is required.
"""

import json
import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import or_

from backend.core.config import settings
from backend.core.database import SessionLocal
from backend.models.job_models import ExperimentJob, ExperimentTask
from backend.models.models import Experiment
from backend.services.analysis_revision_service import activate_revision


logger = logging.getLogger(__name__)
ACTIVE_STATUSES = {"processing", "reanalyzing"}


def _json_default(value):
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _as_payload(row: ExperimentJob) -> dict:
    events = json.loads(row.events_json or "[]")
    return {
        "experiment_id": str(row.experiment_id),
        "prompt_id": str(row.prompt_id),
        "job_type": row.job_type,
        "status": row.status,
        "total": row.total,
        "completed": row.completed,
        "generated": row.generated,
        "succeeded": row.succeeded,
        "unverified": row.unverified,
        "failed": row.failed,
        "last_error": row.last_error,
        "fallback_available": bool(
            row.fallback_reason
            and settings.OPENAI_API_KEY
            and settings.FALLBACK_VISION_PROVIDER == "openai"
            and row.generated > 0
        ),
        "fallback_reason": row.fallback_reason,
        "safe_message": row.safe_message,
        "analysis_provider": row.analysis_provider,
        "analysis_model": row.analysis_model,
        "analysis_revision": row.analysis_revision,
        "failure_breakdown": json.loads(row.failure_breakdown_json or "{}"),
        "events": events,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class DurableQueueWorker:
    async def register_job(self, experiment_id, prompt_id, total: int) -> None:
        from backend.services.queue_worker import ActivePromptRunError

        db = SessionLocal()
        try:
            active = db.query(ExperimentJob).filter(
                ExperimentJob.prompt_id == prompt_id,
                ExperimentJob.status.in_(ACTIVE_STATUSES),
            ).first()
            if active:
                raise ActivePromptRunError(
                    "This prompt already has an active experiment. Wait for it to finish."
                )
            db.add(ExperimentJob(
                experiment_id=experiment_id,
                prompt_id=prompt_id,
                job_type="generation",
                status="processing",
                total=total,
                analysis_provider="gemini",
                analysis_model=settings.GEMINI_MODEL,
            ))
            db.commit()
        finally:
            db.close()

    async def register_reanalysis_job(
        self, experiment_id, prompt_id, total: int, revision: int, fallback_reason: str
    ) -> None:
        from backend.services.queue_worker import ActiveReanalysisError

        db = SessionLocal()
        try:
            current = db.query(ExperimentJob).filter(
                ExperimentJob.experiment_id == experiment_id
            ).first()
            if current and current.status in ACTIVE_STATUSES:
                raise ActiveReanalysisError("This experiment already has active work.")
            if current:
                db.delete(current)
                db.flush()
            db.add(ExperimentJob(
                experiment_id=experiment_id,
                prompt_id=prompt_id,
                job_type="reanalysis",
                status="reanalyzing",
                total=total,
                analysis_provider="openai",
                analysis_model=settings.OPENAI_VISION_MODEL,
                analysis_revision=revision,
                fallback_reason=fallback_reason,
            ))
            db.commit()
        finally:
            db.close()

    async def register_research_job(self, experiment_id, prompt_id, total: int, already_completed: int = 0) -> None:
        await self.register_job(experiment_id, prompt_id, total)
        db = SessionLocal()
        try:
            row = db.query(ExperimentJob).filter(ExperimentJob.experiment_id == experiment_id).first()
            if row:
                row.job_type = "research_generation"
                row.completed = min(max(0, already_completed), total)
                db.commit()
        finally:
            db.close()

    async def enqueue_task(self, task_data: dict) -> None:
        kind = task_data.get("task_kind", "generation")
        db = SessionLocal()
        try:
            db.add(ExperimentTask(
                experiment_id=task_data["experiment_id"],
                sample_index=int(task_data.get("sample_index") or 0),
                task_kind=kind,
                payload_json=json.dumps(task_data, default=_json_default),
            ))
            db.commit()
        finally:
            db.close()

    async def get_job(self, experiment_id) -> dict | None:
        db = SessionLocal()
        try:
            row = db.query(ExperimentJob).filter(
                ExperimentJob.experiment_id == experiment_id
            ).first()
            return _as_payload(row) if row else None
        finally:
            db.close()

    async def process_next(self, experiment_id) -> None:
        task_id = self._claim_task(experiment_id)
        if not task_id:
            return
        db = SessionLocal()
        try:
            task = db.query(ExperimentTask).filter(ExperimentTask.id == task_id).first()
            task_data = json.loads(task.payload_json)
            for key in (
                "experiment_id", "prompt_id", "result_id", "research_task_id",
                "campaign_id", "campaign_prompt_id",
            ):
                if task_data.get(key):
                    task_data[key] = UUID(task_data[key])
        finally:
            db.close()

        succeeded = False
        error = None
        failure_type = None
        event = None
        try:
            from backend.services.queue_worker import queue_worker

            if task_data.get("research_task_id"):
                from backend.services.research_campaign_service import mark_task_processing

                task_db = SessionLocal()
                try:
                    mark_task_processing(task_db, task_data["research_task_id"])
                finally:
                    task_db.close()
            if task_data.get("task_kind") == "reanalysis":
                succeeded, error, failure_type, event = await queue_worker._process_reanalysis_task(task_data)
            else:
                succeeded, error, failure_type, event = await queue_worker._process_generation_task(task_data)
        except Exception:
            logger.exception("Durable task failed")
            error = "The queued task could not be completed."
            failure_type = "worker"
            event = {
                "sample_index": task_data.get("sample_index"),
                "status": "unverified" if task_data.get("task_kind") == "reanalysis" else "failed",
                "phase": "worker",
                "reason": error,
                "image_reference": task_data.get("image_reference"),
                "analysis_provider": task_data.get("provider"),
            }
        await self._complete_task(task_id, task_data, succeeded, error, failure_type, event)

    def _claim_task(self, experiment_id):
        db = SessionLocal()
        try:
            stale = datetime.utcnow() - timedelta(minutes=6)
            task = db.query(ExperimentTask).filter(
                ExperimentTask.experiment_id == experiment_id,
                or_(
                    ExperimentTask.status == "pending",
                    (ExperimentTask.status == "processing") & (ExperimentTask.locked_at < stale),
                ),
            ).order_by(ExperimentTask.sample_index.asc()).with_for_update(skip_locked=True).first()
            if not task:
                return None
            task.status = "processing"
            task.locked_at = datetime.utcnow()
            task_id = task.id
            db.commit()
            return task_id
        finally:
            db.close()

    async def _complete_task(self, task_id, task_data, succeeded, error, failure_type, event) -> None:
        db = SessionLocal()
        try:
            task = db.query(ExperimentTask).filter(ExperimentTask.id == task_id).with_for_update().first()
            job = db.query(ExperimentJob).filter(
                ExperimentJob.experiment_id == task_data["experiment_id"]
            ).with_for_update().first()
            if not task or not job or task.status == "completed":
                db.rollback()
                return
            task.status = "completed"
            task.completed_at = datetime.utcnow()
            job.completed += 1
            if event and event.get("image_reference"):
                job.generated += 1
            if succeeded:
                job.succeeded += 1
            elif job.job_type == "reanalysis" or (event and event.get("status") == "unverified"):
                job.unverified += 1
                if job.job_type != "reanalysis":
                    job.failed += 1
            else:
                job.failed += 1
            if error:
                job.last_error = error
            breakdown = json.loads(job.failure_breakdown_json or "{}")
            if not succeeded and failure_type:
                key = failure_type if failure_type in breakdown else "worker"
                breakdown[key] = breakdown.get(key, 0) + 1
            job.failure_breakdown_json = json.dumps(breakdown)
            events = json.loads(job.events_json or "[]")
            if event:
                event["completed_order"] = job.completed
                events.append(event)
                if event.get("fallback_available"):
                    job.fallback_reason = event.get("fallback_reason")
                    job.safe_message = event.get("safe_message")
            job.events_json = json.dumps(events, default=_json_default)
            job.updated_at = datetime.utcnow()
            finished = job.completed >= job.total
            if finished:
                final_status = "completed" if job.job_type == "reanalysis" or job.succeeded else "failed"
                if job.job_type == "reanalysis":
                    activate_revision(
                        db, task_data["experiment_id"], task_data["provider"], task_data["revision"]
                    )
                job.status = final_status
                experiment = db.query(Experiment).filter(
                    Experiment.id == task_data["experiment_id"]
                ).first()
                if experiment:
                    experiment.status = final_status
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Could not persist durable task completion")
            raise
        finally:
            db.close()


durable_queue_worker = DurableQueueWorker()
