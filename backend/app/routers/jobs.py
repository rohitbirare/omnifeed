import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from app.config import MEDIA_DIR, settings
from app.database import create_job, delete_job, get_job, list_jobs, update_job
from app.queue import enqueue_pipeline_job
from app.services.publish import publish_via_api

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])


class CreateJobRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=500)
    community_name: Optional[str] = ""
    community_description: Optional[str] = ""
    language: str = "en"
    tone: str = "Informative"
    target_length: int = 30
    visual_style: str = "Photographic"
    add_ai_disclosure: bool = True


class BatchJobRequest(BaseModel):
    topics: List[str] = Field(..., min_items=1, max_items=20)
    community_name: Optional[str] = ""
    community_description: Optional[str] = ""
    language: str = "en"
    tone: str = "Informative"
    target_length: int = 30
    visual_style: str = "Photographic"
    add_ai_disclosure: bool = True


class ConfirmPublishRequest(BaseModel):
    post_url: str = Field(..., min_length=4)


class SelectHookRequest(BaseModel):
    hook_index: int


@router.post("", status_code=201)
async def create_new_job(req: CreateJobRequest):
    job_id = str(uuid.uuid4())
    job_data = {
        "id": job_id,
        "topic": req.topic.strip(),
        "community_name": (req.community_name or "").strip(),
        "community_description": (req.community_description or "").strip(),
        "language": req.language,
        "tone": req.tone,
        "target_length": req.target_length,
        "visual_style": req.visual_style,
        "add_ai_disclosure": req.add_ai_disclosure,
        "status": "queued",
        "current_stage": "input",
        "stage_timings": {
            "input": {
                "start": round(datetime.now(timezone.utc).timestamp(), 3),
                "end": round(datetime.now(timezone.utc).timestamp(), 3),
                "duration_s": 0.0,
                "status": "completed",
            }
        },
    }

    created = create_job(job_data)
    enqueue_pipeline_job(job_id)
    return created


@router.post("/batch", status_code=201)
async def create_batch_jobs(req: BatchJobRequest):
    valid_topics = [t.strip() for t in req.topics if t and t.strip()]
    if not valid_topics:
        raise HTTPException(status_code=400, detail="No valid non-empty topics provided")

    created_jobs = []
    for topic in valid_topics:
        job_id = str(uuid.uuid4())
        job_data = {
            "id": job_id,
            "topic": topic,
            "community_name": (req.community_name or "").strip(),
            "community_description": (req.community_description or "").strip(),
            "language": req.language,
            "tone": req.tone,
            "target_length": req.target_length,
            "visual_style": req.visual_style,
            "add_ai_disclosure": req.add_ai_disclosure,
            "status": "queued",
            "current_stage": "input",
            "stage_timings": {
                "input": {
                    "start": round(datetime.now(timezone.utc).timestamp(), 3),
                    "end": round(datetime.now(timezone.utc).timestamp(), 3),
                    "duration_s": 0.0,
                    "status": "completed",
                }
            },
        }
        created = create_job(job_data)
        enqueue_pipeline_job(job_id)
        created_jobs.append(created)

    return {"count": len(created_jobs), "jobs": created_jobs}


@router.get("")
async def get_all_jobs(status: Optional[str] = Query(None)):
    return list_jobs(filter_status=status)


@router.get("/{job_id}")
async def get_job_by_id(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/retry")
async def retry_failed_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Keep completed stages so pipeline resumes from the failed stage
    timings = dict(job.get("stage_timings") or {})
    failed_st = job.get("current_stage")
    if failed_st and failed_st in timings and timings[failed_st].get("status") == "failed":
        del timings[failed_st]

    update_job(job_id, {
        "status": "queued",
        "error_message": "",
        "stage_timings": timings,
    })
    enqueue_pipeline_job(job_id)
    return get_job(job_id)


@router.post("/{job_id}/approve")
async def approve_flagged_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    new_status = "completed" if job.get("status") == "flagged" else job.get("status")
    updated = update_job(job_id, {
        "content_approved_by_user": True,
        "status": new_status,
    })
    return updated


@router.post("/{job_id}/publish")
async def publish_job_api(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Guard: safety check verification
    content_check = job.get("content_check", {})
    if content_check.get("flagged") and not job.get("content_approved_by_user"):
        raise HTTPException(
            status_code=400,
            detail="Content was flagged by automated safety check. Explicit user approval is required before publishing.",
        )

    video_p = Path(job.get("video_path", ""))
    if not video_p.exists():
        raise HTTPException(status_code=400, detail="Video file does not exist on disk")

    try:
        res = await publish_via_api(
            video_path=video_p,
            post_caption=job.get("post_caption", ""),
            title=job.get("title", ""),
        )
        updated = update_job(job_id, {
            "publish_mode": "api",
            "published_url": res.get("post_url", ""),
            "published_at": res.get("timestamp", datetime.now(timezone.utc).isoformat()),
            "published_response": res.get("response_body", "")[:1000],
        })
        return {
            "success": True,
            "status_code": res["status_code"],
            "published_url": res.get("post_url"),
            "job": updated,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{job_id}/confirm-published")
async def confirm_assisted_publish(job_id: str, req: ConfirmPublishRequest):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    clean_url = req.post_url.strip()
    updated = update_job(job_id, {
        "publish_mode": "assisted",
        "published_url": clean_url,
        "published_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"success": True, "job": updated}


@router.post("/{job_id}/select-hook")
async def select_alternative_hook(job_id: str, req: SelectHookRequest):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    hooks = job.get("hooks", [])
    if req.hook_index < 0 or req.hook_index >= len(hooks):
        raise HTTPException(status_code=400, detail="Invalid hook index")

    chosen = hooks[req.hook_index]
    updated = update_job(job_id, {
        "chosen_hook_index": req.hook_index,
        "hook_selection_reason": f"Selected by user: {chosen.get('hook', '')}",
    })
    return updated


@router.delete("/{job_id}")
async def remove_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Clean media files
    job_media_dir = MEDIA_DIR / job_id
    if job_media_dir.exists():
        shutil.rmtree(job_media_dir, ignore_errors=True)

    success = delete_job(job_id)
    return {"success": success, "id": job_id}
