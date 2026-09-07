"""M5 — Rulebook: distill a consolidated, deduplicated standards file.

Reads all enriched takeaways for a channel and asks Claude to merge them into
vault/<handle>/rules/<handle>-standards.md grouped by platform/domain.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import Config
from .manifest import Manifest

RULES_PROMPT = """You are distilling a coding-standards rulebook from a TikTok channel's
video takeaways. Merge, deduplicate, and organize the raw items below into a
markdown checklist that an AI coding assistant will treat as project standards.

{focus_line}

Requirements:
- Group by platform (web / mobile / desktop / general), then by domain.
- Each rule: one imperative checklist line ("- [ ] Use skeleton loaders when ...").
- Include the condition/context when the source gave one ("when X, do Y").
- Deduplicate aggressively; merge near-identical advice.
- End with a short "How AI assistants should use this file" section.

Raw takeaways (JSON, one object per video):
{items}

Respond with only the markdown rulebook."""


def run_rules(config: Config, handle: str, focus: str | None = None,
              out: Path | None = None) -> Path:
    from .ai import complete
    channel_dir = config.channel_dir(handle)
    manifest = Manifest(channel_dir)

    items = []
    for rec in manifest.videos.values():
        f = rec.get("enriched_file")
        if f and Path(f).exists():
            data = json.loads(Path(f).read_text())
            items.append({
                "title": rec.get("title", ""),
                "date": rec.get("date"),
                "platform": data.get("platform"),
                "domain": data.get("domain"),
                "takeaways": data.get("takeaways", []),
            })
    if not items:
        raise RuntimeError("no enriched videos yet — run `tkv enrich` first")

    focus_line = f"Focus the rulebook on: {focus}." if focus else ""
    text = complete(config, RULES_PROMPT.format(
        focus_line=focus_line,
        items=json.dumps(items, ensure_ascii=False)[:150000],
    ), max_tokens=6000)
    rules_dir = (out or config.vault_dir) / handle / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    path = rules_dir / f"{handle}-standards.md"
    path.write_text(text)
    return path
