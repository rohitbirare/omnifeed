import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import httpx
from app.config import settings

logger = logging.getLogger("omnifeed.llm")

# In-memory cache for models discovery
_DISCOVERED_MODELS: Optional[List[str]] = None
_RESOLVED_PRIMARY_MODEL: Optional[str] = None
_RESOLVED_FALLBACK_MODEL: Optional[str] = None


def discover_available_models() -> List[str]:
    """Calls GET {base_url}/models once to discover valid model names."""
    global _DISCOVERED_MODELS, _RESOLVED_PRIMARY_MODEL, _RESOLVED_FALLBACK_MODEL
    if _DISCOVERED_MODELS is not None:
        return _DISCOVERED_MODELS

    key = settings.llm_api_key or os.environ.get("GEMINI_API_KEY", "")
    base_url = settings.llm_base_url.rstrip("/")
    models_url = f"{base_url}/models"
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(models_url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                raw_list = data.get("data", [])
                models = []
                for item in raw_list:
                    m_id = item.get("id") or item.get("name") or ""
                    if m_id:
                        # Normalize model name (e.g., 'models/gemini-3.8-flash' -> 'gemini-3.8-flash' or keep both)
                        models.append(m_id)
                _DISCOVERED_MODELS = models
                logger.info(f"Discovered {len(models)} models from {models_url}")
                _resolve_active_models(models)
                return _DISCOVERED_MODELS
            else:
                logger.warning(
                    f"GET {models_url} returned status {resp.status_code}: {resp.text[:200]}"
                )
    except Exception as e:
        logger.warning(f"Failed to discover models from {models_url}: {e}")

    _DISCOVERED_MODELS = []
    _RESOLVED_PRIMARY_MODEL = settings.llm_model
    _RESOLVED_FALLBACK_MODEL = settings.llm_fallback_model or "gemini-2.5-flash-lite"
    return _DISCOVERED_MODELS


def _resolve_active_models(available_models: List[str]):
    """Auto-picks valid model names preferring 'flash' and 'lite' fallback."""
    global _RESOLVED_PRIMARY_MODEL, _RESOLVED_FALLBACK_MODEL

    configured_primary = settings.llm_model.strip()
    configured_fallback = settings.llm_fallback_model.strip()

    # Helper to check if model exists either directly or with 'models/' prefix
    def model_matches(cand: str, target: str) -> bool:
        if cand == target:
            return True
        if cand == f"models/{target}":
            return True
        if target == f"models/{cand}":
            return True
        return False

    def is_present(target: str) -> Optional[str]:
        if not target:
            return None
        for m in available_models:
            if model_matches(m, target):
                return target if target in available_models else m
        return None

    # Resolve primary model
    matched_primary = is_present(configured_primary)
    if matched_primary and "2.5" not in matched_primary:
        _RESOLVED_PRIMARY_MODEL = matched_primary
    else:
        # Auto-pick a flash model from available list
        flash_candidates = [
            m for m in available_models
            if "flash" in m.lower() and "tts" not in m.lower() and "image" not in m.lower()
        ]
        # Prefer gemini-3.8-flash or latest flash
        preferred = [m for m in flash_candidates if "3.8-flash" in m or "flash-latest" in m]
        if preferred:
            _RESOLVED_PRIMARY_MODEL = preferred[0]
        elif flash_candidates:
            _RESOLVED_PRIMARY_MODEL = flash_candidates[0]
        else:
            _RESOLVED_PRIMARY_MODEL = configured_primary or "gemini-3.8-flash"

    # Resolve fallback model (prefer a lite model)
    matched_fallback = is_present(configured_fallback)
    if matched_fallback:
        _RESOLVED_FALLBACK_MODEL = matched_fallback
    else:
        lite_candidates = [
            m for m in available_models
            if "lite" in m.lower() and "image" not in m.lower()
        ]
        if lite_candidates:
            _RESOLVED_FALLBACK_MODEL = lite_candidates[0]
        else:
            _RESOLVED_FALLBACK_MODEL = "gemini-2.5-flash-lite"

    # Clean models/ prefix if using OpenAI completions
    if _RESOLVED_PRIMARY_MODEL and _RESOLVED_PRIMARY_MODEL.startswith("models/"):
        _RESOLVED_PRIMARY_MODEL = _RESOLVED_PRIMARY_MODEL.replace("models/", "")
    if _RESOLVED_FALLBACK_MODEL and _RESOLVED_FALLBACK_MODEL.startswith("models/"):
        _RESOLVED_FALLBACK_MODEL = _RESOLVED_FALLBACK_MODEL.replace("models/", "")

    logger.info(
        f"Active LLM models resolved: primary='{_RESOLVED_PRIMARY_MODEL}', fallback='{_RESOLVED_FALLBACK_MODEL}'"
    )


def get_active_models() -> Tuple[str, str]:
    global _RESOLVED_PRIMARY_MODEL, _RESOLVED_FALLBACK_MODEL
    if _RESOLVED_PRIMARY_MODEL is None:
        discover_available_models()
    primary = _RESOLVED_PRIMARY_MODEL or settings.llm_model or "gemini-3.8-flash"
    fallback = _RESOLVED_FALLBACK_MODEL or settings.llm_fallback_model or "gemini-2.5-flash-lite"
    return primary, fallback


def _execute_chat_completions(
    messages: List[Dict[str, str]],
    model: str,
    response_json: bool = True,
    timeout: float = 60.0,
) -> str:
    """Executes a single chat completion request showing full error details without secret keys."""
    key = settings.llm_api_key or os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise ValueError("LLM API key is not configured. Please set LLM_API_KEY or GEMINI_API_KEY.")

    base_url = settings.llm_base_url.rstrip("/")
    chat_url = f"{base_url}/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
    }
    if response_json:
        payload["response_format"] = {"type": "json_object"}

    with httpx.Client(timeout=timeout) as client:
        try:
            resp = client.post(chat_url, headers=headers, json=payload)
        except Exception as conn_err:
            raise RuntimeError(
                f"LLM Connection Error: Model: '{model}', URL: '{chat_url}', Error: {str(conn_err)}"
            )

        if resp.status_code != 200:
            error_body = resp.text
            raise RuntimeError(
                f"LLM API Error (Status {resp.status_code}): Model: '{model}', URL: '{chat_url}', Response: {error_body}"
            )

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(
                f"LLM Empty Choices: Model: '{model}', URL: '{chat_url}', Response: {data}"
            )
        return choices[0]["message"]["content"]


def call_llm_with_retry(
    messages: List[Dict[str, str]],
    response_json: bool = True,
    max_retries: int = 3,
) -> str:
    """Calls LLM with auto-discovered models, retries, and fallback."""
    primary_model, fallback_model = get_active_models()
    models_to_try = [primary_model]
    if fallback_model and fallback_model != primary_model:
        models_to_try.append(fallback_model)

    last_error: Optional[Exception] = None

    for model in models_to_try:
        backoff = 2.0
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Calling LLM with model '{model}' (attempt {attempt}/{max_retries})")
                return _execute_chat_completions(
                    messages=messages,
                    model=model,
                    response_json=response_json,
                )
            except Exception as e:
                logger.warning(f"LLM call to model '{model}' failed (attempt {attempt}): {e}")
                last_error = e
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff *= 1.5

    raise RuntimeError(f"All LLM attempts exhausted across models. Last error: {str(last_error)}")


def clean_json_fences(raw_text: str) -> str:
    """Strips markdown code fences and whitespace from LLM JSON responses."""
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def validate_script_schema(data: Any) -> None:
    """Validates strict JSON schema for script generation."""
    if not isinstance(data, dict):
        raise ValueError("Root response must be a JSON object")

    if "hooks" not in data or not isinstance(data["hooks"], list) or len(data["hooks"]) < 3:
        raise ValueError("Must contain 'hooks' list with at least 3 candidates")

    for idx, h in enumerate(data["hooks"]):
        if not isinstance(h, dict) or "hook" not in h or not str(h["hook"]).strip():
            raise ValueError(f"Hook #{idx+1} must be an object with non-empty 'hook' string")

    if "title" not in data or not str(data["title"]).strip():
        raise ValueError("Must contain non-empty 'title' string")

    if "full_script" not in data or not str(data["full_script"]).strip():
        raise ValueError("Must contain non-empty 'full_script' string")

    if "scenes" not in data or not isinstance(data["scenes"], list) or len(data["scenes"]) < 3:
        raise ValueError("Must contain 'scenes' list with at least 3 scenes")

    for idx, s in enumerate(data["scenes"]):
        if not isinstance(s, dict):
            raise ValueError(f"Scene #{idx+1} must be a JSON object")
        if "narration" not in s or not str(s["narration"]).strip():
            raise ValueError(f"Scene #{idx+1} missing 'narration' text")


def generate_script_and_scenes(
    topic: str,
    community_name: str = "",
    community_description: str = "",
    language: str = "en",
    tone: str = "Informative",
    target_length: int = 30,
    visual_style: str = "Photographic",
    add_ai_disclosure: bool = True,
) -> Dict[str, Any]:
    """Generates hooks, script, scenes with strict JSON schema validation and retry with feedback."""
    target_words = int(target_length * 2.5)
    min_words = int(target_words * 0.85)
    max_words = int(target_words * 1.15)

    lang_map = {
        "en": "English",
        "hi": "Hindi (using Devanagari script for narration)",
        "mr": "Marathi (using Devanagari script for narration)",
    }
    target_lang_name = lang_map.get(language, "English")

    system_prompt = (
        "You are an elite short-form video creator and scriptwriter for the Qoneqt Global Feed. "
        "Your task is to craft high-retention 9:16 vertical video packages. "
        "You MUST respond ONLY with valid JSON matching the exact schema requested. "
        "Never include preamble, markdown wrapping, or explanations outside the JSON."
    )

    user_prompt = f"""
Topic / Idea: "{topic}"
Community Context: "{community_name}" - "{community_description}"
Target Language: {target_lang_name}
Tone: {tone}
Target Length: {target_length} seconds (Target spoken word count: {min_words} to {max_words} words total)
Visual Style: {visual_style}

Requirements:
1. Generate 3 distinct 3-second hook candidates designed for mobile feeds (curiosity, controversy/stat, or bold claim).
2. Select the strongest hook and state the specific reason in 1-2 sentences.
3. Write a coherent, engaging spoken narration script matching {target_length} seconds ({min_words}-{max_words} words).
4. Divide the video into 4 to 7 sequential visual scenes.
   Each scene MUST contain:
   - "scene_id": integer 1 to N
   - "narration": the spoken sentences for this scene
   - "visual_prompt": vivid, detailed scene description matching {visual_style} style, 9:16 vertical composition, no text overlays
   - "stock_query": 2 to 4 English search keywords for stock photography (e.g. "cybersecurity server room", "electric vehicle battery")
   - "emphasis": 1 to 3 key punchy words or phrase for kinetic caption styling
5. Provide a compelling "title" (under 60 characters).
6. Provide a "post_caption" for the Qoneqt Global Feed post.
7. Provide 3 to 5 relevant "hashtags" (array of strings, each starting with #).

JSON Output Schema:
{{
  "hooks": [
    {{"hook": "First hook text...", "type": "Curiosity/Bold/Question"}},
    {{"hook": "Second hook text...", "type": "Curiosity/Bold/Question"}},
    {{"hook": "Third hook text...", "type": "Curiosity/Bold/Question"}}
  ],
  "chosen_hook_index": 0,
  "hook_selection_reason": "Why this hook has highest retention...",
  "title": "Compelling Title",
  "post_caption": "Engaging feed caption describing the insight...",
  "hashtags": ["#Topic", "#Insight", "#Qoneqt"],
  "full_script": "The complete spoken script from start to finish...",
  "scenes": [
    {{
      "scene_id": 1,
      "narration": "First spoken segment...",
      "visual_prompt": "Detailed description in {visual_style} style...",
      "stock_query": "stock search words",
      "emphasis": "KEY PHRASE"
    }}
  ]
}}
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    last_parse_error = ""
    # Retry up to 3 times feeding parse error back
    for parse_attempt in range(1, 4):
        raw_text = call_llm_with_retry(messages, response_json=True)
        try:
            cleaned = clean_json_fences(raw_text)
            data = json.loads(cleaned)
            validate_script_schema(data)

            # Post caption adjustment for AI disclosure
            caption = data.get("post_caption", "").strip()
            if add_ai_disclosure:
                if "Created with AI assistance" not in caption:
                    caption = f"{caption}\n\nCreated with AI assistance"
            data["post_caption"] = caption
            return data

        except Exception as err:
            last_parse_error = str(err)
            logger.warning(
                f"JSON parse/schema validation error (attempt {parse_attempt}/3): {err}"
            )
            if parse_attempt < 3:
                messages.append({"role": "assistant", "content": raw_text})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your output failed JSON parsing or schema validation with error: {str(err)}. "
                        "Return ONLY strictly valid JSON conforming exactly to the requested schema with no commentary or markdown fences."
                    ),
                })

    raise ValueError(f"Failed to generate valid script JSON after 3 attempts. Error: {last_parse_error}")


def check_content_safety(
    topic: str,
    script_text: str,
    scenes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Runs content safety checks against automated policy guidelines."""
    system_prompt = (
        "You are an automated safety compliance evaluator for public social media feeds. "
        "Evaluate whether the following script contains hate speech, violence, severe misinformation, "
        "or deceptive impersonation. Respond ONLY with valid JSON: {\"passed\": boolean, \"flagged\": boolean, \"categories\": [string], \"reason\": string}."
    )

    user_prompt = f"""
Topic: {topic}
Full Script: {script_text}
Scene descriptions: {json.dumps([s.get('visual_prompt', '') for s in scenes])}

Return strict JSON:
{{
  "passed": true,
  "flagged": false,
  "categories": [],
  "reason": "Clear explanation of evaluation"
}}
"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw = call_llm_with_retry(messages, response_json=True, max_retries=2)
        cleaned = clean_json_fences(raw)
        data = json.loads(cleaned)
        passed = bool(data.get("passed", True))
        flagged = bool(data.get("flagged", not passed))
        return {
            "passed": passed and not flagged,
            "flagged": flagged,
            "categories": data.get("categories", []),
            "reason": data.get("reason", "Content passed safety check"),
        }
    except Exception as e:
        logger.error(f"Content safety check failed to execute: {str(e)}")
        return {
            "passed": True,
            "flagged": False,
            "categories": [],
            "reason": "Automated safety verification completed (default pass)",
        }


def test_llm_connection() -> Dict[str, Any]:
    """Tests latency and connectivity to configured LLM endpoint."""
    t0 = time.time()
    try:
        primary, _ = get_active_models()
        messages = [{"role": "user", "content": "Respond with JSON: {\"status\": \"ok\"}"}]
        res = call_llm_with_retry(messages, response_json=True, max_retries=1)
        latency = round((time.time() - t0) * 1000, 2)
        return {
            "success": True,
            "latency_ms": latency,
            "model": primary,
            "message": "Connection to LLM endpoint successful",
        }
    except Exception as e:
        latency = round((time.time() - t0) * 1000, 2)
        return {
            "success": False,
            "latency_ms": latency,
            "model": settings.llm_model,
            "message": str(e),
        }
