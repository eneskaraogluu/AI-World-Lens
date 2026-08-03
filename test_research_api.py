"""HTTP-level research API checks on a temporary SQLite file."""

import os
import tempfile
from pathlib import Path


os.environ["PYTHON_DOTENV_DISABLED"] = "1"
temp_dir = tempfile.TemporaryDirectory()
db_path = (Path(temp_dir.name) / "research-api.sqlite").as_posix()
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)

from fastapi.testclient import TestClient

from backend.core.database import SessionLocal, engine
from backend.main import app
from backend.models.base import Base
from backend.services.research_prompt_service import seed_prompt_catalogue


Base.metadata.create_all(engine)
db = SessionLocal(); seed_prompt_catalogue(db); db.close()

with TestClient(app) as client:
    health = client.get("/api/health")
    assert health.status_code == 200 and health.json()["research_storage_ready"] is True
    prompts = client.get("/api/research/prompts?language=en")
    assert prompts.status_code == 200 and len(prompts.json()) >= 30
    assert all(item["language"] == "en" for item in prompts.json())

    study = client.post("/api/research/studies", json={
        "title":"HTTP Study", "slug":"http-study",
        "research_question":"What recurring visible world appears in this HTTP test?",
        "theoretical_framework":"Cultivation-inspired representational audit",
        "protocol_version":"1.0",
    })
    assert study.status_code == 201
    wave = client.post(f"/api/research/studies/{study.json()['id']}/waves", json={"label":"2026-H2"})
    assert wave.status_code == 201
    selected = [item["id"] for item in prompts.json()[:2]]
    invalid_benchmark = client.post("/api/research/benchmarks", json={
        "study_wave_id":wave.json()["id"], "name":"Invalid total", "version":"1.0",
        "dimension":"visible_gender_presentation", "scope_type":"occupation", "scope_key":"fixture",
        "source_organization":"Offline test", "source_title":"Invalid fixture",
        "denominator_description":"Offline denominator", "distribution":{"Female":60,"Male":30},
        "prompt_definition_ids":[selected[0]],
    })
    assert invalid_benchmark.status_code == 422
    benchmark = client.post("/api/research/benchmarks", json={
        "study_wave_id":wave.json()["id"], "name":"Configured fixture", "version":"1.0",
        "dimension":"visible_gender_presentation", "scope_type":"occupation", "scope_key":"fixture",
        "source_organization":"Offline test", "source_title":"Explicit fixture",
        "denominator_description":"Offline denominator", "distribution":{"Female":60,"Male":40},
        "prompt_definition_ids":[selected[0]],
    })
    assert benchmark.status_code == 201 and benchmark.json()["distribution"]["Female"] == .6
    campaign = client.post("/api/research/campaigns", json={
        "wave_id":wave.json()["id"], "name":"HTTP campaign",
        "target_per_prompt":10, "prompt_definition_ids":selected,
        "prompt_variant_ids":[],
    })
    assert campaign.status_code == 201 and campaign.json()["requested_total"] == 20
    campaign_id = campaign.json()["id"]
    locked_benchmark = client.post("/api/research/benchmarks", json={
        "study_wave_id":wave.json()["id"], "name":"Late snapshot", "version":"1.0",
        "dimension":"urbanicity", "scope_type":"occupation", "scope_key":"fixture",
        "source_organization":"Offline test", "source_title":"Late fixture",
        "denominator_description":"Offline denominator", "distribution":{"Urban":100},
        "prompt_definition_ids":[selected[0]],
    })
    assert locked_benchmark.status_code == 409
    dry = client.get(f"/api/research/campaigns/{campaign_id}/dry-run")
    assert dry.status_code == 200 and dry.json()["real_api_calls_made"] is False
    status = client.get(f"/api/research/campaigns/{campaign_id}/status")
    assert status.status_code == 200 and status.json()["counts"]["requested"] == 20
    start = client.post(f"/api/research/campaigns/{campaign_id}/start")
    assert start.status_code == 503
    atlas = client.get(f"/api/research/waves/{wave.json()['id']}/atlas")
    assert atlas.status_code == 200 and len(atlas.json()["rows"]) == 2
    assert all(
        cell["status"] in {"no_reference", "insufficient_sample"}
        for row in atlas.json()["rows"] for cell in row["cells"]
    )

engine.dispose()
temp_dir.cleanup()
print("PASS: research API responses, 503 guard, and honest empty atlas")
