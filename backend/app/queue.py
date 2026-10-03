import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from app.config import MEDIA_DIR, settings
from app.database import get_job, update_job
from app.services.captions import build_ass_subtitle_file
from app.services.images import generate_all_scene_images
from app.services.llm import check_content_safety, generate_script_and_scenes
from app.services.quality import run_quality_check
from app.services.render import assemble_final_video, render_scene_clip
from app.services.tts import calculate_scene_durations, synthesize_voice

logger = logging.getLogger("omnifeed.queue")

_executor: Optional[ThreadPoolExecutor] = None


def get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=settings.max_concurrent_renders,
            thread_name_prefix="omnifeed-worker",
        )
    return _executor


async def execute_pipeline(job_id: str):
    """Executes or resumes the 9-stage video production pipeline from the failed stage."""
    job = get_job(job_id)
    if not job:
        logger.error(f"Pipeline invoked for non-existent job {job_id}")
        return

    job_media_dir = MEDIA_DIR / job_id
    job_media_dir.mkdir(parents=True, exist_ok=True)

    stage_timings: Dict[str, Dict[str, Any]] = dict(job.get("stage_timings") or {})
    t_pipeline_start = time.time()
    current_active_stage = "input"

    def record_stage_start(stage_name: str):
        nonlocal current_active_stage
        current_active_stage = stage_name
        stage_timings[stage_name] = {
            "start": round(time.time(), 3),
            "status": "processing",
        }
        update_job(job_id, {
            "status": "processing",
            "current_stage": stage_name,
            "stage_timings": stage_timings,
        })

    def record_stage_end(stage_name: str, success: bool = True, err_msg: str = ""):
        now = time.time()
        start = stage_timings.get(stage_name, {}).get("start", now)
        stage_timings[stage_name] = {
            "start": start,
            "end": round(now, 3),
            "duration_s": round(now - start, 2),
            "status": "completed" if success else "failed",
            "error": err_msg,
        }
        update_job(job_id, {"stage_timings": stage_timings})

    def is_stage_completed(stage_name: str) -> bool:
        return stage_timings.get(stage_name, {}).get("status") == "completed"

    try:
        # Load state from DB
        full_script = job.get("script_text", "")
        scenes = list(job.get("scenes") or [])
        audio_file = job_media_dir / "narration.mp3"
        timings_file = job_media_dir / "word_timings.json"
        ass_file = job_media_dir / "captions.ass"
        final_video_file = job_media_dir / "video.mp4"
        thumbnail_file = job_media_dir / "thumbnail.jpg"

        # -------------------------------------------------------------
        # STAGE 2: LLM Scripting, Hook Selection, Scene Planning
        # -------------------------------------------------------------
        if not (is_stage_completed("llm_script") and full_script and len(scenes) >= 3):
            record_stage_start("llm_script")
            script_data = generate_script_and_scenes(
                topic=job["topic"],
                community_name=job.get("community_name", ""),
                community_description=job.get("community_description", ""),
                language=job.get("language", "en"),
                tone=job.get("tone", "Informative"),
                target_length=job.get("target_length", 30),
                visual_style=job.get("visual_style", "Photographic"),
                add_ai_disclosure=job.get("add_ai_disclosure", True),
            )

            hooks = script_data.get("hooks", [])
            chosen_hook_idx = int(script_data.get("chosen_hook_index", 0))
            reason = script_data.get("hook_selection_reason", "")
            full_script = script_data.get("full_script", "")
            scenes = script_data.get("scenes", [])
            title = script_data.get("title", job["topic"])
            post_caption = script_data.get("post_caption", "")
            hashtags = script_data.get("hashtags", [])

            update_job(job_id, {
                "hooks": hooks,
                "chosen_hook_index": chosen_hook_idx,
                "hook_selection_reason": reason,
                "script_text": full_script,
                "scenes": scenes,
                "title": title,
                "post_caption": post_caption,
                "hashtags": hashtags,
            })
            record_stage_end("llm_script", True)
        else:
            logger.info(f"Resuming job {job_id}: llm_script already completed")

        # -------------------------------------------------------------
        # STAGE 3: Content Moderation & Claim Safety Verification
        # -------------------------------------------------------------
        content_check = job.get("content_check") or {}
        if not (is_stage_completed("content_check") and content_check):
            record_stage_start("content_check")
            safety_result = check_content_safety(
                topic=job["topic"],
                script_text=full_script,
                scenes=scenes,
            )
            update_job(job_id, {"content_check": safety_result})
            record_stage_end("content_check", True)
            content_check = safety_result
        else:
            logger.info(f"Resuming job {job_id}: content_check already completed")

        is_flagged = content_check.get("flagged", False)

        # -------------------------------------------------------------
        # STAGE 4: Voice Synthesis & Word Boundaries
        # -------------------------------------------------------------
        word_timings = []
        if not (is_stage_completed("tts_voice") and audio_file.exists() and timings_file.exists()):
            record_stage_start("tts_voice")
            audio_duration_s, word_timings = await synthesize_voice(
                text=full_script,
                language=job.get("language", "en"),
                output_audio_path=audio_file,
                output_timings_path=timings_file,
            )

            # Allocate per-scene durations matching speech
            scenes = calculate_scene_durations(scenes, word_timings, audio_duration_s)
            update_job(job_id, {
                "audio_path": str(audio_file),
                "scenes": scenes,
            })
            record_stage_end("tts_voice", True)
        else:
            logger.info(f"Resuming job {job_id}: tts_voice already completed")
            import json
            if timings_file.exists():
                try:
                    t_data = json.loads(timings_file.read_text(encoding="utf-8"))
                    word_timings = t_data.get("words", [])
                except Exception:
                    pass

        # -------------------------------------------------------------
        # STAGE 5: Visuals Generation / Fetching (parallel max 3)
        # -------------------------------------------------------------
        all_visuals_exist = all(
            Path(s.get("visual_path", "")).exists() for s in scenes
        ) if scenes else False

        if not (is_stage_completed("visuals") and all_visuals_exist):
            record_stage_start("visuals")
            scenes = await generate_all_scene_images(
                scenes=scenes,
                visual_style=job.get("visual_style", "Photographic"),
                topic=job["topic"],
                media_dir=job_media_dir,
                max_concurrency=3,
            )
            update_job(job_id, {"scenes": scenes})
            record_stage_end("visuals", True)
        else:
            logger.info(f"Resuming job {job_id}: visuals already completed")

        # -------------------------------------------------------------
        # STAGE 6: Kinetic Captions ASS Subtitles
        # -------------------------------------------------------------
        if not (is_stage_completed("captions") and ass_file.exists() and ass_file.stat().st_size > 50):
            record_stage_start("captions")
            build_ass_subtitle_file(
                word_timings=word_timings,
                language=job.get("language", "en"),
                output_ass_path=ass_file,
            )
            record_stage_end("captions", True)
        else:
            logger.info(f"Resuming job {job_id}: captions already completed")

        # -------------------------------------------------------------
        # STAGE 7: Headless FFmpeg Assembly (Zoompan + Concat + Burn)
        # -------------------------------------------------------------
        if not (is_stage_completed("ffmpeg_render") and final_video_file.exists() and thumbnail_file.exists()):
            record_stage_start("ffmpeg_render")
            scene_clip_paths = []
            for idx, sc in enumerate(scenes):
                img_p = Path(sc["visual_path"])
                dur_p = float(sc.get("duration_s", 4.0))
                clip_out = job_media_dir / f"scene_{sc['scene_id']}_clip.mp4"
                render_scene_clip(
                    image_path=img_p,
                    duration_s=dur_p,
                    output_clip_path=clip_out,
                    scene_index=idx + 1,
                )
                scene_clip_paths.append(clip_out)

            assemble_final_video(
                scene_clips=scene_clip_paths,
                audio_path=audio_file,
                subtitle_path=ass_file,
                output_video_path=final_video_file,
                output_thumb_path=thumbnail_file,
            )

            update_job(job_id, {
                "video_path": str(final_video_file),
                "thumbnail_path": str(thumbnail_file),
            })
            record_stage_end("ffmpeg_render", True)
        else:
            logger.info(f"Resuming job {job_id}: ffmpeg_render already completed")

        # -------------------------------------------------------------
        # STAGE 8: Automated Quality Check via ffprobe
        # -------------------------------------------------------------
        record_stage_start("quality_check")
        target_len = int(job.get("target_length", 30))
        q_report = run_quality_check(
            video_path=final_video_file,
            target_duration_s=target_len,
            ass_path=ass_file,
        )
        update_job(job_id, {"quality_report": q_report})

        if not q_report.get("passed", False):
            err_details = q_report.get("error") or "Video failed core technical quality requirements"
            record_stage_end("quality_check", False, err_details)
            raise RuntimeError(f"Quality Check Failed: {err_details}")

        record_stage_end("quality_check", True)

        # -------------------------------------------------------------
        # STAGE 9: Ready & Final Telemetry Calculation
        # -------------------------------------------------------------
        total_time = round(time.time() - t_pipeline_start, 2)
        final_status = "flagged" if is_flagged else "completed"

        stage_timings["ready"] = {
            "start": round(time.time(), 3),
            "end": round(time.time(), 3),
            "duration_s": 0.0,
            "status": "completed",
        }

        update_job(job_id, {
            "status": final_status,
            "current_stage": "ready",
            "total_duration_s": total_time,
            "stage_timings": stage_timings,
            "error_message": "",
        })

        logger.info(
            f"Successfully finished job {job_id} in {total_time}s with status '{final_status}'"
        )

    except Exception as e:
        logger.exception(f"Job {job_id} encountered fatal pipeline error at stage {current_active_stage}: {str(e)}")
        now_t = time.time()
        start_t = stage_timings.get(current_active_stage, {}).get("start", now_t)
        stage_timings[current_active_stage] = {
            "start": start_t,
            "end": round(now_t, 3),
            "duration_s": round(now_t - start_t, 2),
            "status": "failed",
            "error": str(e),
        }

        update_job(job_id, {
            "status": "failed",
            "current_stage": current_active_stage,
            "error_message": str(e),
            "stage_timings": stage_timings,
            "total_duration_s": round(now_t - t_pipeline_start, 2),
        })


def enqueue_pipeline_job(job_id: str):
    """Schedules the pipeline execution inside the asyncio event loop."""
    asyncio.create_task(execute_pipeline(job_id))
