"""Stage 3 — Transcribe: captions first, faster-whisper fallback.

Output: data/<handle>/transcripts/<video_id>.md with YAML frontmatter.
Temp audio is deleted once transcription succeeds.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .config import Config
from .manifest import Manifest

_whisper_model = None

WATCH_ENV = Path.home() / ".config" / "watch" / ".env"


def _watch_env_key(name: str) -> str | None:
    """Read a key from the /watch skill's config (~/.config/watch/.env)."""
    import os
    if os.environ.get(name):
        return os.environ[name]
    if WATCH_ENV.exists():
        for line in WATCH_ENV.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}=") and not line.startswith("#"):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val
    return None


def groq_transcribe(config: Config, audio_path: Path) -> tuple[list[tuple[str, str]], str]:
    """Transcribe via Groq's Whisper API (same backend the /watch skill uses)."""
    import requests
    key = _watch_env_key("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY not found in env or ~/.config/watch/.env")
    with open(audio_path, "rb") as f:
        r = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (audio_path.name, f)},
            data={"model": "whisper-large-v3", "response_format": "verbose_json"},
            timeout=300,
        )
    r.raise_for_status()
    data = r.json()
    out = []
    for seg in data.get("segments", []):
        m, s = divmod(int(seg["start"]), 60)
        text = seg["text"].strip()
        if text:
            out.append((f"{m}:{s:02d}", text))
    if not out and data.get("text"):
        out = [("0:00", data["text"].strip())]
    return out, data.get("language", "unknown")


def parse_vtt(path: Path) -> list[tuple[str, str]]:
    """Return [(timestamp, text)] segments from a WebVTT file."""
    segments: list[tuple[str, str]] = []
    ts = None
    lines: list[str] = []
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        m = re.match(r"(\d+:)?(\d{2}):(\d{2})[.,]\d{3}\s*-->", line)
        if m:
            if ts and lines:
                segments.append((ts, " ".join(lines)))
            h = (m.group(1) or "0:").rstrip(":")
            ts = f"{int(h)}:{m.group(2)}:{m.group(3)}" if int(h) else f"{m.group(2)}:{m.group(3)}"
            lines = []
        elif line and not line.startswith(("WEBVTT", "NOTE", "STYLE")) and "-->" not in line:
            text = re.sub(r"<[^>]+>", "", line)
            if text and (not lines or lines[-1] != text):
                lines.append(text)
    if ts and lines:
        segments.append((ts, " ".join(lines)))
    # Dedupe consecutive identical texts (auto-captions repeat)
    out: list[tuple[str, str]] = []
    for ts, text in segments:
        if not out or out[-1][1] != text:
            out.append((ts, text))
    return out


def whisper_transcribe(config: Config, audio_path: Path) -> tuple[list[tuple[str, str]], str]:
    """Transcribe audio with faster-whisper. Returns (segments, language)."""
    global _whisper_model
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper not installed and no captions available. "
            "Install with: pip install 'tkv[whisper]'"
        ) from e
    if _whisper_model is None:
        _whisper_model = WhisperModel(config.whisper_model, compute_type="int8")
    segments, info = _whisper_model.transcribe(str(audio_path), vad_filter=True)
    out = []
    for seg in segments:
        m, s = divmod(int(seg.start), 60)
        out.append((f"{m}:{s:02d}", seg.text.strip()))
    return out, info.language


def write_transcript(channel_dir: Path, rec: dict, segments: list[tuple[str, str]],
                     language: str | None) -> Path:
    tdir = channel_dir / "transcripts"
    tdir.mkdir(parents=True, exist_ok=True)
    front = {
        "video_id": rec["video_id"],
        "url": rec.get("url"),
        "date": rec.get("date"),
        "title": rec.get("title", ""),
        "duration": rec.get("duration"),
        "extraction_method": rec.get("extraction_method"),
        "language": language,
    }
    body = "\n".join(f"**{ts}** {text}" for ts, text in segments) or "_(no speech detected)_"
    path = tdir / f"{rec['video_id']}.md"
    path.write_text(
        "---\n" + yaml.safe_dump(front, allow_unicode=True, sort_keys=False) + "---\n\n"
        f"# Transcript\n\n{body}\n"
    )
    return path


def run_transcribe(config: Config, handle: str, retry_failed: bool = False) -> tuple[int, int]:
    channel_dir = config.channel_dir(handle)
    manifest = Manifest(channel_dir)
    ok = failed = 0
    for rec in manifest.pending("transcribed", retry_failed=retry_failed):
        vid = rec["video_id"]
        try:
            language = None
            if rec.get("subtitle_file") and Path(rec["subtitle_file"]).exists():
                segments = parse_vtt(Path(rec["subtitle_file"]))
                sub_name = Path(rec["subtitle_file"]).stem  # e.g. <vid>.en
                language = sub_name.split(".")[-1] if "." in sub_name else None
            elif rec.get("audio_file") and Path(rec["audio_file"]).exists():
                if config.stt_backend == "none":
                    raise RuntimeError("no captions and stt_backend=none")
                if config.stt_backend == "watch-skill":
                    segments, language = groq_transcribe(config, Path(rec["audio_file"]))
                    rec["extraction_method"] = "whisper-groq"
                else:
                    segments, language = whisper_transcribe(config, Path(rec["audio_file"]))
            else:
                raise RuntimeError("no subtitle or audio file on record")
            rec["transcript_file"] = str(write_transcript(channel_dir, rec, segments, language))
            rec["language"] = language
            # Temp audio deleted after success
            if rec.get("audio_file"):
                Path(rec["audio_file"]).unlink(missing_ok=True)
            manifest.mark(vid, "transcribed")
            ok += 1
        except Exception as e:
            manifest.mark(vid, "failed:transcribe", error=str(e))
            failed += 1
    return ok, failed
