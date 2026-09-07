"""Stage 4 — Enrich: Claude summarization, keywords, platform/domain tags.

Consumes transcript + visual log together. Output cached in
data/<handle>/enriched/<video_id>.json; only new/changed inputs re-run.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import Config
from .manifest import Manifest

ENRICH_PROMPT = """You are indexing a TikTok video into a knowledge vault used by AI coding assistants.

Video title/caption: {title}

Transcript:
{transcript}

Visual log (on-screen content):
{visual}

Allowed platform tags: {platforms}
Allowed domain tags: {domains}

Return ONLY valid JSON with this shape:
{{
  "summary": "2-4 sentence summary",
  "takeaways": ["actionable item to implement or consider", "..."],
  "keywords": ["5-15 keywords, lowercase-kebab-case"],
  "platform": ["subset of allowed platform tags"],
  "domain": ["subset of allowed domain tags"],
  "tags": ["free-form topical tags, lowercase-kebab-case"]
}}"""


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of possibly prose-wrapped model output."""
    decoder = json.JSONDecoder()
    idx = text.find("{")
    while idx != -1:
        try:
            obj, _ = decoder.raw_decode(text, idx)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        idx = text.find("{", idx + 1)
    raise ValueError(f"no JSON object in model output: {text[:200]!r}")


def _input_hash(transcript: str, visual: str) -> str:
    return hashlib.sha256((transcript + "\x00" + visual).encode()).hexdigest()[:16]


def enrich_video(config: Config, rec: dict, transcript: str, visual: str) -> dict:
    from .ai import complete
    prompt = ENRICH_PROMPT.format(
        title=rec.get("title", ""),
        transcript=transcript[:20000] or "(no transcript)",
        visual=visual[:10000] or "(no visual log)",
        platforms=", ".join(config.taxonomy["platform"]),
        domains=", ".join(config.taxonomy["domain"]),
    )
    text = complete(config, prompt, max_tokens=1500).strip()
    data = _extract_json(text)
    # Clamp tags to configured taxonomy
    data["platform"] = [t for t in data.get("platform", []) if t in config.taxonomy["platform"]] or ["general"]
    data["domain"] = [t for t in data.get("domain", []) if t in config.taxonomy["domain"]] or ["general"]
    return data


def run_enrich(config: Config, handle: str, retag: bool = False,
               retry_failed: bool = False) -> tuple[int, int]:
    channel_dir = config.channel_dir(handle)
    manifest = Manifest(channel_dir)
    edir = channel_dir / "enriched"
    edir.mkdir(parents=True, exist_ok=True)
    ok = failed = 0
    pending = manifest.pending("enriched", retry_failed=retry_failed)
    if retag:
        pending = [r for r in manifest.videos.values()
                   if manifest.reached(r["video_id"], "enriched")] + pending
    for rec in pending:
        vid = rec["video_id"]
        try:
            transcript = visual = ""
            if rec.get("transcript_file") and Path(rec["transcript_file"]).exists():
                transcript = Path(rec["transcript_file"]).read_text()
            if rec.get("visual_file") and Path(rec["visual_file"]).exists():
                visual = Path(rec["visual_file"]).read_text()
            h = _input_hash(transcript, visual)
            cache = edir / f"{vid}.json"
            if cache.exists() and not retag:
                cached = json.loads(cache.read_text())
                if cached.get("_input_hash") == h:
                    manifest.mark(vid, "enriched")
                    ok += 1
                    continue
            data = enrich_video(config, rec, transcript, visual)
            data["_input_hash"] = h
            cache.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            rec["enriched_file"] = str(cache)
            manifest.mark(vid, "enriched")
            ok += 1
        except Exception as e:
            manifest.mark(vid, "failed:enrich", error=str(e))
            failed += 1
    return ok, failed
