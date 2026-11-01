from contextlib import asynccontextmanager
import logging
from pathlib import Path
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from retain_ai.api.routes import router as api_router
from retain_ai.config import settings
from retain_ai.database import async_session_factory, init_db
from retain_ai.repository.review_card_repository import ReviewCardRepository
from retain_ai.service.grading_service import GradingService
from retain_ai.service.review_orchestrator import ReviewOrchestrator
from retain_ai.service.scheduler_service import SchedulerService
from retain_ai.voice.gemini_live_client import GeminiLiveClient
from retain_ai.voice.live_voice_session_handler import LiveVoiceSessionHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("retain_ai")

STATIC_DIR = Path(__file__).resolve().parent / "static"

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database schema...")
    await init_db()
    logger.info("Retain AI backend ready on %s:%d", settings.host, settings.port)
    yield
    logger.info("Shutting down Retain AI backend...")

app = FastAPI(
    title="Retain AI",
    description="Voice-based spaced repetition review app with Gemini Live API",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API
app.include_router(api_router)

# WebSocket endpoint matching /ws/review
@app.websocket("/ws/review")
async def websocket_review_endpoint(websocket: WebSocket):
    async with async_session_factory() as session:
        card_repo = ReviewCardRepository(session)
        grading_svc = GradingService(
            api_key=settings.gemini_api_key,
            model_name=settings.get_text_model_name()
        )
        scheduler_svc = SchedulerService(card_repo)
        orchestrator = ReviewOrchestrator(scheduler_svc, grading_svc)

        gemini_live = GeminiLiveClient(
            api_key=settings.gemini_api_key,
            model_name=settings.get_live_model_name()
        )
        system_prompt = settings.get_system_prompt()

        handler = LiveVoiceSessionHandler(
            gemini_live_client=gemini_live,
            review_orchestrator=orchestrator,
            grading_service=grading_svc,
            system_prompt=system_prompt
        )
        await handler.handle(websocket)

# Static file serving
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return {"message": "Retain AI API running. Place index.html in static/"}

@app.get("/app.js")
async def serve_app_js():
    js_file = STATIC_DIR / "app.js"
    if js_file.is_file():
        return FileResponse(js_file, media_type="application/javascript")
    return {"error": "app.js not found"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("retain_ai.main:app", host=settings.host, port=settings.port, reload=True)

