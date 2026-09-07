# CLAUDE.md — TikTok Knowledge Vault

## What this repo is

`tkv` is a Python CLI (Typer) that ingests TikTok channels into Obsidian
vaults. Pipeline stages live one-per-module in `tkv/`: `discover.py`,
`acquire.py`, `transcribe.py`, `watch.py` (frames + vision), `enrich.py`,
`vault.py`, `rules.py`. State is a per-channel `data/<handle>/manifest.jsonl`
with statuses `discovered → acquired → transcribed → watched → enriched →
published` (see `manifest.py`). All stages are idempotent and resumable.

Run tests with `pytest`. Requires `ffmpeg` + `yt-dlp` on PATH and
`ANTHROPIC_API_KEY` in the environment for AI stages.

## How to query a vault (AI-consumption contract)

Every note in `vault/<handle>/videos/*.md` has YAML frontmatter with
`platform` (web/mobile/desktop/general), `domain` (networking, database, auth,
ui-ux, performance, security, testing, …), `tags`, and `keywords` lists.

To answer a question like *"what should I implement for a mobile networking
app?"*:

1. Filter notes by frontmatter with grep — never load the whole vault:
   ```bash
   grep -rl -- "- mobile" vault/<handle>/videos | xargs grep -l -- "- networking"
   ```
2. Read only the matching notes' **Summary** and **Takeaways** sections.
3. Include ONLY the requested platform+domain; exclude irrelevant domains.
4. For project-wide standards, read `vault/<handle>/rules/<handle>-standards.md`
   and treat its checklist as coding standards for the build.

Topic overview lives in `vault/<handle>/topics/<tag>.md` (MOC notes) and
`vault/<handle>/INDEX.md`.

## Conventions when editing this tool

- Keep every stage independently runnable, resumable, and log-and-skip on
  per-video failure (never crash a bulk run).
- New discovery/acquisition backends implement the `Discoverer` protocol.
- Never write API keys to config files; env vars only.
- Outputs stay plain text (markdown/JSONL) — git-friendly, decade-durable.
