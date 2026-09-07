"""Stage 2 — Acquire: fetch captions when available, else temp audio.

Audio lives in a temp dir under the channel folder and is deleted after
Stage 3 succeeds. Failures degrade to log-and-skip.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .config import Config
from .manifest import Manifest


def acquire_video(config: Config, channel_dir: Path, rec: dict) -> dict:
    """Fetch metadata + captions or audio for one video. Mutates and returns rec."""
    vid = rec["video_id"]
    url = rec["url"]
    tmp_dir = channel_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    subs_dir = channel_dir / "subs"
    subs_dir.mkdir(parents=True, exist_ok=True)

    # Full metadata (flat-playlist discovery is shallow) + subtitle download attempt.
    meta_cmd = [
        "yt-dlp", "--dump-json", "--no-download",
        "--write-subs", "--write-auto-subs", "--sub-langs", "all",
        "--convert-subs", "vtt",
        "-o", str(subs_dir / f"{vid}.%(ext)s"),
        url,
    ]
    out = subprocess.run(meta_cmd, capture_output=True, text=True, timeout=300)
    if out.returncode == 0 and out.stdout.strip():
        try:
            info = json.loads(out.stdout.strip().splitlines()[0])
            rec["title"] = info.get("title") or rec.get("title", "")
            rec["description"] = info.get("description", "")
            rec["duration"] = info.get("duration")
            rec["view_count"] = info.get("view_count")
            upload = info.get("upload_date")
            if upload and len(upload) == 8:
                rec["date"] = f"{upload[:4]}-{upload[4:6]}-{upload[6:]}"
            rec["hashtags"] = [t for t in (info.get("tags") or [])]
        except (json.JSONDecodeError, IndexError):
            pass

    subs = sorted(subs_dir.glob(f"{vid}*.vtt"))
    if subs:
        rec["subtitle_file"] = str(subs[0])
        rec["extraction_method"] = "captions"
        return rec

    # No captions: download audio-only into temp storage.
    audio_path = tmp_dir / f"{vid}.m4a"
    dl_cmd = [
        "yt-dlp", "-f", "bestaudio/best", "-x", "--audio-format", "m4a",
        "-o", str(tmp_dir / f"{vid}.%(ext)s"), url,
    ]
    out = subprocess.run(dl_cmd, capture_output=True, text=True, timeout=900)
    if out.returncode != 0 or not audio_path.exists():
        # Some formats land with other extensions
        found = list(tmp_dir.glob(f"{vid}.*"))
        if found:
            audio_path = found[0]
        else:
            raise RuntimeError(f"audio download failed: {out.stderr.strip()[-300:]}")
    rec["audio_file"] = str(audio_path)
    rec["extraction_method"] = "whisper"
    return rec


def run_acquire(config: Config, handle: str, retry_failed: bool = False) -> tuple[int, int]:
    channel_dir = config.channel_dir(handle)
    manifest = Manifest(channel_dir)
    ok = failed = 0
    for rec in manifest.pending("acquired", retry_failed=retry_failed):
        vid = rec["video_id"]
        try:
            acquire_video(config, channel_dir, rec)
            manifest.mark(vid, "acquired")
            ok += 1
        except Exception as e:  # log and skip, never crash the run
            manifest.mark(vid, "failed:acquire", error=str(e))
            failed += 1
        time.sleep(config.request_delay)
    return ok, failed
