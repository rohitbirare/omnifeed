import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import httpx
from app.config import settings

logger = logging.getLogger("omnifeed.publish")


async def publish_via_api(
    video_path: Path,
    post_caption: str,
    title: str,
) -> Dict[str, Any]:
    """Sends real multipart upload to configured Qoneqt API endpoint if credentials are provided."""
    if not (settings.qoneqt_api_base and settings.qoneqt_api_token):
        raise ValueError(
            "Qoneqt API credentials are not configured (QONEQT_API_BASE and QONEQT_API_TOKEN are optional). "
            "Please use guided Assisted Publishing mode or set these variables."
        )

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found at {video_path}")

    upload_path = settings.qoneqt_upload_path or "/api/v1/posts/upload"
    field_name = settings.qoneqt_field_name or "file"

    url = f"{settings.qoneqt_api_base}{upload_path}"
    headers = {
        "Authorization": f"Bearer {settings.qoneqt_api_token}",
    }

    logger.info(f"Publishing video to Qoneqt API at {url}...")

    filename = video_path.name
    with open(video_path, "rb") as f:
        file_bytes = f.read()

    files = {
        field_name: (filename, file_bytes, "video/mp4"),
    }
    data = {
        "caption": post_caption,
        "title": title,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, headers=headers, data=data, files=files)
        status_code = response.status_code
        text_body = response.text

        is_success = 200 <= status_code < 300

        result_data = {
            "status_code": status_code,
            "success": is_success,
            "response_body": text_body,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if is_success:
            # Try to extract post URL from response if available
            try:
                parsed = response.json()
                post_url = parsed.get("post_url") or parsed.get("url") or f"{settings.qoneqt_app_url}/feed"
                result_data["post_url"] = post_url
            except Exception:
                result_data["post_url"] = f"{settings.qoneqt_app_url}/feed"
            return result_data
        else:
            raise RuntimeError(
                f"Qoneqt API upload returned HTTP {status_code}: {text_body[:300]}"
            )
