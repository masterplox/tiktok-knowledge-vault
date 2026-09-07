"""Stage 5 — Vault Build: assemble the Obsidian vault.

vault/<handle>/videos/<date>-<slug>.md, topics/<tag>.md MOCs, INDEX.md.
Frontmatter follows the AI-consumption contract (grep-filterable).
Manual frontmatter edits are respected unless --force.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import yaml

from .config import Config
from .manifest import Manifest


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "video").lower()).strip("-")
    return slug[:max_len] or "video"


def build_note(rec: dict, enriched: dict, transcript_body: str, visual_body: str,
               frames: list[str], handle: str) -> tuple[str, dict]:
    front = {
        "video_id": rec["video_id"],
        "channel": f"@{handle}",
        "date": rec.get("date"),
        "platform": enriched.get("platform", ["general"]),
        "domain": enriched.get("domain", ["general"]),
        "tags": enriched.get("tags", []),
        "keywords": enriched.get("keywords", []),
        "source_url": rec.get("url"),
    }
    lines = [f"# {rec.get('title') or rec['video_id']}", ""]
    if enriched.get("summary"):
        lines += ["## Summary", "", enriched["summary"], ""]
    if enriched.get("takeaways"):
        lines += ["## Takeaways", ""] + [f"- {t}" for t in enriched["takeaways"]] + [""]
    tag_links = " ".join(f"[[topics/{t}|#{t}]]" for t in
                         front["platform"] + front["domain"] + front["tags"][:8])
    if tag_links:
        lines += ["## Topics", "", tag_links, ""]
    if frames:
        lines += ["## Key frames", ""] + [f"![[{f}]]" for f in frames[:6]] + [""]
    if visual_body:
        lines += ["## Visual log", "", visual_body, ""]
    if transcript_body:
        lines += ["## Transcript", "", transcript_body, ""]
    body = "\n".join(lines)
    return body, front


def _strip_front(md: str) -> str:
    if md.startswith("---"):
        parts = md.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return md.strip()


def run_build_vault(config: Config, handle: str, out: Path | None = None,
                    force: bool = False) -> Path:
    channel_dir = config.channel_dir(handle)
    manifest = Manifest(channel_dir)
    vault_root = (out or config.vault_dir) / handle
    videos_dir = vault_root / "videos"
    topics_dir = vault_root / "topics"
    rules_dir = vault_root / "rules"
    frames_out = vault_root / "frames"
    for d in (videos_dir, topics_dir, rules_dir):
        d.mkdir(parents=True, exist_ok=True)

    tag_index: dict[str, list[tuple[str, str]]] = {}
    published = 0
    for rec in manifest.videos.values():
        vid = rec["video_id"]
        if not manifest.reached(vid, "enriched"):
            continue
        enriched = {}
        if rec.get("enriched_file") and Path(rec["enriched_file"]).exists():
            enriched = json.loads(Path(rec["enriched_file"]).read_text())
        transcript_body = ""
        if rec.get("transcript_file") and Path(rec["transcript_file"]).exists():
            transcript_body = _strip_front(Path(rec["transcript_file"]).read_text())
            transcript_body = transcript_body.removeprefix("# Transcript").strip()
        visual_body = ""
        if rec.get("visual_file") and Path(rec["visual_file"]).exists():
            visual_body = _strip_front(Path(rec["visual_file"]).read_text())

        # Copy kept frames into the vault
        frame_rels: list[str] = []
        src_frames = channel_dir / "frames" / vid
        if src_frames.exists():
            dest = frames_out / vid
            dest.mkdir(parents=True, exist_ok=True)
            for f in sorted(src_frames.glob("*.jpg")):
                shutil.copy2(f, dest / f.name)
                frame_rels.append(f"frames/{vid}/{f.name}")

        note_name = f"{rec.get('date') or 'undated'}-{slugify(rec.get('title', ''))}.md"
        note_path = videos_dir / note_name
        body, front = build_note(rec, enriched, transcript_body, visual_body, frame_rels, handle)

        if note_path.exists() and not force:
            # Respect manual frontmatter edits: keep existing tag axes if present.
            existing = note_path.read_text()
            if existing.startswith("---"):
                try:
                    old_front = yaml.safe_load(existing.split("---", 2)[1]) or {}
                    for key in ("platform", "domain", "tags"):
                        if key in old_front:
                            front[key] = old_front[key]
                except yaml.YAMLError:
                    pass
        note_path.write_text(
            "---\n" + yaml.safe_dump(front, allow_unicode=True, sort_keys=False) + "---\n\n" + body
        )
        for tag in front["platform"] + front["domain"] + front.get("tags", []):
            tag_index.setdefault(tag, []).append((note_name, rec.get("title") or vid))
        manifest.mark(vid, "published")
        published += 1

    # Topic MOC notes
    for tag, notes in sorted(tag_index.items()):
        moc = [f"# {tag}", "", f"Videos tagged `{tag}`:", ""]
        moc += [f"- [[videos/{name}|{title}]]" for name, title in sorted(notes)]
        (topics_dir / f"{slugify(tag)}.md").write_text("\n".join(moc) + "\n")

    # INDEX
    counts = manifest.counts()
    index = [
        f"# @{handle} — Knowledge Vault", "",
        f"- Videos published: **{published}**",
        f"- Topics: **{len(tag_index)}**",
        f"- Pipeline status: `{counts}`", "",
        "## Navigation", "",
        "- [[rules/" + f"{handle}-standards|Consolidated rulebook]]",
        "- Topic maps: " + " ".join(f"[[topics/{slugify(t)}|#{t}]]" for t in sorted(tag_index)[:30]),
        "", "## Query contract (for AI agents)", "",
        "Every note in `videos/` has YAML frontmatter with `platform`, `domain`,",
        "`tags`, and `keywords` lists. Filter with grep — no database needed:", "",
        "```bash",
        'grep -l "domain:" videos/ -r | xargs grep -l "networking"',
        "```",
    ]
    (vault_root / "INDEX.md").write_text("\n".join(index) + "\n")
    return vault_root
