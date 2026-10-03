import asyncio
import io
import logging
import os
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import httpx
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from app.config import settings

logger = logging.getLogger("omnifeed.images")

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920


def cover_crop_to_9_16(img: Image.Image) -> Image.Image:
    """Crops and resizes any image to exact 1080x1920 (9:16) cover crop."""
    target_ratio = TARGET_WIDTH / TARGET_HEIGHT  # 0.5625
    orig_w, orig_h = img.size
    orig_ratio = orig_w / orig_h

    if orig_ratio > target_ratio:
        # Source is wider than target: crop left and right
        new_w = int(orig_h * target_ratio)
        offset_x = (orig_w - new_w) // 2
        box = (offset_x, 0, offset_x + new_w, orig_h)
    else:
        # Source is taller than target: crop top and bottom
        new_h = int(orig_w / target_ratio)
        offset_y = (orig_h - new_h) // 2
        box = (0, offset_y, orig_w, offset_y + new_h)

    cropped = img.crop(box)
    resized = cropped.resize((TARGET_WIDTH, TARGET_HEIGHT), Image.Resampling.LANCZOS)
    return resized


async def _generate_ai_image(prompt: str) -> bytes:
    """Calls OpenAI-compatible /images/generations endpoint (optional provider)."""
    if not settings.image_api_key or not settings.image_base_url:
        raise ValueError("Image generation credentials not configured")

    url = f"{settings.image_base_url}/images/generations"
    headers = {
        "Authorization": f"Bearer {settings.image_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": prompt,
        "n": 1,
        "size": "1024x1792",
        "model": settings.image_model or "dall-e-3",
        "response_format": "b64_json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

        img_item = data["data"][0]
        if "b64_json" in img_item:
            import base64
            return base64.b64decode(img_item["b64_json"])
        elif "url" in img_item:
            img_url = img_item["url"]
            img_resp = await client.get(img_url)
            img_resp.raise_for_status()
            return img_resp.content

    raise RuntimeError("Unrecognized image response format")


async def _fetch_pixabay_photo(query: str) -> bytes:
    """Searches Pixabay API with URL-encoded query and fallbacks to shorter queries."""
    if not settings.pixabay_api_key:
        raise ValueError("Pixabay API key not configured")

    clean_q = query.strip()
    words = clean_q.split()

    # Query cascade: full query -> 2 words -> 1 word
    queries_to_try = [clean_q]
    if len(words) > 2:
        queries_to_try.append(" ".join(words[:2]))
    if len(words) > 1:
        queries_to_try.append(words[0])

    async with httpx.AsyncClient(timeout=20.0) as client:
        last_err: Optional[Exception] = None
        for q_attempt in queries_to_try:
            encoded_q = urllib.parse.quote_plus(q_attempt)
            url = (
                f"https://pixabay.com/api/?key={settings.pixabay_api_key}"
                f"&q={encoded_q}&image_type=photo&orientation=vertical"
                f"&safesearch=true&per_page=5&min_height=1080"
            )
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                hits = data.get("hits", [])
                if hits:
                    first_hit = hits[0]
                    photo_url = (
                        first_hit.get("largeImageURL")
                        or first_hit.get("imageURL")
                        or first_hit.get("webformatURL")
                    )
                    if photo_url:
                        img_resp = await client.get(photo_url)
                        img_resp.raise_for_status()
                        return img_resp.content
            except Exception as e:
                last_err = e

        raise ValueError(
            f"No Pixabay vertical photos found for query '{query}' (tried: {queries_to_try}). "
            f"Last error: {str(last_err) if last_err else 'Zero search results'}"
        )


def _render_procedural_scene_poster(
    scene_id: int,
    prompt: str,
    emphasis: str,
    style: str,
    topic: str,
) -> bytes:
    """Generates an ultra-clean, production-grade 1080x1920 graphic scene card so a job never fails."""
    palette = [
        ((15, 23, 42), (30, 41, 59)),       # slate-900 to slate-800
        ((15, 118, 110), (13, 148, 136)),   # deep teal to teal-600
        ((30, 58, 138), (37, 99, 235)),     # navy to blue-600
        ((24, 24, 27), (63, 63, 70)),       # zinc
        ((2, 44, 34), (6, 78, 59)),         # dark emerald
    ]
    bg_start, bg_end = palette[(scene_id - 1) % len(palette)]

    base = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), color=bg_start)
    draw = ImageDraw.Draw(base)

    # Vertical gradient backdrop
    for y in range(TARGET_HEIGHT):
        ratio = y / TARGET_HEIGHT
        r = int(bg_start[0] + (bg_end[0] - bg_start[0]) * ratio)
        g = int(bg_start[1] + (bg_end[1] - bg_start[1]) * ratio)
        b = int(bg_start[2] + (bg_end[2] - bg_start[2]) * ratio)
        draw.line([(0, y), (TARGET_WIDTH, y)], fill=(r, g, b))

    # Grid texture
    grid_color = (255, 255, 255, 12)
    grid_img = Image.new("RGBA", (TARGET_WIDTH, TARGET_HEIGHT), (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid_img)
    for x in range(0, TARGET_WIDTH, 120):
        grid_draw.line([(x, 0), (x, TARGET_HEIGHT)], fill=grid_color, width=1)
    for y in range(0, TARGET_HEIGHT, 120):
        grid_draw.line([(0, y), (TARGET_WIDTH, y)], fill=grid_color, width=1)

    # Focus circle
    center_x, center_y = TARGET_WIDTH // 2, 800
    radius = 380
    grid_draw.ellipse(
        [center_x - radius, center_y - radius, center_x + radius, center_y + radius],
        outline=(255, 255, 255, 25),
        width=2,
    )
    base = Image.alpha_composite(base.convert("RGBA"), grid_img).convert("RGB")
    draw = ImageDraw.Draw(base)

    font_large = ImageFont.load_default()
    font_sub = ImageFont.load_default()
    font_tag = ImageFont.load_default()

    # Try system fonts if available
    for font_cand in [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        if os.path.exists(font_cand):
            try:
                font_large = ImageFont.truetype(font_cand, 64)
                font_sub = ImageFont.truetype(font_cand, 34)
                font_tag = ImageFont.truetype(font_cand, 26)
                break
            except Exception:
                pass

    # Scene header pill
    pill_text = f"SCENE 0{scene_id} // {style.upper()}"
    draw.rectangle([100, 260, 480, 320], fill=(255, 255, 255, 20), outline=(255, 255, 255, 60), width=1)
    draw.text((120, 275), pill_text, fill=(255, 255, 255), font=font_tag)

    # Center focus: Emphasis word / phrase
    emp = emphasis.strip().upper() if emphasis else topic.strip().upper()
    if len(emp) > 40:
        emp = emp[:40] + "..."

    words = emp.split()
    lines = []
    curr = []
    for w in words:
        if len(" ".join(curr + [w])) <= 16:
            curr.append(w)
        else:
            lines.append(" ".join(curr))
            curr = [w]
    if curr:
        lines.append(" ".join(curr))

    y_text = 720
    for line in lines[:2]:
        bbox = draw.textbbox((0, 0), line, font=font_large)
        text_w = bbox[2] - bbox[0]
        x_text = (TARGET_WIDTH - text_w) // 2
        draw.text((x_text + 3, y_text + 3), line, fill=(0, 0, 0, 180), font=font_large)
        draw.text((x_text, y_text), line, fill=(255, 255, 255), font=font_large)
        y_text += 85

    # Safe frame bottom visual descriptor
    desc = prompt[:80] + "..." if len(prompt) > 80 else prompt
    draw.text((100, TARGET_HEIGHT - 380), desc, fill=(203, 213, 225), font=font_sub)

    out_io = io.BytesIO()
    base.save(out_io, format="JPEG", quality=92)
    return out_io.getvalue()


async def generate_scene_image(
    scene_id: int,
    visual_prompt: str,
    stock_query: str,
    emphasis: str,
    visual_style: str,
    topic: str,
    output_path: Path,
) -> str:
    """Attempts visual sources with Pillow validation and graceful fallback to scene card."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    provider_used = "procedural_scene_card"
    raw_bytes: Optional[bytes] = None

    # 1. Try AI Image Generation if configured
    if settings.image_api_key and settings.image_base_url:
        try:
            logger.info(f"Generating AI image for scene {scene_id}")
            candidate_bytes = await _generate_ai_image(visual_prompt)
            # Validate with Pillow
            with Image.open(io.BytesIO(candidate_bytes)) as test_img:
                test_img.load()
            raw_bytes = candidate_bytes
            provider_used = f"ai_generation ({settings.image_model or 'dall-e-3'})"
        except Exception as e:
            logger.warning(f"AI image generation failed for scene {scene_id}: {str(e)}")

    # 2. Try Pixabay provider
    if raw_bytes is None and settings.pixabay_api_key:
        try:
            q = stock_query if stock_query else topic
            logger.info(f"Fetching Pixabay photo for scene {scene_id} query '{q}'")
            candidate_bytes = await _fetch_pixabay_photo(q)
            # Validate with Pillow
            with Image.open(io.BytesIO(candidate_bytes)) as test_img:
                test_img.load()
            raw_bytes = candidate_bytes
            provider_used = "pixabay"
        except Exception as e:
            logger.warning(f"Pixabay visual fetching failed for scene {scene_id}: {str(e)}")

    # 3. Plain text scene card fallback - job NEVER fails only because of missing image
    if raw_bytes is None:
        logger.info(f"Generating clean text scene card for scene {scene_id}")
        raw_bytes = _render_procedural_scene_poster(
            scene_id=scene_id,
            prompt=visual_prompt,
            emphasis=emphasis,
            style=visual_style,
            topic=topic,
        )
        provider_used = "scene_card"

    # Cover-crop to exact 1080x1920
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    final_img = cover_crop_to_9_16(img)
    final_img.save(output_path, format="JPEG", quality=92)
    return provider_used


async def generate_all_scene_images(
    scenes: List[Dict[str, Any]],
    visual_style: str,
    topic: str,
    media_dir: Path,
    max_concurrency: int = 3,
) -> List[Dict[str, Any]]:
    """Generates images for all scenes with controlled concurrency (max 3)."""
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _worker(scene: Dict[str, Any]):
        s_id = scene.get("scene_id", 1)
        out_file = media_dir / f"scene_{s_id}.jpg"
        async with semaphore:
            provider = await generate_scene_image(
                scene_id=s_id,
                visual_prompt=scene.get("visual_prompt", ""),
                stock_query=scene.get("stock_query", ""),
                emphasis=scene.get("emphasis", ""),
                visual_style=visual_style,
                topic=topic,
                output_path=out_file,
            )
            scene["visual_path"] = str(out_file)
            scene["visual_provider"] = provider
            return scene

    tasks = [_worker(s) for s in scenes]
    results = await asyncio.gather(*tasks)
    return results


async def test_pixabay_connection() -> Dict[str, Any]:
    """Tests Pixabay API key connectivity and search response."""
    t0 = time.time()
    if not settings.pixabay_api_key:
        return {
            "success": True,
            "latency_ms": 0.0,
            "provider": "pixabay",
            "message": "Pixabay key not configured (using built-in 9:16 scene cards)",
        }

    try:
        raw = await _fetch_pixabay_photo("technology")
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            w, h = img.size
        latency = round((time.time() - t0) * 1000, 2)
        return {
            "success": True,
            "latency_ms": latency,
            "provider": "pixabay",
            "message": f"Pixabay download verified ({w}x{h} px)",
        }
    except Exception as e:
        latency = round((time.time() - t0) * 1000, 2)
        return {
            "success": False,
            "latency_ms": latency,
            "provider": "pixabay",
            "message": str(e),
        }


async def test_image_provider_connection() -> Dict[str, Any]:
    """Tests connectivity to configured optional AI image provider or returns status."""
    t0 = time.time()
    if settings.image_api_key and settings.image_base_url:
        try:
            raw = await _generate_ai_image("Minimalist test")
            with Image.open(io.BytesIO(raw)) as img:
                img.load()
            latency = round((time.time() - t0) * 1000, 2)
            return {
                "success": True,
                "latency_ms": latency,
                "provider": "ai_generation",
                "model": settings.image_model or "dall-e-3",
                "message": "AI image generation endpoint verified",
            }
        except Exception as e:
            latency = round((time.time() - t0) * 1000, 2)
            return {
                "success": False,
                "latency_ms": latency,
                "provider": "ai_generation",
                "message": str(e),
            }
    else:
        return {
            "success": True,
            "latency_ms": 0.0,
            "provider": "ai_generation",
            "message": "AI Image Generation is optional and not configured.",
        }
