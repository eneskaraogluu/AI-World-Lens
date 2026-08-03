import logging
import colorama
from colorama import Fore, Style
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api import routes_category, routes_prompt, routes_experiment, routes_statistics, routes_comparison, routes_research, routes_presentation
from backend.services.queue_worker import queue_worker
from backend.core.config import settings
from backend.core.database import SessionLocal
from backend.services.analysis_revision_service import analysis_history_available
from backend.services.research_campaign_service import (
    recover_interrupted_campaigns,
    research_schema_available,
)

# Initialize Colorama and Logging
colorama.init(autoreset=True)

class ColoredFormatter(logging.Formatter):
    def format(self, record):
        if record.levelno == logging.ERROR:
            color = Fore.RED
        elif record.levelno == logging.WARNING:
            color = Fore.YELLOW
        elif record.levelno == logging.INFO:
            color = Fore.GREEN
        else:
            color = Style.RESET_ALL
        
        record.msg = f"{color}{record.msg}{Style.RESET_ALL}"
        return super().format(record)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
# Avoid duplicate logs if uvicorn already adds handlers, but we want our colors
if not logger.handlers:
    logger.addHandler(handler)

app = FastAPI(
    title="AI World Lens API",
    description="API for managing Generative AI research experiments",
    version="1.0.0"
)

# CORS ayarları: Frontend'in (React/Vue vs.) bu API'ye erişebilmesi için gerekli
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Geliştirme aşamasında her yere izin ver
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(routes_category.router, prefix="/api/categories", tags=["Categories"])
app.include_router(routes_prompt.router, prefix="/api/prompts", tags=["Prompts"])
app.include_router(routes_experiment.router, prefix="/api/experiments", tags=["Experiments"])
app.include_router(routes_statistics.router, prefix="/api/statistics", tags=["Statistics"])
app.include_router(routes_comparison.router, prefix="/api/comparison", tags=["Comparison"])
app.include_router(routes_research.router, prefix="/api/research", tags=["Research"])
app.include_router(routes_presentation.router, prefix="/api/presentation", tags=["Presentation Safety"])

@app.on_event("startup")
async def startup_event():
    db = SessionLocal()
    try:
        if research_schema_available(db):
            interrupted = recover_interrupted_campaigns(db)
            if interrupted:
                logger.warning(
                    "Paused %s interrupted research campaign(s); resume is explicit and idempotent.",
                    interrupted,
                )
    finally:
        db.close()
    queue_worker.start_workers(num_workers=settings.QUEUE_WORKERS)

@app.on_event("shutdown")
async def shutdown_event():
    await queue_worker.stop_workers()

@app.get("/")
def root():
    return {"message": "Welcome to AI World Lens API. Go to /docs for Swagger UI."}


@app.get("/api/health")
def health():
    warnings = []
    if not settings.GEMINI_API_KEY:
        warnings.append("GEMINI_API_KEY is missing")
    if settings.IMAGE_PROVIDER == "openai" and not settings.OPENAI_API_KEY:
        warnings.append("OPENAI_API_KEY is missing")
    if settings.IMAGE_PROVIDER == "pollinations" and not settings.POLLINATIONS_API_KEY:
        warnings.append("POLLINATIONS_API_KEY is missing")
    db = SessionLocal()
    try:
        fallback_revision_storage_ready = analysis_history_available(db)
        research_storage_ready = research_schema_available(db)
    except Exception:
        fallback_revision_storage_ready = False
        research_storage_ready = False
    finally:
        db.close()
    return {
        "status": "ready" if not warnings else "configuration_required",
        "gemini_configured": bool(settings.GEMINI_API_KEY),
        "openai_configured": bool(settings.OPENAI_API_KEY),
        "pollinations_configured": bool(settings.POLLINATIONS_API_KEY),
        "image_provider": settings.IMAGE_PROVIDER,
        "image_model": settings.OPENAI_IMAGE_MODEL if settings.IMAGE_PROVIDER == "openai" else settings.POLLINATIONS_MODEL,
        "gemini_model": settings.GEMINI_MODEL,
        "primary_vision_provider": settings.PRIMARY_VISION_PROVIDER,
        "primary_vision_model": settings.GEMINI_MODEL,
        "fallback_vision_provider": (
            settings.FALLBACK_VISION_PROVIDER
            if settings.FALLBACK_VISION_PROVIDER == "openai" else None
        ),
        "fallback_vision_model": settings.OPENAI_VISION_MODEL,
        "fallback_vision_configured": bool(
            settings.FALLBACK_VISION_PROVIDER == "openai" and settings.OPENAI_API_KEY
        ),
        "fallback_revision_storage_ready": fallback_revision_storage_ready,
        "research_storage_ready": research_storage_ready,
        "vision_test_simulation_active": settings.VISION_TEST_SIMULATE_GEMINI_QUOTA,
        "pollinations_model": settings.POLLINATIONS_MODEL,
        "run_iterations": settings.RUN_ITERATIONS,
        "queue_size": queue_worker.queue.qsize(),
        "warnings": warnings,
    }
