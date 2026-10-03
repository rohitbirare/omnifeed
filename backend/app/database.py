import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.config import DB_PATH


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        topic TEXT NOT NULL,
        community_name TEXT DEFAULT '',
        community_description TEXT DEFAULT '',
        language TEXT DEFAULT 'en',
        tone TEXT DEFAULT 'Informative',
        target_length INTEGER DEFAULT 30,
        visual_style TEXT DEFAULT 'Photographic',
        add_ai_disclosure INTEGER DEFAULT 1,
        status TEXT DEFAULT 'queued',
        current_stage TEXT DEFAULT 'input',
        stage_timings TEXT DEFAULT '{}',
        total_duration_s REAL DEFAULT 0.0,
        error_message TEXT DEFAULT '',
        hooks TEXT DEFAULT '[]',
        chosen_hook_index INTEGER DEFAULT 0,
        hook_selection_reason TEXT DEFAULT '',
        script_text TEXT DEFAULT '',
        title TEXT DEFAULT '',
        post_caption TEXT DEFAULT '',
        hashtags TEXT DEFAULT '[]',
        scenes TEXT DEFAULT '[]',
        content_check TEXT DEFAULT '{}',
        content_approved_by_user INTEGER DEFAULT 0,
        audio_path TEXT DEFAULT '',
        video_path TEXT DEFAULT '',
        thumbnail_path TEXT DEFAULT '',
        quality_report TEXT DEFAULT '{}',
        publish_mode TEXT DEFAULT 'none',
        published_url TEXT DEFAULT '',
        published_at TEXT DEFAULT '',
        published_response TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    # Recover unfinished jobs on server startup
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        UPDATE jobs
        SET status = 'failed',
            error_message = 'Interrupted by server restart',
            updated_at = ?
        WHERE status IN ('queued', 'processing')
    """, (now,))

    conn.commit()
    conn.close()


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    # Parse JSON fields safely
    for key in ["stage_timings", "hooks", "hashtags", "scenes", "content_check", "quality_report"]:
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except Exception:
                d[key] = {} if key in ["stage_timings", "content_check", "quality_report"] else []
        else:
            d[key] = {} if key in ["stage_timings", "content_check", "quality_report"] else []
    
    d["add_ai_disclosure"] = bool(d.get("add_ai_disclosure", 1))
    d["content_approved_by_user"] = bool(d.get("content_approved_by_user", 0))
    return d


def create_job(job: Dict[str, Any]) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()

    now = datetime.now(timezone.utc).isoformat()
    job["created_at"] = now
    job["updated_at"] = now

    cursor.execute("""
        INSERT INTO jobs (
            id, topic, community_name, community_description, language,
            tone, target_length, visual_style, add_ai_disclosure, status,
            current_stage, stage_timings, total_duration_s, error_message,
            hooks, chosen_hook_index, hook_selection_reason, script_text,
            title, post_caption, hashtags, scenes, content_check,
            content_approved_by_user, audio_path, video_path, thumbnail_path,
            quality_report, publish_mode, published_url, published_at,
            published_response, created_at, updated_at
        ) VALUES (
            :id, :topic, :community_name, :community_description, :language,
            :tone, :target_length, :visual_style, :add_ai_disclosure, :status,
            :current_stage, :stage_timings, :total_duration_s, :error_message,
            :hooks, :chosen_hook_index, :hook_selection_reason, :script_text,
            :title, :post_caption, :hashtags, :scenes, :content_check,
            :content_approved_by_user, :audio_path, :video_path, :thumbnail_path,
            :quality_report, :publish_mode, :published_url, :published_at,
            :published_response, :created_at, :updated_at
        )
    """, {
        "id": job["id"],
        "topic": job.get("topic", ""),
        "community_name": job.get("community_name", ""),
        "community_description": job.get("community_description", ""),
        "language": job.get("language", "en"),
        "tone": job.get("tone", "Informative"),
        "target_length": job.get("target_length", 30),
        "visual_style": job.get("visual_style", "Photographic"),
        "add_ai_disclosure": 1 if job.get("add_ai_disclosure", True) else 0,
        "status": job.get("status", "queued"),
        "current_stage": job.get("current_stage", "input"),
        "stage_timings": json.dumps(job.get("stage_timings", {})),
        "total_duration_s": job.get("total_duration_s", 0.0),
        "error_message": job.get("error_message", ""),
        "hooks": json.dumps(job.get("hooks", [])),
        "chosen_hook_index": job.get("chosen_hook_index", 0),
        "hook_selection_reason": job.get("hook_selection_reason", ""),
        "script_text": job.get("script_text", ""),
        "title": job.get("title", ""),
        "post_caption": job.get("post_caption", ""),
        "hashtags": json.dumps(job.get("hashtags", [])),
        "scenes": json.dumps(job.get("scenes", [])),
        "content_check": json.dumps(job.get("content_check", {})),
        "content_approved_by_user": 1 if job.get("content_approved_by_user", False) else 0,
        "audio_path": job.get("audio_path", ""),
        "video_path": job.get("video_path", ""),
        "thumbnail_path": job.get("thumbnail_path", ""),
        "quality_report": json.dumps(job.get("quality_report", {})),
        "publish_mode": job.get("publish_mode", "none"),
        "published_url": job.get("published_url", ""),
        "published_at": job.get("published_at", ""),
        "published_response": job.get("published_response", ""),
        "created_at": now,
        "updated_at": now,
    })

    conn.commit()
    conn.close()
    return get_job(job["id"])  # type: ignore


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row_to_dict(row)
    return None


def list_jobs(filter_status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    if filter_status and filter_status != "all":
        cursor.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (filter_status, limit)
        )
    else:
        cursor.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
    rows = cursor.fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]


def update_job(job_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    json_keys = {"stage_timings", "hooks", "hashtags", "scenes", "content_check", "quality_report"}
    bool_keys = {"add_ai_disclosure", "content_approved_by_user"}

    set_clauses = []
    params = []
    for k, v in updates.items():
        if k in json_keys:
            set_clauses.append(f"{k} = ?")
            params.append(json.dumps(v))
        elif k in bool_keys:
            set_clauses.append(f"{k} = ?")
            params.append(1 if v else 0)
        else:
            set_clauses.append(f"{k} = ?")
            params.append(v)

    params.append(job_id)
    query = f"UPDATE jobs SET {', '.join(set_clauses)} WHERE id = ?"
    cursor.execute(query, params)
    conn.commit()
    conn.close()
    return get_job(job_id)


def delete_job(job_id: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0
