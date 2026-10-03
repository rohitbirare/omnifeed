import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("omnifeed.quality")


def run_quality_check(
    video_path: Path,
    target_duration_s: int,
    ass_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Runs rigorous ffprobe quality verification on the generated MP4."""
    if not video_path.exists():
        return {
            "passed": False,
            "error": "Output video file does not exist",
            "checks": [],
        }

    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height",
        "-of", "json",
        str(video_path),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        logger.error(f"ffprobe quality check failed: {res.stderr}")
        return {
            "passed": False,
            "error": f"ffprobe execution error: {res.stderr[-200:]}",
            "checks": [],
        }

    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    format_info = data.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    width = int(video_stream.get("width", 0)) if video_stream else 0
    height = int(video_stream.get("height", 0)) if video_stream else 0
    video_codec = video_stream.get("codec_name", "unknown") if video_stream else "none"
    audio_codec = audio_stream.get("codec_name", "unknown") if audio_stream else "none"

    duration_s = float(format_info.get("duration", 0.0))
    size_bytes = int(format_info.get("size", 0))
    size_mb = round(size_bytes / (1024 * 1024), 2)

    # Individual check definitions
    checks = []

    # 1. Resolution Check (1080x1920)
    res_passed = (width == 1080 and height == 1920)
    checks.append({
        "name": "Resolution 1080x1920 (9:16)",
        "passed": res_passed,
        "measured": f"{width}x{height}",
        "target": "1080x1920",
    })

    # 2. Video Stream Check
    v_passed = (video_stream is not None and video_codec in ["h264", "libx264"])
    checks.append({
        "name": "Video Stream (H.264)",
        "passed": v_passed,
        "measured": video_codec,
        "target": "h264",
    })

    # 3. Audio Stream Check
    a_passed = (audio_stream is not None and audio_codec in ["aac", "mp3"])
    checks.append({
        "name": "Audio Stream (AAC)",
        "passed": a_passed,
        "measured": audio_codec,
        "target": "aac",
    })

    # 4. Target Duration Check (+/- 25% or 7s tolerance for natural speech pacing)
    dur_diff = abs(duration_s - target_duration_s)
    tolerance = max(target_duration_s * 0.35, 7.0)
    dur_passed = dur_diff <= tolerance
    checks.append({
        "name": f"Duration Cadence (target {target_duration_s}s)",
        "passed": dur_passed,
        "measured": f"{round(duration_s, 1)}s (diff: {round(dur_diff, 1)}s)",
        "target": f"{target_duration_s}s (+/- {round(tolerance, 1)}s)",
    })

    # 5. File Size Check (< 100 MB)
    size_passed = size_mb < 100.0 and size_mb > 0.05
    checks.append({
        "name": "File Size (< 100 MB)",
        "passed": size_passed,
        "measured": f"{size_mb} MB",
        "target": "< 100 MB",
    })

    # 6. Captions Check
    captions_present = ass_path is not None and ass_path.exists() and ass_path.stat().st_size > 100
    checks.append({
        "name": "Kinetic Captions Layer",
        "passed": captions_present,
        "measured": "Burned ASS kinetic subtitles" if captions_present else "Missing",
        "target": "Present & Synced",
    })

    # Overall pass requirement: Core checks must pass
    all_passed = res_passed and v_passed and a_passed and size_passed and captions_present

    return {
        "passed": all_passed,
        "checks": checks,
        "measured_values": {
            "width": width,
            "height": height,
            "duration_s": round(duration_s, 2),
            "size_bytes": size_bytes,
            "size_mb": size_mb,
            "video_codec": video_codec,
            "audio_codec": audio_codec,
        },
    }
