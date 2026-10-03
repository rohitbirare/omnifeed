import os
import shutil
from pathlib import Path
from typing import List
from pydantic import BaseModel
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data")))
MEDIA_DIR = DATA_DIR / "media"
DB_PATH = DATA_DIR / "omnifeed.db"

# Ensure data directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseModel):
    # Required LLM Settings
    llm_api_key: str = ""
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    llm_model: str = "gemini-1.5-flash"
    llm_fallback_model: str = "gemini-3.5-flash-lite"

    # Required Stock Photo Provider (Pixabay)
    pixabay_api_key: str = ""

    # Optional AI Image Generation (OpenAI-compatible /images/generations)
    image_api_key: str = ""
    image_base_url: str = ""
    image_model: str = ""

    # Optional Qoneqt API Publishing
    qoneqt_api_base: str = ""
    qoneqt_api_token: str = ""
    qoneqt_upload_path: str = ""
    qoneqt_field_name: str = ""
    qoneqt_app_url: str = "https://qoneqt.com"

    # Concurrency
    max_concurrent_renders: int = 2

    # CORS
    cors_origins: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


def load_settings() -> Settings:
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    llm_key = os.environ.get("LLM_API_KEY", "").strip()

    # If LLM_API_KEY is not explicitly set, fall back to GEMINI_API_KEY
    if not llm_key and gemini_key:
        llm_key = gemini_key

    llm_base = os.environ.get(
        "LLM_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta/openai"
    ).rstrip("/")

    llm_model = os.environ.get("LLM_MODEL", "gemini-2.0-flash").strip()
    if not llm_model:
        llm_model = "gemini-2.0-flash"
    llm_fallback = os.environ.get("LLM_FALLBACK_MODEL", "gemini-2.5-flash-lite").strip()
    pixabay_key = os.environ.get("PIXABAY_API_KEY", "").strip()

    # Optional Image Generation (unset or empty is fully supported)
    image_key = os.environ.get("IMAGE_API_KEY", "").strip()
    image_base = os.environ.get("IMAGE_BASE_URL", "").rstrip("/")
    image_model = os.environ.get("IMAGE_MODEL", "").strip()
    if not image_model and image_key:
        image_model = "dall-e-3"

    # Optional Qoneqt API publishing (unset or empty is fully supported)
    qoneqt_base = os.environ.get("QONEQT_API_BASE", "").rstrip("/")
    qoneqt_token = os.environ.get("QONEQT_API_TOKEN", "").strip()
    qoneqt_upload = os.environ.get("QONEQT_UPLOAD_PATH", "").strip()
    qoneqt_field = os.environ.get("QONEQT_FIELD_NAME", "").strip()
    qoneqt_url = os.environ.get("QONEQT_APP_URL", "").strip() or "https://qoneqt.com"

    cors_env = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    origins = [o.strip() for o in cors_env.split(",") if o.strip()]

    return Settings(
        llm_api_key=llm_key,
        llm_base_url=llm_base,
        llm_model=llm_model,
        llm_fallback_model=llm_fallback,
        pixabay_api_key=pixabay_key,
        image_api_key=image_key,
        image_base_url=image_base,
        image_model=image_model,
        qoneqt_api_base=qoneqt_base,
        qoneqt_api_token=qoneqt_token,
        qoneqt_upload_path=qoneqt_upload,
        qoneqt_field_name=qoneqt_field,
        qoneqt_app_url=qoneqt_url,
        max_concurrent_renders=int(os.environ.get("MAX_CONCURRENT_RENDERS", "2")),
        cors_origins=origins,
    )


settings = load_settings()


def get_system_status() -> dict:
    ffmpeg_available = bool(shutil.which("ffmpeg"))
    ffprobe_available = bool(shutil.which("ffprobe"))

    return {
        "status": "healthy",
        "product": "OmniFeed",
        "version": "1.0.0",
        "providers": {
            "llm": {
                "required": True,
                "configured": bool(settings.llm_api_key),
                "model": settings.llm_model,
                "base_url": settings.llm_base_url,
                "has_fallback": bool(settings.llm_fallback_model),
                "fallback_model": settings.llm_fallback_model,
            },
            "pixabay": {
                "required": False,
                "configured": bool(settings.pixabay_api_key),
            },
            "image_generation": {
                "required": False,
                "configured": bool(settings.image_api_key and settings.image_base_url),
                "model": settings.image_model if settings.image_api_key else None,
                "base_url": settings.image_base_url if settings.image_api_key else None,
            },
            "edge_tts": {
                "required": True,
                "configured": True,
                "supported_languages": ["en", "hi", "mr"],
            },
            "qoneqt_api": {
                "required": False,
                "configured": bool(settings.qoneqt_api_base and settings.qoneqt_api_token),
                "mode": "api" if (settings.qoneqt_api_base and settings.qoneqt_api_token) else "assisted",
                "app_url": settings.qoneqt_app_url,
            },
        },
        "media_engine": {
            "ffmpeg": ffmpeg_available,
            "ffprobe": ffprobe_available,
        },
        "max_concurrent_renders": settings.max_concurrent_renders,
    }
