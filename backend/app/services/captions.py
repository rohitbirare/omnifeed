import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("omnifeed.captions")


def format_ass_time(seconds: float) -> str:
    """Formats seconds into ASS timestamp H:MM:SS.cc."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{hrs}:{mins:02d}:{secs:02d}.{cs:02d}"


def build_ass_subtitle_file(
    word_timings: List[Dict[str, Any]],
    language: str,
    output_ass_path: Path,
) -> Path:
    """Builds an ASS subtitle file with kinetic word highlighting in the lower-middle safe area."""
    output_ass_path.parent.mkdir(parents=True, exist_ok=True)

    # Font selection based on language script
    if language in ["hi", "mr"]:
        font_name = "Noto Sans Devanagari"
    else:
        font_name = "DejaVu Sans"

    # Deep teal accent in ASS format (&HAABBGGRR): #0f766e -> B=0x6e, G=0x76, R=0x0f -> &H006E760F&
    # Or high-contrast bright teal: #14b8a6 -> B=0xa6, G=0xb8, R=0x14 -> &H00A6B814&
    accent_bgr = "&H00A6B814&"
    white_bgr = "&H00FFFFFF&"
    black_outline = "&H00000000&"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: KineticCaption,{font_name},66,{white_bgr},&H000000FF,{black_outline},&H80000000,-1,0,0,0,100,100,0,0,1,5,1,2,80,80,480,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    if not word_timings:
        with open(output_ass_path, "w", encoding="utf-8") as f:
            f.write(header)
        return output_ass_path

    # Group words into short phrases (2 to 4 words per line)
    chunks: List[List[Dict[str, Any]]] = []
    chunk_size = 3
    for i in range(0, len(word_timings), chunk_size):
        chunks.append(word_timings[i : i + chunk_size])

    dialogue_lines: List[str] = []

    for chunk in chunks:
        if not chunk:
            continue

        chunk_start = chunk[0]["start"]
        chunk_end = chunk[-1]["end"]

        # For each word in the chunk, highlight it while it is being spoken
        for i, target_word in enumerate(chunk):
            w_start = target_word["start"]
            w_end = target_word["end"]
            if w_end <= w_start:
                w_end = w_start + 0.2

            # Build line text with target word highlighted
            text_tokens = []
            for j, w in enumerate(chunk):
                raw_w = w["word"].replace("{", "").replace("}", "")
                if j == i:
                    text_tokens.append(f"{{\\c{accent_bgr}}}{raw_w}{{\\c{white_bgr}}}")
                else:
                    text_tokens.append(raw_w)

            line_text = " ".join(text_tokens)
            start_str = format_ass_time(w_start)
            end_str = format_ass_time(w_end)

            dialogue_lines.append(
                f"Dialogue: 0,{start_str},{end_str},KineticCaption,,0,0,0,,{line_text}"
            )

    full_ass = header + "\n".join(dialogue_lines) + "\n"

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(full_ass)

    logger.info(f"Built ASS subtitle file with {len(dialogue_lines)} events at {output_ass_path}")
    return output_ass_path
