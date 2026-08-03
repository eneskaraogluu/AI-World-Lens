"""Offline Faz 1/2 regression tests. No provider or real DB calls."""

import asyncio
import json
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.base import Base
from backend.models.models import Category, Experiment, Prompt, Result
from backend.models.research_models import BenchmarkMapping, BenchmarkSnapshot, CampaignPrompt, ResearchAnalysisV2, ResearchTask, Study
from backend.schemas.research import BenchmarkCreate, CampaignCreate, StudyCreate, WaveCreate
from backend.services.research_benchmark_service import create_benchmark, normalize_distribution
from backend.services.research_analysis_service import AnalysisV2Payload, apply_scene_policy_flags, v1_projection
from backend.services.research_campaign_service import (
    ResearchStateError,
    _selection_hash,
    build_manifest,
    canonical_counts,
    create_campaign,
    create_study,
    create_wave,
    dry_run,
    materialize_tasks,
)
from backend.services.research_metrics_service import (
    atlas,
    benjamini_hochberg,
    chi_square_goodness_of_fit,
    evidence,
    experiment_trajectory,
    jensen_shannon_divergence,
    percentage_point_gap,
    representation_ratio,
    trajectory,
    wilson_interval,
)
from backend.services.research_prompt_service import (
    CATALOGUE,
    prompt_set_hash,
    seed_prompt_catalogue,
    standardize_prompt,
)


engine = create_engine("sqlite://")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
db = Session()


first_seed = seed_prompt_catalogue(db)
second_seed = seed_prompt_catalogue(db)
assert first_seed["concepts"] >= 30 and first_seed["definitions"] >= 60
assert second_seed["created"] == 0
assert len(CATALOGUE) >= 30
definitions = db.query(__import__("backend.models.research_models", fromlist=["PromptDefinition"]).PromptDefinition).all()
assert {item.language for item in definitions} == {"en", "tr"}
assert len({(item.concept_key, item.language) for item in definitions}) == len(definitions)

single = standardize_prompt("an engineer", "single_person")
family = standardize_prompt("a family", "family_group")
place = standardize_prompt("a city square", "place_focused")
assert "exactly one primary person" in single.lower()
assert "exactly one" not in family.lower()
assert "exactly one" not in place.lower() and "people may appear" in place.lower()

study = create_study(db, StudyCreate(
    title="Ortalama Dunya Test",
    slug="ortalama-dunya-test",
    research_question="What recurring visible world does a neutral prompt produce?",
))
wave = create_wave(db, study, WaveCreate(label="2026-H2"))
selected = sorted([item for item in definitions if item.language == "en"], key=lambda item: item.slug)[:3]
fixed_time = datetime(2026, 8, 3, 12, 0, 0)
manifest_a = build_manifest(wave, study, selected, 10, created_at=fixed_time)
manifest_b = build_manifest(wave, study, list(reversed(selected)), 10, created_at=fixed_time)
assert manifest_a == manifest_b
assert "api_key" not in json.dumps(manifest_a).lower()
assert prompt_set_hash(selected) == prompt_set_hash(reversed(selected))
other_engine = create_engine("sqlite://")
Base.metadata.create_all(other_engine)
other_db = sessionmaker(bind=other_engine)(); seed_prompt_catalogue(other_db)
other_selected = other_db.query(type(selected[0])).filter(type(selected[0]).slug.in_([item.slug for item in selected])).all()
assert _selection_hash(selected, {}) == _selection_hash(other_selected, {})
other_db.close()
assert normalize_distribution({"Female": 60, "Male": 40}) == {"Female": .6, "Male": .4}
try:
    normalize_distribution({"Female": 60, "Male": 30})
except ValueError:
    pass
else:
    raise AssertionError("Invalid benchmark total was accepted")

benchmark_wave = create_wave(db, study, WaveCreate(label="benchmark-draft", benchmark_version="1.0"))
registry_row = create_benchmark(db, BenchmarkCreate(
    study_wave_id=benchmark_wave.id, name="Offline occupation baseline", version="1.0",
    dimension="visible_gender_presentation", scope_type="occupation", scope_key=selected[0].concept_key,
    reference_year="2026", geographic_scope="Offline test", source_organization="Test registry",
    source_title="Explicit offline fixture", denominator_description="Test denominator",
    distribution={"Female":60,"Male":40}, prompt_definition_ids=[selected[0].id],
))
assert json.loads(registry_row.distribution_json) == {"Female": .6, "Male": .4}

campaign = create_campaign(db, CampaignCreate(
    wave_id=wave.id,
    name="Test baseline",
    target_per_prompt=10,
    prompt_definition_ids=[item.id for item in selected],
))
assert campaign.requested_total == 30 and wave.locked_at is not None
assert materialize_tasks(db, campaign) == 30
assert materialize_tasks(db, campaign) == 0
plan = dry_run(db, campaign)
assert plan["missing_tasks"] == 0 and plan["duplicate_tasks"] == 0 and plan["real_api_calls_made"] is False
assert db.query(ResearchTask).count() == 30

different = next(item for item in definitions if item.id not in {chosen.id for chosen in selected})
try:
    create_campaign(db, CampaignCreate(
        wave_id=wave.id, name="Different prompt set", target_per_prompt=10,
        prompt_definition_ids=[different.id],
    ))
except ResearchStateError:
    pass
else:
    raise AssertionError("Locked wave accepted a different prompt set")

# Build 10 real-looking, machine-provisional V2 records entirely in SQLite.
campaign_prompt = db.query(CampaignPrompt).filter(CampaignPrompt.campaign_id == campaign.id).first()
legacy_category = Category(name="Offline research test")
legacy_prompt = Prompt(category=legacy_category, text=campaign_prompt.standardized_prompt)
experiment = Experiment(name="Offline V2", model_name="fake-image + fake-vision", status="completed")
db.add_all([legacy_category, legacy_prompt, experiment]); db.commit()
tasks = db.query(ResearchTask).filter(ResearchTask.campaign_prompt_id == campaign_prompt.id).order_by(ResearchTask.sample_index).all()
base_time = datetime(2026, 8, 3, 12, 0, 0)
for index, task in enumerate(tasks, start=1):
    result = Result(
        experiment_id=experiment.id, prompt_id=legacy_prompt.id,
        image_reference=f"offline-{index}.png", model_name="fake-image",
        analysis_status="success", detected_person_count=1,
        detected_gender="Female" if index <= 6 else "Male",
        detected_age_group="55+" if index <= 2 else "35-44",
        created_at=base_time + timedelta(seconds=index),
    )
    db.add(result); db.flush()
    payload = AnalysisV2Payload.model_validate({
        "analysis_schema_version":"2.0", "detected_person_count":1,
        "persons":[{"person_index":1,"is_primary":True,"visible_gender_presentation":"Female" if index <= 6 else "Male","estimated_age_group":"55+" if index <= 2 else "35-44"}],
        "scene":{"setting_type":"Office","indoor_outdoor":"Indoor","urbanicity":"Urban","environment_condition":"WellMaintained","technology_presence":"High" if index <= 4 else "Medium","vehicle_presence":"NotVisible","attire_formality":"Workwear"},
        "occupation_alignment":"Aligned", "quality_flags":[], "notes":None,
    })
    db.add(ResearchAnalysisV2(
        result_id=result.id, provider="fake", model_name="fake-vision", revision=1,
        status="success", source_type="machine_provisional", payload_json=payload.model_dump_json(),
        quality_flags_json="[]", is_active=True,
    ))
    task.result_id = result.id; task.experiment_id = experiment.id; task.status = "validated"; task.completed_at = result.created_at
db.commit()

campaign = db.query(type(campaign)).filter(type(campaign).id == campaign.id).first()
counts = canonical_counts(db, campaign)
assert counts["requested"] == 30 and counts["completed"] == 10 and counts["machine_validated"] == 10
assert counts["gender_usable"] == 10 and counts["scene_usable"] == 10

single_payload = AnalysisV2Payload.model_validate_json(tasks[0].result and db.query(ResearchAnalysisV2).filter(ResearchAnalysisV2.result_id == tasks[0].result_id).one().payload_json)
assert v1_projection(single_payload)["detected_gender"] in {"Female", "Male"}
place_payload = AnalysisV2Payload.model_validate({
    "analysis_schema_version":"2.0", "detected_person_count":0, "persons":[],
    "scene":{"setting_type":"PublicSpace","indoor_outdoor":"Outdoor","urbanicity":"Urban","environment_condition":"Mixed","technology_presence":"Low","vehicle_presence":"Present","attire_formality":"Unclear"},
    "occupation_alignment":"NotApplicable", "quality_flags":[], "notes":None,
})
assert v1_projection(place_payload) is None
assert apply_scene_policy_flags(place_payload, "zero_or_more").quality_flags == []
multi_payload = AnalysisV2Payload.model_validate({
    **place_payload.model_dump(), "detected_person_count":2,
    "persons":[{"person_index":1,"is_primary":True,"visible_gender_presentation":"Unclear","estimated_age_group":"Unclear"},{"person_index":2,"is_primary":False,"visible_gender_presentation":"Unclear","estimated_age_group":"Unclear"}],
})
assert v1_projection(multi_payload) is None
try:
    AnalysisV2Payload.model_validate({**place_payload.model_dump(), "detected_person_count": 1})
except ValueError:
    pass
else:
    raise AssertionError("Inconsistent person count was accepted")
sensitive_tokens = {"ethnicity", "religion", "nationality", "health", "income", "social_class"}
assert not sensitive_tokens.intersection(AnalysisV2Payload.model_fields)

for dimension, values in {
    "visible_gender_presentation":{"Female":6000,"Male":4000},
    "estimated_age_group":{"55+":2000,"35-44":8000},
    "urbanicity":{"Urban":10000},
    "occupation_alignment":{"Aligned":10000},
    "technology_presence":{"High":4000,"Medium":6000},
}.items():
    snapshot = BenchmarkSnapshot(
        study_wave_id=wave.id, name=f"Offline {dimension}", version=wave.benchmark_version,
        dimension=dimension, scope_type="occupation", scope_key=campaign_prompt.definition.concept_key,
        source_organization="Offline test registry", source_title="Configured benchmark",
        denominator_description="Offline test denominator",
        category_mapping_json="{}",
        distribution_json=json.dumps({key:value/10000 for key,value in values.items()}),
        verification_status="configured",
    )
    db.add(snapshot); db.flush()
    db.add(BenchmarkMapping(benchmark_snapshot_id=snapshot.id, prompt_definition_id=campaign_prompt.prompt_definition_id))
db.commit()

track = trajectory(db, campaign_prompt, "visible_gender_presentation")
assert [point["n"] for point in track["points"]] == list(range(1, 11))
assert track["points"][-1]["denominator"] == 10 and track["provider"] == "fake"
mixed = ResearchAnalysisV2(
    result_id=tasks[0].result_id, provider="other", model_name="other-vision", revision=2,
    status="success", source_type="machine_provisional",
    payload_json=db.query(ResearchAnalysisV2).filter(ResearchAnalysisV2.result_id == tasks[0].result_id).first().payload_json,
    quality_flags_json="[]", is_active=True,
)
db.add(mixed); db.commit()
try:
    trajectory(db, campaign_prompt, "visible_gender_presentation")
except ResearchStateError:
    pass
else:
    raise AssertionError("Mixed provider revisions were silently combined")
db.delete(mixed); db.commit()
cinema_track = experiment_trajectory(db, experiment.id)
assert [point["n"] for point in cinema_track["points"]] == list(range(1, 11))
assert cinema_track["denominator_rule"].startswith("Unclear")
atlas_data = atlas(db, wave, minimum_n=10)
row = next(item for item in atlas_data["rows"] if item["campaign_prompt_id"] == campaign_prompt.id)
female = next(cell for cell in row["cells"] if cell["dimension"] == "female_gap")
assert female["status"] == "value" and female["value"] == 0.0 and female["unit"] == "pp"
other_row = next(item for item in atlas_data["rows"] if item["campaign_prompt_id"] != campaign_prompt.id)
assert next(cell for cell in other_row["cells"] if cell["dimension"] == "female_gap")["status"] == "no_reference"
proof = evidence(db, wave, campaign_prompt, "visible_gender_presentation", "Female")
assert len(proof["items"]) == 10 and sum(item["included_in_metric"] for item in proof["items"]) == 6

assert percentage_point_gap(.6, .4) == 20.0
assert representation_ratio(.6, .4) == 1.5
assert representation_ratio(.6, 0) is None
low, high = wilson_interval(5, 10)
assert 0.23 < low < 0.24 and 0.76 < high < 0.77
assert all(math_value == math_value and math_value not in {float("inf"), float("-inf")} for math_value in (low, high))
chi = chi_square_goodness_of_fit({"Female":60,"Male":40}, {"Female":.5,"Male":.5})
assert chi and round(chi["statistic"], 1) == 4.0 and chi["p_value"] > 0
assert chi_square_goodness_of_fit({"Female":3,"Male":2}, {"Female":.5,"Male":.5}) is None
assert jensen_shannon_divergence({"Female":.5,"Male":.5}, {"Female":.5,"Male":.5}) == 0
assert benjamini_hochberg([.01,.04,None,.03]) == [.03,.04,None,.04]

print("PASS: research core, Analysis V2, trajectory, atlas, and evidence tests")
