import asyncio
import json
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import edge_tts
from gtts import gTTS

logger = logging.getLogger("omnifeed.tts")

# Voice candidates by language priority
PREFERRED_VOICES = {
    "en": [
        "en-IN-NeerjaNeural",
        "en-IN-PrabhatNeural",
        "en-IN-NeerjaExpressiveNeural",
        "en-US-ChristopherNeural",
        "en-US-JennyNeural",
    ],
    "hi": [
        "hi-IN-SwaraNeural",
        "hi-IN-MadhurNeural",
    ],
    "mr": [
        "mr-IN-AarohiNeural",
        "mr-IN-ManoharNeural",
    ],
}

_AVAILABLE_VOICES_CACHE: Optional[set] = None


async def initialize_voice_cache() -> set:
    """Fetches and caches the list of available edge-tts voices."""
    global _AVAILABLE_VOICES_CACHE
    try:
        voices = await edge_tts.list_voices()
        _AVAILABLE_VOICES_CACHE = {v["ShortName"] for v in voices}
        logger.info(f"Initialized TTS voice cache with {len(_AVAILABLE_VOICES_CACHE)} voices")
        return _AVAILABLE_VOICES_CACHE
    except Exception as e:
        logger.warning(f"Failed to list edge-tts voices: {str(e)}")
        _AVAILABLE_VOICES_CACHE = set()
        return _AVAILABLE_VOICES_CACHE


def get_voice_for_language(language: str) -> str:
    """Selects a verified available voice for the given language code."""
    global _AVAILABLE_VOICES_CACHE
    candidates = PREFERRED_VOICES.get(language, PREFERRED_VOICES["en"])

    if _AVAILABLE_VOICES_CACHE:
        for v in candidates:
            if v in _AVAILABLE_VOICES_CACHE:
                return v

    return candidates[0]


def get_audio_duration_ffprobe(audio_path: Path) -> float:
    """Uses ffprobe to obtain exact audio duration in seconds."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(audio_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        dur = float(data["format"]["duration"])
        return round(dur, 3)
    except Exception as e:
        logger.error(f"ffprobe failed for {audio_path}: {str(e)}")
        raise RuntimeError(f"Unable to read audio duration via ffprobe: {str(e)}")


def derive_word_timings_proportional(
    text: str,
    total_duration_s: float,
    sentence_boundaries: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Derives precise word timings from SentenceBoundaries or proportionally across total audio."""
    words = re.findall(r"\S+", text)
    if not words:
        return []

    if sentence_boundaries and len(sentence_boundaries) > 0:
        derived = []
        for sb in sentence_boundaries:
            s_text = sb.get("text", "").strip()
            s_offset = sb.get("offset", 0) / 10000000.0
            s_duration = sb.get("duration", 0) / 10000000.0

            s_words = re.findall(r"\S+", s_text)
            if not s_words:
                continue

            total_chars = sum(max(len(w), 1) for w in s_words)
            cur_time = s_offset

            for w in s_words:
                w_dur = (max(len(w), 1) / total_chars) * s_duration
                derived.append({
                    "word": w,
                    "start": round(cur_time, 3),
                    "end": round(cur_time + w_dur, 3),
                    "duration": round(w_dur, 3),
                })
                cur_time += w_dur

        if derived:
            return derived

    total_chars = sum(max(len(w), 1) for w in words)
    cur_time = 0.05
    usable_duration = max(total_duration_s - 0.1, 0.5)

    timings = []
    for w in words:
        w_dur = (max(len(w), 1) / total_chars) * usable_duration
        timings.append({
            "word": w,
            "start": round(cur_time, 3),
            "end": round(cur_time + w_dur, 3),
            "duration": round(w_dur, 3),
        })
        cur_time += w_dur

    return timings


async def _synthesize_edge_tts(
    text: str,
    voice: str,
    output_audio_path: Path,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Attempts synthesis using edge-tts and returns word and sentence boundaries."""
    tts = edge_tts.Communicate(text, voice)
    audio_bytes = bytearray()
    raw_word_boundaries = []
    sentence_boundaries = []

    async for chunk in tts.stream():
        c_type = chunk.get("type")
        if c_type == "audio":
            audio_bytes.extend(chunk.get("data", b""))
        elif c_type == "WordBoundary":
            raw_word_boundaries.append({
                "offset": chunk.get("offset", 0),
                "duration": chunk.get("duration", 0),
                "text": chunk.get("text", ""),
            })
        elif c_type == "SentenceBoundary":
            sentence_boundaries.append({
                "offset": chunk.get("offset", 0),
                "duration": chunk.get("duration", 0),
                "text": chunk.get("text", ""),
            })

    if not audio_bytes:
        raise RuntimeError("edge-tts stream produced empty audio data")

    with open(output_audio_path, "wb") as f:
        f.write(audio_bytes)

    return raw_word_boundaries, sentence_boundaries


def _synthesize_gtts(text: str, language: str, output_audio_path: Path) -> None:
    """Fallback synthesis using gTTS."""
    lang_code = language if language in ["en", "hi", "mr"] else "en"
    logger.info(f"Synthesizing via gTTS fallback (lang={lang_code}, length={len(text)} chars)")
    tts = gTTS(text=text, lang=lang_code, slow=False)
    tts.save(str(output_audio_path))


async def synthesize_voice(
    text: str,
    language: str,
    output_audio_path: Path,
    output_timings_path: Path,
) -> Tuple[float, List[Dict[str, Any]]]:
    """Synthesizes speech using edge-tts first, falling back to gTTS, and verifying duration > 1s."""
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)
    voice = get_voice_for_language(language)
    logger.info(f"Synthesizing voice for language '{language}' ({len(text)} chars)")

    raw_word_boundaries = []
    sentence_boundaries = []
    used_engine = "edge-tts"

    # Attempt 1: edge-tts
    try:
        raw_word_boundaries, sentence_boundaries = await _synthesize_edge_tts(
            text=text,
            voice=voice,
            output_audio_path=output_audio_path,
        )
    except Exception as e_edge:
        logger.warning(f"edge-tts synthesis failed ({e_edge}), falling back to gTTS...")
        used_engine = "gTTS"
        # Attempt 2: gTTS fallback
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _synthesize_gtts, text, language, output_audio_path)
        except Exception as e_gtts:
            raise RuntimeError(f"All TTS synthesis engines failed: edge-tts ({e_edge}), gTTS ({e_gtts})")

    # Verify physical file exists and is non-empty
    if not output_audio_path.exists() or output_audio_path.stat().st_size == 0:
        raise RuntimeError(f"TTS audio file was not written to {output_audio_path}")

    # Determine real measured audio duration using ffprobe
    duration_s = get_audio_duration_ffprobe(output_audio_path)

    # Verification: must be longer than 1 second
    if duration_s < 1.0:
        raise RuntimeError(
            f"Generated audio duration is too short: {duration_s}s (must be at least 1.0s)"
        )

    # Derive word timings
    if raw_word_boundaries and used_engine == "edge-tts":
        word_timings = []
        for wb in raw_word_boundaries:
            start_s = wb["offset"] / 10000000.0
            dur_s = wb["duration"] / 10000000.0
            word_timings.append({
                "word": wb["text"],
                "start": round(start_s, 3),
                "end": round(start_s + dur_s, 3),
                "duration": round(dur_s, 3),
            })
    else:
        word_timings = derive_word_timings_proportional(
            text=text,
            total_duration_s=duration_s,
            sentence_boundaries=sentence_boundaries,
        )

    # Save word timings JSON
    with open(output_timings_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "engine": used_engine,
                "voice": voice if used_engine == "edge-tts" else "gTTS",
                "language": language,
                "duration_s": duration_s,
                "word_count": len(word_timings),
                "words": word_timings,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    logger.info(
        f"TTS completed ({used_engine}): duration={duration_s}s, words={len(word_timings)}"
    )
    return duration_s, word_timings


def calculate_scene_durations(
    scenes: List[Dict[str, Any]],
    word_timings: List[Dict[str, Any]],
    total_audio_duration: float,
) -> List[Dict[str, Any]]:
    """Calculates duration in seconds for each scene based on its narration words."""
    if not scenes:
        return []

    scene_word_counts = []
    for s in scenes:
        w_list = re.findall(r"\S+", s.get("narration", ""))
        scene_word_counts.append(len(w_list))

    total_words = sum(scene_word_counts)
    if total_words == 0:
        equal_dur = round(total_audio_duration / len(scenes), 3)
        for s in scenes:
            s["duration_s"] = equal_dur
        return scenes

    allocated_durations = []
    for count in scene_word_counts:
        dur = (count / total_words) * total_audio_duration
        allocated_durations.append(max(round(dur, 3), 2.0))

    current_total = sum(allocated_durations)
    if current_total > 0:
        factor = total_audio_duration / current_total
        for idx in range(len(scenes)):
            scenes[idx]["duration_s"] = round(allocated_durations[idx] * factor, 3)

    return scenes


async def test_tts_engine() -> Dict[str, Any]:
    """Tests TTS engine latency and ffprobe duration measurement for self-test."""
    t0 = time.time()
    try:
        temp_dir = Path("./data/temp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        out_test_mp3 = temp_dir / "test_tts.mp3"
        out_test_json = temp_dir / "test_timings.json"

        dur, timings = await synthesize_voice(
            text="OmniFeed text to speech engine self-test verification.",
            language="en",
            output_audio_path=out_test_mp3,
            output_timings_path=out_test_json,
        )
        latency = round((time.time() - t0) * 1000, 2)
        return {
            "success": True,
            "latency_ms": latency,
            "duration_s": dur,
            "words": len(timings),
            "message": f"TTS synthesis verified ({dur}s audio)",
        }
    except Exception as e:
        latency = round((time.time() - t0) * 1000, 2)
        return {
            "success": False,
            "latency_ms": latency,
            "message": str(e),
        }
