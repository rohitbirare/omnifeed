import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.config import BASE_DIR, MEDIA_DIR, settings
from app.database import init_db
from app.routers import jobs, status
from app.services.tts import initialize_voice_cache

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("omnifeed.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database and recover any interrupted jobs
    logger.info("Initializing OmniFeed database...")
    init_db()

    # Pre-cache and verify edge-tts voice catalog
    logger.info("Initializing TTS voice catalog...")
    await initialize_voice_cache()

    logger.info(f"OmniFeed backend initialized successfully. Media directory: {MEDIA_DIR}")
    yield
    logger.info("OmniFeed backend shutting down.")


app = FastAPI(
    title="OmniFeed Backend API",
    description="Autonomous Multimodal Content Pipeline for Qoneqt",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
origins_str = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allowed_origins = [o.strip() for o in origins_str.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "Content-Type"],
)

# Mount media directory for video, audio, and thumbnail streaming & downloads
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")

# Include JSON API routers
app.include_router(jobs.router)
app.include_router(status.router)


@app.get("/")
async def root():
    return {
        "status": "ok",
        "product": "OmniFeed Backend API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/healthz",
            "status": "/api/status",
            "self_test": "/api/status/self-test",
            "jobs": "/api/jobs",
            "media": "/media",
        },
    }
