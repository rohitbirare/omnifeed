import shutil
from fastapi import APIRouter
from app.config import get_system_status
from app.services.images import test_image_provider_connection, test_pixabay_connection
from app.services.llm import test_llm_connection
from app.services.render import test_ffmpeg_caption_burn
from app.services.tts import test_tts_engine

router = APIRouter(tags=["Status"])


@router.get("/healthz")
async def health_check():
    return {"status": "ok", "product": "OmniFeed"}


@router.get("/api/status")
async def system_status():
    return get_system_status()


@router.post("/api/status/test-llm")
async def test_llm():
    return test_llm_connection()


@router.post("/api/status/test-image")
async def test_image():
    return await test_image_provider_connection()


@router.post("/api/status/test-pixabay")
async def test_pixabay():
    return await test_pixabay_connection()


@router.post("/api/status/self-test")
async def run_full_self_test():
    """Runs full pipeline self-test: LLM, TTS, Pixabay download, FFmpeg caption burn, and ffprobe."""
    # 1. LLM
    llm_res = test_llm_connection()

    # 2. TTS
    tts_res = await test_tts_engine()

    # 3. Pixabay
    pix_res = await test_pixabay_connection()

    # 4. FFmpeg caption burn
    burn_res = test_ffmpeg_caption_burn()

    # 5. FFprobe
    ffprobe_ok = bool(shutil.which("ffprobe"))
    ffprobe_res = {
        "success": ffprobe_ok,
        "message": "ffprobe installed and executable" if ffprobe_ok else "ffprobe not found in PATH",
    }

    all_passed = bool(
        llm_res.get("success")
        and tts_res.get("success")
        and pix_res.get("success")
        and burn_res.get("success")
        and ffprobe_res.get("success")
    )

    return {
        "all_passed": all_passed,
        "results": {
            "llm": llm_res,
            "tts": tts_res,
            "pixabay": pix_res,
            "caption_burn": burn_res,
            "ffprobe": ffprobe_res,
        },
    }
