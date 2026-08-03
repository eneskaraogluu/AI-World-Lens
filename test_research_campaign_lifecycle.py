"""Offline queue lifecycle checks with a fake enqueue adapter."""

import asyncio

from backend.core.database import SessionLocal, engine
from backend.models.base import Base
from backend.models.research_models import Campaign, CampaignPrompt, PromptDefinition, ResearchTask
from backend.schemas.research import CampaignCreate, StudyCreate, WaveCreate
from backend.services.queue_worker import queue_worker
from backend.services.research_campaign_service import (
    create_campaign,
    create_study,
    create_wave,
    dispatch_available,
    pause_campaign,
    recover_interrupted_campaigns,
    resume_campaign,
    start_campaign,
)
from backend.services.research_prompt_service import seed_prompt_catalogue


Base.metadata.create_all(engine)
db = SessionLocal()
seed_prompt_catalogue(db)
definition = db.query(PromptDefinition).filter(PromptDefinition.language == "en").first()
study = create_study(db, StudyCreate(
    title="Lifecycle Study", slug="lifecycle-study",
    research_question="How does the persistent campaign queue behave across pauses?",
))
wave = create_wave(db, study, WaveCreate(label="offline-wave"))
campaign = create_campaign(db, CampaignCreate(
    wave_id=wave.id, name="Lifecycle campaign", target_per_prompt=3,
    prompt_definition_ids=[definition.id],
))
campaign_id = campaign.id

enqueued = []
registered = []
original_enqueue = queue_worker.enqueue_task
original_register = queue_worker.register_research_job


async def fake_enqueue(task):
    enqueued.append(dict(task))


async def fake_register(experiment_id, prompt_id, total, already_completed=0):
    registered.append((str(experiment_id), str(prompt_id), total, already_completed))


queue_worker.enqueue_task = fake_enqueue
queue_worker.register_research_job = fake_register


async def scenario():
    await start_campaign(campaign_id, use_mock=True)
    first_ids = [str(item["research_task_id"]) for item in enqueued]
    assert len(first_ids) == 2 and len(set(first_ids)) == 2
    await start_campaign(campaign_id, use_mock=True)
    assert len(enqueued) == 2

    local = SessionLocal()
    active_campaign = local.query(Campaign).filter(Campaign.id == campaign_id).first()
    pause_campaign(local, active_campaign)
    local.close()
    await resume_campaign(campaign_id, use_mock=True)
    assert len(enqueued) == 2, "same-process resume duplicated active tasks"

    local = SessionLocal()
    first_task = local.query(ResearchTask).filter(ResearchTask.id == enqueued[0]["research_task_id"]).first()
    first_task.status = "validated"
    local.commit(); local.close()
    await dispatch_available(campaign_id, use_mock=True)
    assert len(enqueued) == 3
    assert len({str(item["research_task_id"]) for item in enqueued}) == 3

    # Simulate a process restart: active result-less slots become planned,
    # completed slots stay terminal, and the campaign requires explicit resume.
    local = SessionLocal()
    assert recover_interrupted_campaigns(local) == 1
    assert local.query(Campaign).filter(Campaign.id == campaign_id).one().status == "paused"
    assert local.query(ResearchTask).filter(ResearchTask.status == "validated").count() == 1
    local.close()
    enqueued.clear()
    await resume_campaign(campaign_id, use_mock=True)
    assert len(enqueued) == 2
    resumed_ids = {str(item["research_task_id"]) for item in enqueued}
    local = SessionLocal()
    completed_id = str(local.query(ResearchTask).filter(ResearchTask.status == "validated").one().id)
    local.close()
    assert completed_id not in resumed_ids


try:
    asyncio.run(scenario())
finally:
    queue_worker.enqueue_task = original_enqueue
    queue_worker.register_research_job = original_register
    db.close()

print("PASS: campaign start/pause/resume/restart idempotency with fake queue")
