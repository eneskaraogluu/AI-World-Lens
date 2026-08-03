import asyncio
import json
import os
import sys
import types
from uuid import uuid4

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["OPENAI_API_KEY"] = "test-only-placeholder"

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api import routes_comparison, routes_experiment
from backend.core.config import settings
from backend.models.base import Base
from backend.models.models import Category, Experiment, Prompt, Result, ResultAnalysis
from backend.schemas.run import ReanalyzeExperimentRequest
from backend.services.analysis_revision_service import (
    effective_analyses,
    save_analysis_revision,
)
from backend.services.comparison_service import get_comparison
from backend.services.queue_worker import QueueWorker
from backend.services.openai_vision_analyzer import OpenAIVisionAnalyzer
from backend.services.vision_base import (
    DemographicAnalysis,
    VisionAnalysisOutcome,
    VisionError,
    classify_provider_error,
)
import backend.services.queue_worker as queue_module
import backend.services.openai_vision_analyzer as openai_vision_module


class FakeGenerator:
    model_name = "fake-image-generator"
    model_version = "test"

    def __init__(self):
        self.calls = 0

    async def generate_image(self, prompt_text, seed):
        self.calls += 1
        return f"preserved-{self.calls}.png", 1, None


class FakeAnalyzer:
    def __init__(self, provider_name, model_name, outcomes):
        self.provider_name = provider_name
        self.model_name = model_name
        self.outcomes = list(outcomes)
        self.calls = 0

    async def analyze_image(self, image_reference):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        return outcome


def success(gender="Female", age="25-34"):
    return VisionAnalysisOutcome({
        "detected_age_group": age,
        "detected_gender": gender,
        "detected_person_count": 1,
        "framing_status": "complete",
        "face_visibility": "clear",
        "demographic_codable": True,
        "quality_flags": [],
    }, 4)


def quota_error():
    return VisionAnalysisOutcome({}, 4, VisionError(
        "quota_exhausted",
        "Gemini Vision quota is currently unavailable.",
        True,
        True,
    ))


def openai_error():
    return VisionAnalysisOutcome({}, 4, VisionError(
        "provider_unavailable",
        "OpenAI Vision is temporarily unavailable.",
        True,
        False,
    ))


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, factory, factory()


def seed_scope(db, label="experiment"):
    category = Category(id=uuid4(), name="Occupations")
    prompt = Prompt(id=uuid4(), category=category, text="A CEO")
    experiment = Experiment(id=uuid4(), name=label, model_name="test", status="running")
    db.add_all([category, prompt, experiment])
    db.commit()
    return prompt, experiment


async def run_generation_case(outcomes):
    engine, factory, db = make_db()
    prompt, experiment = seed_scope(db)
    worker = QueueWorker()
    worker._generator_instances["openai-image"] = FakeGenerator()
    analyzer = FakeAnalyzer("gemini", "gemini-test", outcomes)
    original_analyzer = queue_module.vision_analyzer
    original_factory = queue_module.SessionLocal
    queue_module.vision_analyzer = analyzer
    queue_module.SessionLocal = factory
    try:
        await worker.register_job(experiment.id, prompt.id, len(outcomes))
        for index in range(len(outcomes)):
            task = {
                "prompt_id": prompt.id,
                "prompt_text": prompt.text,
                "experiment_id": experiment.id,
                "generator_type": "openai-image",
                "seed": None,
                "sample_index": index + 1,
            }
            succeeded, error, failure_type, event = await worker._process_generation_task(task)
            await worker._complete_task(task, succeeded, error, failure_type, event)
        return engine, factory, db, prompt, experiment, worker, analyzer
    finally:
        queue_module.vision_analyzer = original_analyzer
        queue_module.SessionLocal = original_factory


async def run_checks():
    settings.OPENAI_API_KEY = "test-only-placeholder"
    settings.FALLBACK_VISION_PROVIDER = "openai"

    # OpenAI Vision uses a real image data URL and Pydantic structured output,
    # while this test substitutes the SDK client and performs no network call.
    captured = {}

    class FakeCompletions:
        def parse(self, **kwargs):
            captured.update(kwargs)
            message = types.SimpleNamespace(
                parsed=DemographicAnalysis(
                    detected_age_group="35-44",
                    detected_gender="Female",
                    detected_person_count=1,
                    framing_status="complete",
                    face_visibility="clear",
                    demographic_codable=True,
                    quality_flags=[],
                ),
                refusal=None,
            )
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    class FakeOpenAIClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = types.SimpleNamespace(completions=FakeCompletions())

    original_openai_module = sys.modules.get("openai")
    original_loader = openai_vision_module.load_image_bytes
    sys.modules["openai"] = types.SimpleNamespace(OpenAI=FakeOpenAIClient)

    async def fake_image_loader(_):
        return b"\x89PNG\r\n\x1a\n" + b"test-image-bytes"

    openai_vision_module.load_image_bytes = fake_image_loader
    try:
        analyzer_under_test = OpenAIVisionAnalyzer()
        outcome = await analyzer_under_test.analyze_image("local-test.png")
        assert outcome.succeeded
        image_part = captured["messages"][0]["content"][1]["image_url"]
        assert image_part["url"].startswith("data:image/png;base64,")
        assert image_part["detail"] == "low"
        assert captured["response_format"] is DemographicAnalysis
        assert captured["temperature"] == 0
    finally:
        openai_vision_module.load_image_bytes = original_loader
        if original_openai_module is None:
            sys.modules.pop("openai", None)
        else:
            sys.modules["openai"] = original_openai_module

    assert classify_provider_error(RuntimeError("429 RESOURCE_EXHAUSTED quota"), "gemini").fallback_available
    assert classify_provider_error(ValueError("unsupported image"), "gemini").error_code == "image_error"

    # 1. Normal Gemini analysis remains the primary, single-provider revision.
    _, _, db, prompt, experiment, worker, analyzer = await run_generation_case([success(), success("Male")])
    job = await worker.get_job(experiment.id)
    assert job["succeeded"] == 2 and not job["fallback_available"]
    analyses, metadata = effective_analyses(db, prompt.id, experiment.id)
    assert {item.provider for item in analyses} == {"gemini"}
    assert metadata["analysis_revision"] == 1
    db.close()

    # 2-5. A first-sample quota error preserves the image and only offers fallback.
    _, _, db, prompt, experiment, worker, analyzer = await run_generation_case([quota_error(), success()])
    job = await worker.get_job(experiment.id)
    saved_refs = [row[0] for row in db.query(Result.image_reference).order_by(Result.created_at).all()]
    assert saved_refs == ["preserved-1.png", "preserved-2.png"]
    assert job["fallback_available"] is True
    assert job["fallback_reason"] == "gemini_quota_exhausted"
    assert worker.queue.empty(), "Fallback must not start silently"
    assert db.query(ResultAnalysis).filter(ResultAnalysis.provider == "openai").count() == 0
    db.close()

    # 3. A quota failure after prior successes still keeps one active Gemini revision.
    _, _, db, prompt, experiment, worker, analyzer = await run_generation_case([success(), success("Male"), quota_error()])
    analyses, metadata = effective_analyses(db, prompt.id, experiment.id)
    assert len(analyses) == 3
    assert {item.provider for item in analyses} == {"gemini"}
    assert sum(item.status == "success" for item in analyses) == 2
    db.close()

    # 6-11. Explicit OpenAI re-analysis queues generated images only and switches atomically.
    engine, factory, db = make_db()
    prompt, experiment = seed_scope(db, "fallback")
    generated = []
    for index in range(3):
        row = Result(
            experiment_id=experiment.id,
            prompt_id=prompt.id,
            generation_id=f"generated-{index}",
            image_reference=f"saved-{index}.png",
            model_name="gpt-image-test",
            analysis_status="success",
        )
        db.add(row)
        db.commit()
        generated.append(row)
        save_analysis_revision(db, row.id, "gemini", "gemini-test", 1, success(), is_active=True)
    db.add(Result(
        experiment_id=experiment.id,
        prompt_id=prompt.id,
        generation_id="generation-failed",
        image_reference="error",
        model_name="gpt-image-test",
        analysis_status="failed",
    ))
    db.commit()

    reanalysis_worker = QueueWorker()
    original_route_worker = routes_experiment.queue_worker
    original_factory = queue_module.SessionLocal
    original_openai = queue_module.openai_vision_analyzer
    routes_experiment.queue_worker = reanalysis_worker
    queue_module.SessionLocal = factory
    fake_openai = FakeAnalyzer("openai", "gpt-4o-mini-test", [success("Male"), success(), openai_error()])
    queue_module.openai_vision_analyzer = fake_openai
    try:
        response = await routes_experiment.reanalyze_experiment(
            experiment.id, ReanalyzeExperimentRequest(provider="openai"), db
        )
        assert response["status"] == "reanalyzing" and response["total"] == 3
        assert reanalysis_worker.queue.qsize() == 3
        try:
            await routes_experiment.reanalyze_experiment(
                experiment.id, ReanalyzeExperimentRequest(provider="openai"), db
            )
            raise AssertionError("Duplicate re-analysis should return 409")
        except HTTPException as exc:
            assert exc.status_code == 409

        while not reanalysis_worker.queue.empty():
            task = await reanalysis_worker.queue.get()
            succeeded, error, failure_type, event = await reanalysis_worker._process_reanalysis_task(task)
            await reanalysis_worker._complete_task(task, succeeded, error, failure_type, event)
            reanalysis_worker.queue.task_done()

        analyses, metadata = effective_analyses(db, prompt.id, experiment.id)
        assert len(analyses) == 3
        assert {item.provider for item in analyses} == {"openai"}
        assert metadata["analysis_revision"] == 2
        assert sum(item.status == "success" for item in analyses) == 2
        assert sum(item.status == "unverified" for item in analyses) == 1
        assert db.query(ResultAnalysis).filter(
            ResultAnalysis.provider == "gemini", ResultAnalysis.is_active.is_(True)
        ).count() == 0
        assert db.query(ResultAnalysis).filter(
            ResultAnalysis.provider == "openai", ResultAnalysis.is_active.is_(True)
        ).count() == 3
        assert db.query(Result).filter(Result.image_reference == "error").count() == 1
    finally:
        routes_experiment.queue_worker = original_route_worker
        queue_module.SessionLocal = original_factory
        queue_module.openai_vision_analyzer = original_openai

    # 12-13, 19. Comparisons are experiment-scoped and contain finite, honest values.
    comparison = get_comparison(db, prompt.id, experiment.id)
    assert comparison["validated_samples"] == 2
    assert comparison["unverified_samples"] == 1
    assert comparison["failed_samples"] == 1
    assert comparison["analysis_provider"] == "openai"
    json.dumps(comparison, allow_nan=False, default=str)
    api_comparison = routes_comparison.read_experiment_comparison(experiment.id, db)
    assert api_comparison["experiment_id"] == experiment.id
    safe_results = routes_experiment.read_experiment_results(experiment.id, db)
    assert len(safe_results) == 4
    assert all("error_message" not in item and "safe_error_message" not in item for item in safe_results)
    listed = routes_experiment.list_experiments(prompt.id, db)
    assert any(item["id"] == str(experiment.id) for item in listed)
    second = Experiment(id=uuid4(), name="separate", model_name="test", status="completed")
    db.add(second)
    db.add(Result(
        experiment_id=second.id,
        prompt_id=prompt.id,
        generation_id="separate-result",
        image_reference="separate.png",
        model_name="gpt-image-test",
        analysis_status="success",
        detected_gender="Female",
        detected_age_group="55+",
        detected_person_count=1,
    ))
    db.commit()
    separate = get_comparison(db, prompt.id, second.id)
    assert separate["total_generations"] == 1
    assert comparison["total_generations"] == 2

    # 18. Health reports configuration metadata but never key values.
    from backend.main import health
    health_payload = health()
    assert health_payload["fallback_vision_provider"] == "openai"
    assert health_payload["fallback_vision_model"]
    assert "test-only-placeholder" not in json.dumps(health_payload)

    # 20. A legacy Result without ResultAnalysis remains readable.
    legacy_effective, legacy_metadata = effective_analyses(db, prompt.id, second.id)
    assert len(legacy_effective) == 1
    assert legacy_effective[0].status == "success"
    assert legacy_metadata["analysis_provider"] == "gemini"

    # Mock records never enter production comparisons.
    mock_experiment = Experiment(id=uuid4(), name="mock", model_name="mock", status="completed")
    db.add(mock_experiment)
    db.add(Result(
        experiment_id=mock_experiment.id,
        prompt_id=prompt.id,
        generation_id="mock",
        image_reference="mock_no_image_saved",
        model_name="mock-generator",
        analysis_status="success",
        detected_gender="Male",
        detected_age_group="25-34",
        detected_person_count=1,
    ))
    db.commit()
    assert get_comparison(db, prompt.id, mock_experiment.id)["total_generations"] == 0
    db.close()


if __name__ == "__main__":
    asyncio.run(run_checks())
    print("VISION FAILOVER: PASS")
