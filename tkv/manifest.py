"""Per-channel manifest: one JSONL record per video, checkpointed status.

Status progression: discovered -> acquired -> transcribed -> watched
-> enriched -> published. Failures record status="failed:<stage>" plus error.
Writes are atomic (temp file + rename) so a crash never corrupts the manifest.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

STAGES = ["discovered", "acquired", "transcribed", "watched", "enriched", "published"]


class Manifest:
    def __init__(self, channel_dir: Path):
        self.path = channel_dir / "manifest.jsonl"
        self.videos: dict[str, dict] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    self.videos[rec["video_id"]] = rec
                except (json.JSONDecodeError, KeyError):
                    continue

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            for rec in self.videos.values():
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)

    def upsert(self, video_id: str, **fields) -> dict:
        rec = self.videos.setdefault(video_id, {"video_id": video_id})
        rec.update(fields)
        return rec

    def mark(self, video_id: str, status: str, error: str | None = None) -> None:
        rec = self.videos.setdefault(video_id, {"video_id": video_id})
        rec["status"] = status
        if error:
            rec["error"] = error
        elif "error" in rec:
            del rec["error"]
        self.save()

    def reached(self, video_id: str, stage: str) -> bool:
        """True if the video has completed `stage` (or a later one)."""
        rec = self.videos.get(video_id)
        if not rec:
            return False
        status = rec.get("status", "")
        if status not in STAGES:
            return False
        return STAGES.index(status) >= STAGES.index(stage)

    def pending(self, stage: str, retry_failed: bool = False) -> list[dict]:
        """Videos that have completed the previous stage but not `stage`."""
        prev = STAGES[STAGES.index(stage) - 1]
        out = []
        for rec in self.videos.values():
            status = rec.get("status", "")
            if status in STAGES and self.reached(rec["video_id"], stage):
                continue
            if status.startswith("failed:"):
                if retry_failed:
                    out.append(rec)
                continue
            if self.reached(rec["video_id"], prev):
                out.append(rec)
        return out

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for rec in self.videos.values():
            s = rec.get("status", "unknown")
            out[s] = out.get(s, 0) + 1
        return out
