import array
import math
import re
import subprocess
import sys
import uuid
from pathlib import Path

from subgen_utils import hidden_subprocess_kwargs


def has_saved_editor_changes(review):
    return bool(review and (review.get("editor_saved") or any(
        cue.get("manually_edited") for field in ("source_draft", "translation_draft")
        for cue in review.get(field) or []
    )))


def review_subtitle_files(review, base):
    """Render both edited languages from the durable review, without providers."""
    from subgen_review import normalize_cues, render_srt_bytes

    if not base or Path(base).name != base or base in {".", ".."} or "\\" in base:
        raise ValueError("Invalid subtitle filename")
    source_language = review.get("source_language") or "source"
    target_language = review.get("target_language")
    languages = [(source_language, normalize_cues(review.get("source_draft")))]
    if target_language and target_language != source_language:
        translated = normalize_cues(review.get("translation_draft"))
        if len(translated) != len(languages[0][1]):
            raise ValueError("Source and translation cue counts differ")
        languages.append((target_language, translated))
    files = {}
    for language, cues in languages:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", language):
            raise ValueError("Invalid subtitle language")
        if not cues or not validate_editor_segments(cues)["accept"]:
            raise ValueError("Resolve subtitle timing errors before saving subtitle files")
        files[f"{base}.{language}.srt"] = render_srt_bytes(cues)
        files[f"{base}.{language}.txt"] = ("\n".join(cue["text"] for cue in cues) + "\n").encode("utf-8")
    files[f"{base}.api_transcript.txt"] = files[f"{base}.{source_language}.txt"]
    return files


def export_review_subtitles(review, directory, base):
    files = review_subtitle_files(review, base)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    staged = []
    try:
        for name, content in files.items():
            destination = directory / name
            temporary = directory / f".{name}.{uuid.uuid4().hex}.tmp"
            staged.append((temporary, destination))
            temporary.write_bytes(content)
        for temporary, destination in staged:
            temporary.replace(destination)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    language = review.get("target_language") or review.get("source_language") or "source"
    return directory / f"{base}.{language}.srt"


def srt_time_to_seconds(value):
    if isinstance(value, (int, float)):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Timestamp must be finite")
        return result
    text = str(value or "").strip().replace(".", ",")
    if ":" not in text:
        result = float(text.replace(",", "."))
        if not math.isfinite(result):
            raise ValueError("Timestamp must be finite")
        return result
    parts = text.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid SRT timestamp: {value}")
    seconds_part = parts[2].split(",")
    if len(seconds_part) != 2:
        raise ValueError(f"Invalid SRT timestamp: {value}")
    return (
        int(parts[0]) * 3600
        + int(parts[1]) * 60
        + int(seconds_part[0])
        + int(seconds_part[1].ljust(3, "0")[:3]) / 1000.0
    )


def validate_editor_segments(segments):
    errors = []
    warnings = []
    previous_end = 0.0
    for position, segment in enumerate(segments or [], start=1):
        try:
            start = srt_time_to_seconds(segment.get("start"))
            end = srt_time_to_seconds(segment.get("end"))
        except (TypeError, ValueError) as exc:
            errors.append({"index": position, "code": "invalid_time", "message": str(exc)})
            continue
        if start < 0 or end <= start:
            errors.append({"index": position, "code": "invalid_range", "message": "End time must be after start time."})
            continue
        if position > 1 and start < previous_end - 0.001:
            errors.append({"index": position, "code": "overlap", "message": "Cue overlaps the previous cue."})
        duration = end - start
        text = str(segment.get("translation") or segment.get("text") or "").strip()
        if not text:
            warnings.append({"index": position, "code": "empty_text", "message": "Cue has no subtitle text."})
        if duration < 0.35:
            warnings.append({"index": position, "code": "short_duration", "message": "Cue is shorter than 350 ms."})
        if duration > 8.0:
            warnings.append({"index": position, "code": "long_duration", "message": "Cue remains visible longer than 8 seconds."})
        if text and len(text) / max(duration, 0.001) > 24:
            warnings.append({"index": position, "code": "reading_speed", "message": "Cue may be too fast to read."})
        previous_end = end
    return {"accept": not errors, "errors": errors, "warnings": warnings}


def build_waveform_peaks(video_path, bins=900):
    bins = max(120, min(2000, int(bins or 900)))
    command = [
        "ffmpeg", "-v", "error", "-i", str(video_path), "-vn", "-ac", "1",
        "-ar", "400", "-f", "s16le", "pipe:1",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        timeout=120,
        **hidden_subprocess_kwargs(),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-1000:])
    samples = array.array("h")
    samples.frombytes(result.stdout)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return [0.0] * bins
    stride = max(1, len(samples) // bins)
    peaks = []
    for offset in range(0, len(samples), stride):
        window = samples[offset:offset + stride]
        peaks.append(round(max((abs(value) for value in window), default=0) / 32768.0, 4))
        if len(peaks) == bins:
            break
    if len(peaks) < bins:
        peaks.extend([0.0] * (bins - len(peaks)))
    return peaks
