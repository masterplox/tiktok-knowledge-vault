# PRD: TikTok Knowledge Vault (TKV)

**Version:** 1.0
**Status:** Draft
**Intended executor:** Claude Code (agentic implementation)
**License goal:** Open source / publicly reusable

---

## 1. Overview

TikTok Knowledge Vault (TKV) is a CLI-first application that ingests all videos from a given TikTok profile (optionally within a date range), extracts transcripts, stores them in a structured repository, and uses AI to generate summaries, keywords, and topic-tagged knowledge files organized as an Obsidian vault. The vault becomes a long-term, searchable "second brain" that AI coding assistants (e.g., Claude Code) can query as a knowledge base when building new applications.

### Primary use cases
1. **Security knowledge base:** Ingest a security-focused TikTok channel. When vibe-coding a new app, the AI reads the vault and surfaces only the security practices relevant to the app type (web vs. mobile) and domain (e.g., networking vs. database).
2. **UX best-practices rulebook:** Ingest a UX design channel. Generate a standing `RULES.md` / TODO-style file (e.g., "use skeleton loading when X, progress indicators when Y") that AI assistants treat as project standards for every new build.
3. **Long-horizon recall:** Years later, type a single keyword in Obsidian and pull up every transcript, summary, and lesson learned on that topic.

---

## 2. Goals & Non-Goals

### Goals
- Ingest the complete video history of any TikTok profile from a URL, or a user-specified date range.
- Extract transcripts reliably (captions when available; speech-to-text fallback).
- Store raw transcripts + metadata in a durable, versionable repository (git-friendly plain text).
- AI-generated per-video summaries, keywords, and topic tags.
- Generate AI-parseable markdown knowledge files, filterable by platform (web/mobile), domain (networking, database, auth, etc.), and topic.
- Produce an Obsidian-compatible vault (wikilinks, tags, frontmatter, MOC index notes).
- Idempotent + resumable: re-running only processes new videos; failures resume mid-run.
- Built to last years: minimal fragile dependencies, pluggable extractors, config-driven.
- Publicly reusable: documented, MIT/Apache licensed, no hardcoded personal data.

### Non-Goals
- Downloading/storing full video files long-term (audio is temporary, deleted after transcription).
- Re-hosting or republishing creators' content publicly (vault is for personal knowledge use).
- A GUI (v1 is CLI; GUI is future work).
- Real-time monitoring (scheduled/manual runs are sufficient in v1).

---

## 3. User Stories

| ID | Story |
|----|-------|
| U1 | As a user, I provide a TikTok profile URL and get every video's transcript extracted and stored. |
| U2 | As a user, I can pass `--since 2020-01-01 --until 2024-12-31` to limit the crawl range. |
| U3 | As a user, I can re-run the tool and it only processes videos not already in the repo. |
| U4 | As a user, I get an Obsidian vault where each video is a note with summary, keywords, tags, and a link to the full transcript. |
| U5 | As a user, I can ask my AI assistant "what should I implement for a mobile networking app?" and it reads only the notes tagged `#mobile` + `#networking`. |
| U6 | As a user, I can generate a consolidated `rules/ux-standards.md` distilled from a UX channel, used as coding standards. |
| U7 | As a user, I can search one keyword in Obsidian and surface all related transcripts and summaries across years. |
| U8 | As a maintainer, I can swap the transcript extraction backend without touching the rest of the pipeline. |
| U9 | As a public user, I can clone the repo, add my own API keys, and run it on any channel. |

---

## 4. System Architecture

Pipeline of 5 decoupled stages, each independently runnable and resumable:

```
[1 Discover] → [2 Acquire] → [3 Transcribe] → [3b Watch (Frames + Vision)] → [4 Enrich (AI)] → [5 Vault Build]
```

### Stage 1 — Discover
- Input: profile URL (e.g., `https://www.tiktok.com/@handle`) + optional date range.
- Enumerate all video IDs, URLs, post dates, captions, hashtags, view counts.
- Primary backend: `yt-dlp` (actively maintained, handles TikTok). Abstraction layer (`Discoverer` interface) so alternate backends (TikTok Research API, Apify, browser automation) can be plugged in when yt-dlp breaks.
- Output: `data/<handle>/manifest.jsonl` (one JSON object per video).

### Stage 2 — Acquire
- Download audio-only (smallest footprint) for videos lacking usable captions.
- If TikTok provides subtitle tracks, download those instead and skip audio.
- Temp storage only; audio deleted after Stage 3 succeeds.

### Stage 3 — Transcribe
- Priority order: (a) native TikTok captions → (b) local Whisper (faster-whisper) → (c) cloud STT (configurable, optional).
- Output: `data/<handle>/transcripts/<video_id>.md` with YAML frontmatter (video_id, url, date, title/caption, duration, extraction_method, language).
- Language detection + original-language transcript; optional translation flag.

### Stage 3b — Watch (Frame Extraction + Visual Understanding)
Adopts the approach of the Claude Code `/watch` skill ecosystem (yt-dlp + ffmpeg frames + timestamped transcript handed to Claude's vision) so Claude can "see" what's on screen, not just hear it. This matters for TikTok specifically: creators rely heavily on text overlays, code snippets, UI walkthroughs, and diagrams that never appear in the audio transcript.

- **Frame extraction (ffmpeg), two configurable modes:**
  - `scene` (default): one frame per detected shot/scene change — bounded frame count regardless of video length, keeps vision-token cost flat.
  - `fps`: uniform sampling at N frames per second (`--fps 1`, `--fps 2`, etc.) for videos where dense coverage is needed.
- **Frame storage:** `data/<handle>/frames/<video_id>/<timestamp>.jpg` — frames are kept (unlike temp audio) so the vault can embed or link them.
- **Visual interpretation:** frames + timestamped transcript are sent together to Claude (vision). Output per video, saved to `data/<handle>/visual/<video_id>.md`:
  - Timestamped visual log ("0:03 — text overlay: 'always pin your TLS certs'", "0:07 — screen recording of Xcode settings")
  - OCR/extraction of on-screen text, code, and slide content
  - Description of demonstrated UI patterns (critical for the UX-channel use case, e.g., recognizing a skeleton loader vs. progress bar being shown)
- **Fused understanding:** Stage 4 enrichment consumes transcript + visual log together, so takeaways include screen-only information.
- **Integration options (config flag `watch.backend`):**
  - `builtin`: TKV's own ffmpeg/vision pipeline (default; no external skill dependency, needed for long-term reliability)
  - `claude-watch-skill`: delegate to an installed Claude Code `/watch` skill when TKV is run as a Claude Code project
- **Cost controls:** per-run frame budget, per-video frame cap (default ~20 for scene mode), image downscaling to 1280px, cost estimate printed before a bulk vision run, `--no-vision` flag for transcript-only ingestion.
- Resumable/idempotent like every other stage: per-video `watched` status in the manifest.

### Stage 4 — Enrich (AI)
- Per-video, call an LLM (Claude API; model configurable) with **both the transcript and the Stage 3b visual log** to produce:
  - 2–4 sentence summary
  - Bullet list of actionable takeaways ("things to implement / consider")
  - Keywords (5–15)
  - Structured tags along two axes:
    - **platform:** `web`, `mobile`, `desktop`, `general`
    - **domain:** `networking`, `database`, `auth`, `ui-ux`, `performance`, `security`, `testing`, etc. (taxonomy is config-defined per channel, extensible)
- Output written into the note frontmatter + body. Enrichment is cached; only new/changed transcripts are re-enriched.

### Stage 5 — Vault Build
- Assemble Obsidian vault at `vault/<handle>/`:
  - `videos/<date>-<slug>.md` — one note per video (frontmatter tags, summary, takeaways, wikilinks, embedded full transcript or link to it, timestamped visual log, and embedded key frames `![[frames/<video_id>/<ts>.jpg]]`)
  - `topics/<tag>.md` — MOC (Map of Content) notes auto-listing all videos per tag
  - `rules/<channel>-standards.md` — **consolidated rulebook**: AI-distilled, deduplicated best-practices checklist across the whole channel, grouped by platform/domain. This is the file AI assistants read when coding.
  - `INDEX.md` — vault home with channel info, stats, and navigation
- All markdown uses consistent frontmatter so AI agents can filter mechanically:

```yaml
---
video_id: "7301234567"
channel: "@securitytok"
date: 2024-03-15
platform: [mobile]
domain: [networking]
tags: [security, tls, certificate-pinning]
source_url: https://...
---
```

### AI-consumption contract (critical requirement)
The vault must be queryable by an AI agent with simple file operations: "find all notes where `platform` contains `mobile` AND `domain` contains `networking`" must be answerable via frontmatter grep — no database required. Document this contract in the repo README with example prompts for Claude Code (e.g., a bundled `CLAUDE.md` / skill file telling the agent how to query the vault).

---

## 5. CLI Interface

```
tkv ingest https://www.tiktok.com/@securitytok            # full history
tkv ingest @securitytok --since 2021-01-01 --until 2023-06-30
tkv ingest @securitytok --no-vision                        # transcripts only (cheaper)
tkv watch @securitytok --mode scene                        # frame extraction + vision pass
tkv watch @securitytok --mode fps --fps 1 --video <id>     # dense per-second frames for one video
tkv resume @securitytok                                    # continue failed run
tkv enrich @securitytok --retag                            # re-run AI stage
tkv build-vault @securitytok --out ./vault
tkv rules @securitytok --focus ux                          # regenerate rulebook
tkv status @securitytok                                    # counts, failures, gaps
```

Config: `tkv.config.yaml` (API keys via env vars only — never in config), per-channel taxonomy overrides, rate-limit settings, STT backend choice.

---

## 6. Reliability & Longevity Requirements ("won't fail, usable for years")

| Requirement | Implementation |
|---|---|
| Resumable | Every stage checkpoints per-video status in `manifest.jsonl` (`discovered → acquired → transcribed → enriched → published`). Crash-safe; rerun continues. |
| Idempotent | Video ID is the primary key; existing outputs are skipped unless `--force`. |
| Rate-limit safe | Configurable delays, exponential backoff, jitter; polite defaults to avoid TikTok blocks. |
| Extractor churn | `Discoverer`/`Acquirer` behind interfaces; yt-dlp pinned but upgradeable; failures degrade to "log and skip," never crash the run. |
| Data durability | All outputs are plain text markdown/JSONL in a git repo — no proprietary formats, future-proof for a decade. |
| Failure reporting | `tkv status` lists failed videos with reasons; `--retry-failed` flag. |
| Testing | Unit tests per stage, integration test against a small fixture channel, CI on GitHub Actions. |

---

## 7. Public Reusability Requirements

- MIT or Apache-2.0 license.
- Zero hardcoded channels, keys, or personal paths.
- `README.md` with quickstart (<5 commands from clone to first vault).
- `CLAUDE.md` in repo so Claude Code can operate/extend the tool and query vaults.
- Ethical-use section: personal knowledge use, respect creators' rights, don't republish transcripts, comply with TikTok ToS; note that scraping approach may violate ToS and users assume responsibility.
- Configurable AI provider (Claude default; provider interface for others).

---

## 8. Tech Stack (recommended)

- **Language:** Python 3.11+ (best ecosystem for yt-dlp + Whisper)
- **Discovery/download:** yt-dlp
- **Transcription:** faster-whisper (local, free) with cloud STT optional
- **AI enrichment:** Anthropic API (Claude), model in config
- **Storage:** plain files + JSONL manifest, git for versioning
- **CLI:** Typer or Click
- **Packaging:** pipx-installable; optional Dockerfile

---

## 9. Milestones

1. **M1 – Skeleton & Discover:** CLI, config, manifest, yt-dlp discovery with date range. ✅ Acceptance: full video list for a test channel in manifest.jsonl.
2. **M2 – Transcripts:** caption fetch + Whisper fallback, resumable. ✅ Acceptance: transcripts for 100% of accessible videos; failures logged, not fatal.
3. **M2b – Watch:** ffmpeg frame extraction (scene + fps modes), Claude vision pass, visual logs, frame storage, cost estimator. ✅ Acceptance: on-screen-only info (e.g., a text overlay never spoken aloud) appears in the visual log and downstream takeaways.
4. **M3 – Enrichment:** summaries, keywords, platform/domain tagging. ✅ Acceptance: frontmatter filterable by grep.
4. **M4 – Vault:** per-video notes, topic MOCs, INDEX. ✅ Acceptance: opens cleanly in Obsidian; keyword search surfaces expected notes.
5. **M5 – Rulebook:** consolidated standards file (UX use case). ✅ Acceptance: Claude Code, given the rules file, applies the standards in a sample project.
6. **M6 – Hardening & Release:** retries, status command, tests, docs, license, public repo.

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| TikTok blocks scraping / yt-dlp breaks | Pluggable discoverer; official Research API adapter as alternative; graceful degradation |
| Huge channels (1000s of videos) = long runs & API cost | Batching, cost estimate before enrichment, local Whisper default |
| Vision/frame tokens explode costs on bulk runs | Scene-change mode default (frames bounded by cuts, not duration), per-video frame caps, downscaling, pre-run cost estimate, `--no-vision` escape hatch |
| Auto-tagging misclassifies platform/domain | Taxonomy in config, `--retag` re-runs, manual frontmatter edits are respected (never overwritten without `--force`) |
| ToS/copyright concerns for a public tool | Ship the tool (not data); ethical-use docs; transcripts stay in user's private vault |

---

## 11. Success Metrics

- ≥95% of a channel's accessible videos end with a transcript on first full run.
- A rerun after interruption completes without duplicating work.
- An AI agent, given only the vault + query contract, correctly answers a platform+domain filtered question (e.g., mobile networking security items) with zero irrelevant domains included.
- A stranger can clone, configure, and produce a vault from a channel of their choice using only the README.
