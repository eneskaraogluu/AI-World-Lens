import asyncio
import logging
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from backend.core.config import settings
from backend.core.database import SessionLocal
from backend.models.models import Experiment, Result
from backend.services.analysis_revision_service import (
    activate_revision,
    save_analysis_revision,
)
from backend.services.analysis_service import vision_analyzer
from backend.services.mock_generator import MockGenerator
from backend.services.openai_generator import OpenAIImageGenerator
from backend.services.openai_vision_analyzer import openai_vision_analyzer
from backend.services.pollinations_generator import PollinationsGenerator
from backend.services.result_service import save_result
from backend.services.vision_base import (
    VisionAnalysisOutcome,
    VisionError,
    demographic_quality_decision,
)


logger = logging.getLogger(__name__)

COMPOSITION_RETRY_CODES = {
    "head_cropped",
    "face_cropped",
    "face_blurred",
    "face_not_visible",
    "incomplete_framing",
}
DEFAULT_COMPOSITION_RETRY_LIMIT = 1


class ActivePromptRunError(RuntimeError):
    pass


class ActiveReanalysisError(RuntimeError):
    pass


class QueueWorker:
    def __init__(self):
        self.queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self.workers: list[asyncio.Task] = []
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._jobs_lock = asyncio.Lock()
        self._generator_instances = {
            "openai-image": OpenAIImageGenerator(),
            "pollinations-flux": PollinationsGenerator(),
            "mock-generator": MockGenerator(),
        }

    def start_workers(self, num_workers: int = 2) -> None:
        if settings.SERVERLESS_MODE:
            logger.info("Serverless mode: durable Neon task ledger is active")
            return
        if any(not task.done() for task in self.workers):
            return
        safe_workers = min(2, max(1, num_workers))
        self.workers = [
            asyncio.create_task(self._worker(f"Worker-{index + 1}"))
            for index in range(safe_workers)
        ]
        logger.info("Started %s queue workers", safe_workers)

    async def stop_workers(self) -> None:
        if settings.SERVERLESS_MODE:
            return
        for task in self.workers:
            task.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()

    async def register_job(self, experiment_id, prompt_id, total: int) -> None:
        if settings.SERVERLESS_MODE:
            from backend.services.durable_queue_worker import durable_queue_worker

            return await durable_queue_worker.register_job(experiment_id, prompt_id, total)
        experiment_key = str(experiment_id)
        prompt_key = str(prompt_id)
        async with self._jobs_lock:
            active = next((
                job for job in self._jobs.values()
                if job["prompt_id"] == prompt_key
                and job["status"] in {"processing", "reanalyzing"}
            ), None)
            if active:
                raise ActivePromptRunError(
                    "This prompt already has an active experiment. Wait for it to finish."
                )
            self._jobs[experiment_key] = self._new_job(
                experiment_key, prompt_key, total, "generation", "processing"
            )

    async def register_research_job(
        self, experiment_id, prompt_id, total: int, already_completed: int = 0
    ) -> None:
        """Idempotently register a persistent campaign prompt queue job.

        ResearchTask is the source of truth.  This in-memory mirror exists only
        so the legacy experiment status endpoint remains useful.
        """
        if settings.SERVERLESS_MODE:
            from backend.services.durable_queue_worker import durable_queue_worker

            return await durable_queue_worker.register_research_job(
                experiment_id, prompt_id, total, already_completed
            )
        experiment_key = str(experiment_id)
        async with self._jobs_lock:
            current = self._jobs.get(experiment_key)
            if current and current["status"] in {"processing", "reanalyzing"}:
                return
            job = self._new_job(
                experiment_key, str(prompt_id), total, "research_generation", "processing"
            )
            job["completed"] = min(max(0, already_completed), total)
            self._jobs[experiment_key] = job

    async def register_reanalysis_job(
        self,
        experiment_id,
        prompt_id,
        total: int,
        revision: int,
        fallback_reason: str,
    ) -> None:
        if settings.SERVERLESS_MODE:
            from backend.services.durable_queue_worker import durable_queue_worker

            return await durable_queue_worker.register_reanalysis_job(
                experiment_id, prompt_id, total, revision, fallback_reason
            )
        experiment_key = str(experiment_id)
        async with self._jobs_lock:
            current = self._jobs.get(experiment_key)
            if current and current["status"] in {"processing", "reanalyzing"}:
                raise ActiveReanalysisError("This experiment already has active work.")
            job = self._new_job(
                experiment_key, str(prompt_id), total, "reanalysis", "reanalyzing"
            )
            job.update({
                "analysis_provider": "openai",
                "analysis_model": settings.OPENAI_VISION_MODEL,
                "analysis_revision": revision,
                "fallback_reason": fallback_reason,
                "fallback_available": False,
            })
            self._jobs[experiment_key] = job

    @staticmethod
    def _new_job(experiment_id, prompt_id, total, job_type, status):
        now = datetime.now(timezone.utc).isoformat()
        return {
            "experiment_id": experiment_id,
            "prompt_id": prompt_id,
            "job_type": job_type,
            "status": status,
            "total": total,
            "completed": 0,
            "generated": 0,
            "succeeded": 0,
            "unverified": 0,
            "failed": 0,
            "last_error": None,
            "fallback_available": False,
            "fallback_reason": None,
            "safe_message": None,
            "analysis_provider": "gemini",
            "analysis_model": settings.GEMINI_MODEL,
            "analysis_revision": 1,
            "failure_breakdown": {"generation": 0, "analysis": 0, "worker": 0},
            "events": [],
            "started_at": now,
            "updated_at": now,
        }

    async def get_job(self, experiment_id) -> Dict[str, Any] | None:
        if settings.SERVERLESS_MODE:
            from backend.services.durable_queue_worker import durable_queue_worker

            return await durable_queue_worker.get_job(experiment_id)
        async with self._jobs_lock:
            job = self._jobs.get(str(experiment_id))
            if not job:
                return None
            return {
                **job,
                "events": [dict(event) for event in job.get("events", [])],
                "failure_breakdown": dict(job.get("failure_breakdown", {})),
            }

    async def enqueue_task(self, task_data: Dict[str, Any]) -> None:
        if settings.SERVERLESS_MODE:
            from backend.services.durable_queue_worker import durable_queue_worker

            return await durable_queue_worker.enqueue_task(task_data)
        await self.queue.put(task_data)

    async def _complete_task(
        self,
        task_data: Dict[str, Any],
        succeeded: bool,
        error: str | None,
        failure_type: str | None = None,
        event: Dict[str, Any] | None = None,
    ) -> None:
        experiment_id = task_data["experiment_id"]
        finished = False
        job_type = "generation"
        final_status = "completed"
        async with self._jobs_lock:
            job = self._jobs.get(str(experiment_id))
            if not job:
                return
            job_type = job.get("job_type", "generation")
            job["completed"] += 1
            if event and event.get("image_reference"):
                job["generated"] += 1
            if succeeded:
                job["succeeded"] += 1
            elif job_type == "reanalysis" or (event and event.get("status") == "unverified"):
                job["unverified"] += 1
                if job_type != "reanalysis":
                    job["failed"] += 1
            else:
                job["failed"] += 1
            if error:
                job["last_error"] = error
            if not succeeded and failure_type:
                breakdown = job["failure_breakdown"]
                breakdown[failure_type if failure_type in breakdown else "worker"] += 1
            if event:
                event["completed_order"] = job["completed"]
                job["events"].append(event)
                if event.get("fallback_available"):
                    reference = (event.get("image_reference") or "").lower()
                    local_image = (
                        not reference.startswith(("http://", "https://"))
                        and reference.endswith((".png", ".jpg", ".jpeg", ".webp"))
                    ) or reference.startswith("blob:")
                    job["fallback_available"] = bool(
                        settings.OPENAI_API_KEY
                        and settings.FALLBACK_VISION_PROVIDER == "openai"
                        and job["generated"] > 0
                        and local_image
                    )
                    job["fallback_reason"] = event.get("fallback_reason")
                    job["safe_message"] = event.get("safe_message")
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            if job["completed"] >= job["total"]:
                if job_type == "reanalysis":
                    # Keep the public job in progress until the staged
                    # revision has actually been activated below.
                    final_status = "completed"
                else:
                    job["status"] = "completed" if job["succeeded"] else "failed"
                    final_status = job["status"]
                finished = True

        if not finished:
            return
        db = SessionLocal()
        try:
            if job_type == "reanalysis":
                activate_revision(
                    db,
                    experiment_id,
                    task_data["provider"],
                    task_data["revision"],
                )
                if task_data.get("research_analysis_v2"):
                    from backend.services.research_analysis_service import activate_research_revision

                    activate_research_revision(
                        db, experiment_id, task_data["provider"], task_data["revision"]
                    )
            experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
            if experiment:
                experiment.status = final_status
                db.commit()
            if job_type == "reanalysis":
                async with self._jobs_lock:
                    job = self._jobs.get(str(experiment_id))
                    if job:
                        job["status"] = final_status
                        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            db.rollback()
            logger.exception("Could not finalize experiment analysis revision")
            async with self._jobs_lock:
                job = self._jobs.get(str(experiment_id))
                if job:
                    job["status"] = "failed"
                    job["last_error"] = "The analysis revision could not be activated."
                    job["safe_message"] = "The re-analysis finished but could not be activated safely."
        finally:
            db.close()

    async def _worker(self, name: str) -> None:
        while True:
            task_data = await self.queue.get()
            succeeded = False
            error = None
            failure_type = None
            event = None
            try:
                if task_data.get("research_task_id"):
                    from backend.services.research_campaign_service import mark_task_processing

                    task_db = SessionLocal()
                    try:
                        mark_task_processing(task_db, task_data["research_task_id"])
                    finally:
                        task_db.close()
                if task_data.get("task_kind") == "reanalysis":
                    succeeded, error, failure_type, event = await self._process_reanalysis_task(task_data)
                else:
                    succeeded, error, failure_type, event = await self._process_generation_task(task_data)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
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
                logger.exception("[%s] Task failed: %s", name, exc)
            finally:
                await self._complete_task(
                    task_data, succeeded, error, failure_type, event
                )
                self.queue.task_done()
                if task_data.get("campaign_id"):
                    from backend.services.research_campaign_service import dispatch_available

                    await dispatch_available(
                        task_data["campaign_id"],
                        use_mock=task_data.get("generator_type") == "mock-generator",
                    )

    async def _process_generation_task(
        self, task_data: Dict[str, Any]
    ) -> Tuple[bool, str | None, str | None, Dict[str, Any]]:
        prompt_text = task_data["prompt_text"]
        prompt_id = task_data["prompt_id"]
        experiment_id = task_data["experiment_id"]
        generator_type = task_data["generator_type"]
        seed = task_data["seed"]
        generator = self._generator_instances[generator_type]
        is_research = task_data.get("task_kind") == "research_generation"
        retry_limit = (
            max(0, min(1, int(task_data.get("quality_retry_limit", DEFAULT_COMPOSITION_RETRY_LIMIT))))
            if generator_type == "openai-image" and not is_research else 0
        )
        retry_count = 0
        generation_duration = 0.0
        analysis_duration_total = 0
        generation_error = None
        image_ref = None
        outcome = VisionAnalysisOutcome({}, 0)
        while True:
            attempt_prompt = self._composition_retry_prompt(prompt_text, retry_count) if retry_count else prompt_text
            image_ref, attempt_generation_duration, generation_error = await generator.generate_image(
                attempt_prompt, seed
            )
            generation_duration += attempt_generation_duration

            if generator_type == "mock-generator" and is_research:
                analysis, analysis_duration, _ = self._mock_research_analysis(
                    task_data.get("expected_person_policy", "zero_or_more")
                )
                outcome = VisionAnalysisOutcome(analysis, analysis_duration)
            elif generator_type == "mock-generator":
                analysis, analysis_duration, _ = self._mock_analysis(prompt_text)
                outcome = VisionAnalysisOutcome(analysis, analysis_duration)
            elif image_ref and not generation_error:
                if is_research:
                    from backend.services.research_vision_service import gemini_research_analyzer

                    outcome = await gemini_research_analyzer.analyze_image(image_ref)
                else:
                    outcome = await vision_analyzer.analyze_image(image_ref)
            else:
                outcome = VisionAnalysisOutcome({}, 0)
            analysis_duration_total += outcome.duration_ms

            attempt_quality_ok, attempt_quality_code, _ = demographic_quality_decision(outcome.data)
            should_replace = (
                retry_count < retry_limit
                and not generation_error
                and outcome.succeeded
                and not attempt_quality_ok
                and attempt_quality_code in COMPOSITION_RETRY_CODES
            )
            if not should_replace:
                break
            retry_count += 1
            logger.info(
                "Replacing sample %s after composition gate: %s",
                task_data.get("sample_index"), attempt_quality_code,
            )

        quality_gate_applies = not is_research and generator_type != "mock-generator"
        quality_ok, quality_code, quality_message = demographic_quality_decision(outcome.data)
        analysis_error = outcome.error.safe_message if outcome.error else None
        error = generation_error or analysis_error or (quality_message if quality_gate_applies and outcome.succeeded else None)
        if generator_type == "mock-generator":
            analysis_status = "success"
        elif generation_error:
            analysis_status = "failed"
        else:
            analysis_status = "success" if outcome.succeeded and (quality_ok or not quality_gate_applies) else "unverified"
        result_data = {
            "generation_id": f"gen-{uuid.uuid4()}",
            "image_reference": image_ref or "error",
            "detected_age_group": outcome.data.get("detected_age_group", "Unclear"),
            "detected_gender": outcome.data.get("detected_gender", "Unclear"),
            "detected_person_count": outcome.data.get("detected_person_count", 0),
            "model_name": generator.model_name,
            "model_version": generator.model_version,
            "seed": None if generator_type == "openai-image" else seed,
            "generation_duration": generation_duration,
            "analysis_duration": analysis_duration_total,
            "error_message": error,
            "analysis_status": analysis_status,
        }
        db = SessionLocal()
        try:
            result = save_result(db, experiment_id, prompt_id, result_data)
            # Later helper calls commit the session. SQLAlchemy expires ORM
            # attributes on commit, so keep the scalar id before the session
            # is closed instead of reading from a detached Result instance.
            result_id = result.id
            if is_research:
                from backend.services.research_analysis_service import (
                    AnalysisV2Payload,
                    apply_scene_policy_flags,
                    save_research_analysis,
                )
                from backend.services.research_campaign_service import finish_research_task

                payload = None
                if outcome.succeeded:
                    try:
                        payload = apply_scene_policy_flags(
                            AnalysisV2Payload.model_validate(outcome.data),
                            task_data.get("expected_person_policy", "zero_or_more"),
                        )
                    except Exception:
                        outcome = VisionAnalysisOutcome({}, outcome.duration_ms)
                        analysis_status = "unverified"
                        error = "The vision provider returned invalid Analysis V2 data."
                if image_ref and not generation_error:
                    save_research_analysis(
                        db,
                        result_id=result_id,
                        provider="mock" if generator_type == "mock-generator" else "gemini",
                        model_name="mock" if generator_type == "mock-generator" else settings.GEMINI_MODEL,
                        revision=1,
                        payload=payload,
                        error_code=outcome.error.error_code if outcome.error else ("invalid_response" if not payload else None),
                        safe_error_message=outcome.error.safe_message if outcome.error else (error if not payload else None),
                    )
                task_status = "failed" if generation_error else "validated" if payload else "unverified"
                finish_research_task(
                    db,
                    task_data["research_task_id"],
                    result_id,
                    task_status,
                    error_code=outcome.error.error_code if outcome.error else None,
                    safe_error_message=error,
                )
            elif generator_type != "mock-generator" and image_ref and not generation_error:
                save_analysis_revision(
                    db,
                    result_id,
                    vision_analyzer.provider_name,
                    vision_analyzer.model_name,
                    1,
                    outcome,
                    is_active=True,
                )
        finally:
            db.close()

        failure_type = "generation" if generation_error else "analysis" if analysis_status != "success" else None
        event_status = "success" if analysis_status == "success" else "unverified" if image_ref and not generation_error else "failed"
        fallback_available = bool(outcome.error and outcome.error.fallback_available)
        event = {
            "sample_index": task_data.get("sample_index"),
            "status": event_status,
            "phase": "complete" if event_status == "success" else failure_type,
            "reason": (
                "Image generated and vision analysis validated."
                if event_status == "success"
                else self._friendly_failure_reason(failure_type, error)
            ),
            "safe_message": outcome.error.safe_message if outcome.error else quality_message if quality_gate_applies else None,
            "error_code": outcome.error.error_code if outcome.error else quality_code if quality_gate_applies else None,
            "fallback_available": fallback_available,
            "fallback_reason": (
                f"gemini_{outcome.error.error_code}" if fallback_available else None
            ),
            "image_reference": image_ref,
            "detected_person_count": outcome.data.get("detected_person_count", 0),
            "detected_gender": outcome.data.get("detected_gender"),
            "detected_age_group": outcome.data.get("detected_age_group"),
            "analysis_provider": "gemini" if generator_type != "mock-generator" else "mock",
            "analysis_model": vision_analyzer.model_name if generator_type != "mock-generator" else "mock",
            "quality_assessed": quality_gate_applies and outcome.succeeded,
            "quality_status": quality_code if quality_gate_applies and outcome.succeeded else None,
            "quality_flags": outcome.data.get("quality_flags", []),
            "composition_retry_count": retry_count,
            "result_id": str(result_id),
        }
        return analysis_status == "success", error, failure_type, event

    @staticmethod
    def _composition_retry_prompt(prompt_text: str, retry_count: int) -> str:
        return (
            f"{prompt_text}. Composition correction attempt {retry_count}: "
            "center the single person in the frame, pull the camera farther back, "
            "show the complete head with clear space above the hair, keep both sides "
            "of the body inside the image, and render the face sharply without blur"
        )

    async def _process_reanalysis_task(
        self, task_data: Dict[str, Any]
    ) -> Tuple[bool, str | None, str | None, Dict[str, Any]]:
        if task_data.get("research_analysis_v2"):
            from backend.services.research_vision_service import openai_research_analyzer

            outcome = await openai_research_analyzer.analyze_image(task_data["image_reference"])
        else:
            outcome = await openai_vision_analyzer.analyze_image(task_data["image_reference"])
        db = SessionLocal()
        try:
            compatibility_outcome = outcome
            research_payload = None
            if task_data.get("research_analysis_v2"):
                from backend.models.research_models import ResearchTask
                from backend.services.research_analysis_service import (
                    AnalysisV2Payload,
                    apply_scene_policy_flags,
                    save_research_analysis,
                    v1_projection,
                )

                try:
                    research_payload = AnalysisV2Payload.model_validate(outcome.data) if outcome.succeeded else None
                    research_task = db.query(ResearchTask).filter(
                        ResearchTask.result_id == task_data["result_id"]
                    ).first()
                    if research_payload and research_task:
                        research_payload = apply_scene_policy_flags(
                            research_payload,
                            research_task.campaign_prompt.definition.expected_person_policy,
                        )
                except Exception:
                    outcome = VisionAnalysisOutcome({}, outcome.duration_ms, VisionError(
                        "invalid_response", "OpenAI Vision returned invalid Analysis V2 data.", False
                    ))
                    research_payload = None
                save_research_analysis(
                    db,
                    result_id=task_data["result_id"],
                    provider="openai",
                    model_name=openai_research_analyzer.model_name,
                    revision=task_data["revision"],
                    payload=research_payload,
                    error_code=outcome.error.error_code if outcome.error else None,
                    safe_error_message=outcome.error.safe_message if outcome.error else None,
                    is_active=False,
                )
                projection = v1_projection(research_payload) if research_payload else None
                compatibility_outcome = VisionAnalysisOutcome(
                    projection or {
                        "detected_person_count": research_payload.detected_person_count if research_payload else 0,
                        "detected_gender": "Unclear",
                        "detected_age_group": "Unclear",
                    },
                    outcome.duration_ms,
                    outcome.error,
                )
            save_analysis_revision(
                db,
                task_data["result_id"],
                "openai",
                openai_vision_analyzer.model_name,
                task_data["revision"],
                compatibility_outcome,
                is_active=False,
                fallback_reason=task_data.get("fallback_reason"),
                enforce_quality=not task_data.get("research_analysis_v2"),
            )
        finally:
            db.close()
        quality_gate_applies = not task_data.get("research_analysis_v2")
        quality_ok, quality_code, quality_message = demographic_quality_decision(compatibility_outcome.data)
        accepted = outcome.succeeded and (quality_ok or not quality_gate_applies)
        error = outcome.error.safe_message if outcome.error else quality_message if quality_gate_applies else None
        event = {
            "sample_index": task_data.get("sample_index"),
            "status": "success" if accepted else "unverified",
            "phase": "complete" if accepted else "analysis",
            "reason": (
                "Image revalidated with OpenAI Vision."
                if accepted else error
            ),
            "safe_message": outcome.error.safe_message if outcome.error else quality_message if quality_gate_applies else None,
            "error_code": outcome.error.error_code if outcome.error else quality_code if quality_gate_applies else None,
            "image_reference": task_data["image_reference"],
            "detected_person_count": compatibility_outcome.data.get("detected_person_count", 0),
            "detected_gender": compatibility_outcome.data.get("detected_gender"),
            "detected_age_group": compatibility_outcome.data.get("detected_age_group"),
            "analysis_provider": "openai",
            "analysis_model": openai_vision_analyzer.model_name,
            "quality_assessed": quality_gate_applies and outcome.succeeded,
            "quality_status": quality_code if quality_gate_applies and outcome.succeeded else None,
            "quality_flags": compatibility_outcome.data.get("quality_flags", []),
        }
        return accepted, error, "analysis" if error else None, event

    @staticmethod
    def _friendly_failure_reason(failure_type: str | None, error: str | None) -> str:
        normalized = (error or "").lower()
        if normalized.startswith("excluded —"):
            return error
        if "quota" in normalized or "rate" in normalized or "429" in normalized:
            return "The vision provider quota is currently unavailable for this sample."
        if "timeout" in normalized or "timed out" in normalized:
            return "The provider did not respond within the allowed time."
        if "safety" in normalized or "policy" in normalized or "blocked" in normalized:
            return "The provider safety filter did not return an image."
        if failure_type == "generation":
            return "Image generation did not return a valid image."
        if failure_type == "analysis":
            return "The image was created, but vision analysis could not be completed."
        return "The sample task could not be completed."

    def _mock_analysis(self, prompt_text: str) -> Tuple[Dict[str, Any], int, None]:
        start = time.monotonic()
        return {
            "detected_age_group": random.choice(["18-24", "25-34", "35-44"]),
            "detected_gender": random.choice(["Male", "Female"]),
            "detected_person_count": 1,
        }, int((time.monotonic() - start) * 1000), None

    def _mock_research_analysis(self, expected_person_policy: str) -> Tuple[Dict[str, Any], int, None]:
        start = time.monotonic()
        count = 1 if expected_person_policy in {"exactly_one", "one_or_more"} else 2 if expected_person_policy == "group_expected" else 0
        persons = [{
            "person_index": index,
            "is_primary": index == 1,
            "visible_gender_presentation": "Female" if index % 2 else "Male",
            "estimated_age_group": "35-44",
        } for index in range(1, count + 1)]
        return {
            "analysis_schema_version": "2.0",
            "detected_person_count": count,
            "persons": persons,
            "scene": {
                "setting_type": "Other",
                "indoor_outdoor": "Unclear",
                "urbanicity": "Unclear",
                "environment_condition": "Unclear",
                "technology_presence": "Unclear",
                "vehicle_presence": "Unclear",
                "attire_formality": "Unclear",
            },
            "occupation_alignment": "NotApplicable" if count == 0 else "Aligned",
            "quality_flags": [],
            "notes": None,
        }, int((time.monotonic() - start) * 1000), None


queue_worker = QueueWorker()
