import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
from PIL import Image

logger = logging.getLogger("omnifeed.render")


def _get_last_20_lines(stderr_text: str) -> str:
    """Extracts up to the last 20 lines of FFmpeg stderr for crisp debugging."""
    lines = [line.strip() for line in stderr_text.strip().splitlines() if line.strip()]
    return "\n".join(lines[-20:]) if lines else "No stderr output captured"


def render_scene_clip(
    image_path: Path,
    duration_s: float,
    output_clip_path: Path,
    scene_index: int = 1,
) -> Path:
    """Renders a single scene image into an MP4 clip with subtle Ken Burns motion."""
    output_clip_path.parent.mkdir(parents=True, exist_ok=True)
    fps = 30
    total_frames = max(int(duration_s * fps), 30)

    # Alternate gentle zoom speeds and direction slightly
    if scene_index % 2 == 1:
        vf_filter = (
            f"zoompan=z='min(zoom+0.0008,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={total_frames}:s=1080x1920:fps={fps}"
        )
    else:
        vf_filter = (
            f"zoompan=z='min(zoom+0.0006,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={total_frames}:s=1080x1920:fps={fps}"
        )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-vf", vf_filter,
        "-t", str(duration_s),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "veryfast",
        "-r", str(fps),
        str(output_clip_path),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        err_excerpt = _get_last_20_lines(res.stderr)
        logger.error(f"FFmpeg error rendering scene {scene_index}:\n{err_excerpt}")
        raise RuntimeError(f"FFmpeg failed to render scene clip #{scene_index}:\n{err_excerpt}")

    return output_clip_path


def assemble_final_video(
    scene_clips: List[Path],
    audio_path: Path,
    subtitle_path: Path,
    output_video_path: Path,
    output_thumb_path: Path,
) -> Tuple[Path, Path]:
    """Concatenates scene clips, adds narration audio, burns ASS captions, and outputs 9:16 MP4."""
    output_video_path.parent.mkdir(parents=True, exist_ok=True)
    job_dir = output_video_path.parent

    concat_txt_path = job_dir / "concat_scenes.txt"
    with open(concat_txt_path, "w", encoding="utf-8") as f:
        for clip in scene_clips:
            clean_path = str(clip.resolve()).replace("\\", "/")
            f.write(f"file '{clean_path}'\n")

    temp_raw_video = job_dir / "temp_raw_video.mp4"

    # Step 1: Concatenate clips losslessly
    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_txt_path),
        "-c", "copy",
        str(temp_raw_video),
    ]
    res_concat = subprocess.run(concat_cmd, capture_output=True, text=True)
    if res_concat.returncode != 0:
        err_excerpt = _get_last_20_lines(res_concat.stderr)
        logger.error(f"FFmpeg concat failed:\n{err_excerpt}")
        raise RuntimeError(f"FFmpeg concat failed:\n{err_excerpt}")

    # Step 2: Mux audio and burn ASS subtitles with safe path escaping
    # Convert backslashes to forward slashes, escape colons for ffmpeg filtergraph
    clean_sub = str(subtitle_path.resolve()).replace("\\", "/").replace(":", "\\:")
    burn_cmd = [
        "ffmpeg", "-y",
        "-i", str(temp_raw_video),
        "-i", str(audio_path),
        "-vf", f"ass='{clean_sub}'",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-r", "30",
        "-shortest",
        "-movflags", "+faststart",
        str(output_video_path),
    ]

    res_burn = subprocess.run(burn_cmd, capture_output=True, text=True)
    if res_burn.returncode != 0:
        err_excerpt = _get_last_20_lines(res_burn.stderr)
        logger.error(f"FFmpeg burn/mux failed:\n{err_excerpt}")
        raise RuntimeError(f"FFmpeg burn/mux failed:\n{err_excerpt}")

    # Step 3: Produce high quality JPG thumbnail at 1.5s
    thumb_cmd = [
        "ffmpeg", "-y",
        "-ss", "00:00:01.500",
        "-i", str(output_video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_thumb_path),
    ]
    res_thumb = subprocess.run(thumb_cmd, capture_output=True, text=True)
    if res_thumb.returncode != 0 or not output_thumb_path.exists():
        # Fallback to frame 0.2s
        subprocess.run([
            "ffmpeg", "-y",
            "-ss", "00:00:00.200",
            "-i", str(output_video_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(output_thumb_path),
        ], capture_output=True)

    # Clean temporary intermediate files to conserve disk space
    if concat_txt_path.exists():
        concat_txt_path.unlink()
    if temp_raw_video.exists():
        temp_raw_video.unlink()
    for sc in scene_clips:
        if sc.exists():
            sc.unlink()

    return output_video_path, output_thumb_path


def test_ffmpeg_caption_burn() -> Dict[str, Any]:
    """Tests burning an ASS caption into a short test clip for the status self-test."""
    t0 = time.time()
    temp_dir = Path("./data/temp")
    temp_dir.mkdir(parents=True, exist_ok=True)

    test_img_path = temp_dir / "selftest_img.jpg"
    test_clip_path = temp_dir / "selftest_clip.mp4"
    test_ass_path = temp_dir / "selftest.ass"
    test_out_path = temp_dir / "selftest_burned.mp4"

    try:
        # Create minimal 1080x1920 image
        img = Image.new("RGB", (1080, 1920), color=(15, 23, 42))
        img.save(test_img_path)

        # Render 1.5s clip
        cmd_clip = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(test_img_path),
            "-t", "1.5",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            str(test_clip_path),
        ]
        r1 = subprocess.run(cmd_clip, capture_output=True, text=True)
        if r1.returncode != 0:
            raise RuntimeError(f"Clip generation failed: {_get_last_20_lines(r1.stderr)}")

        # Create test ASS
        ass_content = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,320,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.50,Default,,0,0,0,,{\\c&H00A6B814&}OmniFeed{\\c&H00FFFFFF&} Self-Test
"""
        test_ass_path.write_text(ass_content, encoding="utf-8")

        # Burn ASS subtitle
        clean_sub = str(test_ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
        cmd_burn = [
            "ffmpeg", "-y",
            "-i", str(test_clip_path),
            "-vf", f"ass='{clean_sub}'",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(test_out_path),
        ]
        r2 = subprocess.run(cmd_burn, capture_output=True, text=True)
        if r2.returncode != 0:
            raise RuntimeError(f"Caption burn failed: {_get_last_20_lines(r2.stderr)}")

        latency = round((time.time() - t0) * 1000, 2)
        return {
            "success": True,
            "latency_ms": latency,
            "message": "FFmpeg ASS caption burn and mux verified",
        }
    except Exception as e:
        latency = round((time.time() - t0) * 1000, 2)
        return {
            "success": False,
            "latency_ms": latency,
            "message": str(e),
        }
    finally:
        for p in [test_img_path, test_clip_path, test_ass_path, test_out_path]:
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
