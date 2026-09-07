"""Stage 3b — Watch: ffmpeg frame extraction + Claude vision visual log.

Frames are kept (unlike temp audio) at data/<handle>/frames/<video_id>/ so
the vault can embed them. Vision output goes to data/<handle>/visual/<id>.md.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .config import Config
from .manifest import Manifest

VISION_PROMPT = """You are analyzing frames from a short-form TikTok video alongside its transcript.
Each image is labeled with its timestamp. Produce a markdown "visual log":

1. A timestamped list of what appears on screen (text overlays quoted verbatim,
   code snippets transcribed in fenced blocks, UI patterns named precisely,
   diagrams described).
2. Call out any information visible on screen that is NOT in the audio transcript.
3. If UI patterns are demonstrated (skeleton loader, progress bar, toast, etc.),
   name them explicitly.

Transcript:
{transcript}

Respond with only the markdown visual log."""


def _download_video(url: str, tmp_dir: Path, vid: str) -> Path:
    out = tmp_dir / f"{vid}.mp4"
    if not out.exists():
        r = subprocess.run(
            ["yt-dlp", "-f", "mp4/best", "-o", str(out), url],
            capture_output=True, text=True, timeout=900,
        )
        if r.returncode != 0 or not out.exists():
            raise RuntimeError(f"video download failed: {r.stderr.strip()[-300:]}")
    return out


def extract_frames(config: Config, video_path: Path, frames_dir: Path,
                   mode: str, fps: float) -> list[Path]:
    """Extract frames named by timestamp (seconds). Returns saved frame paths."""
    frames_dir.mkdir(parents=True, exist_ok=True)
    w = config.watch
    scale = f"scale='min({w.max_width},iw)':-2"
    if mode == "scene":
        vf = f"select='gt(scene,{w.scene_threshold})+eq(n,0)',{scale}"
    else:
        vf = f"fps={fps},{scale}"
    tmp_pattern = frames_dir / "raw_%05d.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-vf", vf, "-fps_mode", "vfr",
         "-frame_pts", "1", "-q:v", "4", str(tmp_pattern)],
        capture_output=True, text=True, timeout=600, check=True,
    )
    # Rename raw_N to timestamped names using ffprobe-derived pts via showinfo alternative:
    # simpler: re-run naming by frame index * (duration/count) is lossy; instead use
    # ffmpeg's -frame_pts which encodes pts in the number when supported. Fall back to index.
    frames = sorted(frames_dir.glob("raw_*.jpg"))[: w.max_frames_per_video]
    for extra in sorted(frames_dir.glob("raw_*.jpg"))[w.max_frames_per_video:]:
        extra.unlink()
    out = []
    for f in frames:
        n = int(re.search(r"(\d+)", f.stem).group(1))
        dest = frames_dir / f"{n:06d}.jpg"
        f.rename(dest)
        out.append(dest)
    return out


def vision_pass(config: Config, frames: list[Path], transcript: str) -> str:
    from .ai import complete_with_images
    return complete_with_images(
        config, VISION_PROMPT.format(transcript=transcript[:12000]), frames,
        model=config.vision_model,
    )


def estimate_cost(n_videos: int, frames_per_video: int) -> str:
    # ~1100 tokens per downscaled 1280px frame, rough Sonnet input pricing
    tokens = n_videos * frames_per_video * 1100
    usd = tokens / 1_000_000 * 3.0
    return f"~{n_videos} videos x {frames_per_video} frames = ~{tokens:,} vision tokens (~${usd:.2f} input)"


def run_watch(config: Config, handle: str, mode: str | None = None, fps: float | None = None,
              only_video: str | None = None, retry_failed: bool = False,
              no_vision: bool = False) -> tuple[int, int]:
    channel_dir = config.channel_dir(handle)
    manifest = Manifest(channel_dir)
    mode = mode or config.watch.mode
    fps = fps or config.watch.fps
    ok = failed = 0
    pending = manifest.pending("watched", retry_failed=retry_failed)
    if only_video:
        pending = [r for r in pending if r["video_id"] == only_video] or \
                  [manifest.videos[only_video]] if only_video in manifest.videos else []
    frame_budget = config.watch.frame_budget_per_run
    for rec in pending:
        vid = rec["video_id"]
        if no_vision:
            manifest.mark(vid, "watched")
            ok += 1
            continue
        if frame_budget <= 0:
            break
        try:
            tmp_dir = channel_dir / "tmp"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            video_path = _download_video(rec["url"], tmp_dir, vid)
            frames_dir = channel_dir / "frames" / vid
            frames = extract_frames(config, video_path, frames_dir, mode, fps)
            frame_budget -= len(frames)
            transcript = ""
            if rec.get("transcript_file") and Path(rec["transcript_file"]).exists():
                transcript = Path(rec["transcript_file"]).read_text()
            log = vision_pass(config, frames, transcript)
            vdir = channel_dir / "visual"
            vdir.mkdir(parents=True, exist_ok=True)
            vpath = vdir / f"{vid}.md"
            vpath.write_text(f"# Visual log — {rec.get('title','')}\n\n{log}\n")
            rec["visual_file"] = str(vpath)
            rec["frame_count"] = len(frames)
            video_path.unlink(missing_ok=True)
            manifest.mark(vid, "watched")
            ok += 1
        except Exception as e:
            manifest.mark(vid, "failed:watch", error=str(e))
            failed += 1
    return ok, failed
