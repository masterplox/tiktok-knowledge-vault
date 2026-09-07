# TikTok Knowledge Vault (TKV)

CLI tool that ingests every video from a TikTok profile, extracts transcripts
(captions → Whisper fallback), *watches* the video (ffmpeg frames + Claude
vision, so on-screen text/code/UI patterns are captured), enriches everything
with AI summaries/keywords/tags, and builds an **Obsidian vault** that AI
coding assistants can query as a long-term knowledge base.

## Setup

**1. Install the prerequisites** (Python 3.11+, plus two binaries on your PATH):

```bash
# macOS
brew install python@3.11 ffmpeg yt-dlp

# Debian / Ubuntu
sudo apt install python3 python3-venv ffmpeg && pipx install yt-dlp
```

**2. Install TKV:**

```bash
git clone https://github.com/masterplox/tiktok-knowledge-vault.git
cd tiktok-knowledge-vault
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[whisper]"     # drop [whisper] if your channels all have captions
```

**3. Verify the install** — all three should succeed:

```bash
tkv --help
ffmpeg -version | head -1
yt-dlp --version
```

**4. Pick an AI backend.** TKV needs Claude for the enrichment and vision
stages. Two options, no config file edits required:

| Backend | How to enable | Cost |
|---|---|---|
| `claude-cli` | Install [Claude Code](https://claude.com/claude-code) and log in. Auto-detected. | Included in your Claude plan |
| `anthropic-api` | `export ANTHROPIC_API_KEY=sk-ant-...` | Pay-per-token ([pricing](https://www.anthropic.com/pricing)) |

If both are available TKV prefers the CLI. Force one with
`ai_backend: claude-cli` or `ai_backend: anthropic-api` in
[tkv.config.yaml](tkv.config.yaml).

> **Keys are read from environment variables only.** TKV never writes a key to
> a config file, a log, or the vault. Do not paste keys into
> `tkv.config.yaml` — there is no field for them.

**5. Choose how speech gets transcribed.** TKV uses a video's own captions
when TikTok has them; only videos *without* captions reach a speech-to-text
backend. Set `stt_backend` in [tkv.config.yaml](tkv.config.yaml):

| `stt_backend` | Needs a key? | Notes |
|---|---|---|
| `faster-whisper` *(default)* | **No** | Runs locally and offline. Requires the `[whisper]` extra from step 2. Downloads the Whisper model on first use (size depends on `whisper_model`). |
| `watch-skill` | **Yes — `GROQ_API_KEY`** | Groq-hosted Whisper. Much faster, no local model, but sends audio to Groq and bills your Groq account. |
| `none` | No | Captions only; videos without captions are marked failed and skipped. |

**You do not need a `GROQ_API_KEY` unless you deliberately switch to
`watch-skill`.** The default is fully local. If you do switch:

```bash
export GROQ_API_KEY=gsk_...      # get one at https://console.groq.com/keys
```

TKV also accepts it from `~/.config/watch/.env` if you use the `/watch` skill.

**6. Run your first ingest.** Narrow the date range and skip the vision pass
for a cheap first run before committing to a full channel:

```bash
tkv ingest https://www.tiktok.com/@somechannel --since 2025-01-01 --no-vision
```

Happy with the output? Run the full pipeline, then add the vision pass. It
prints an estimated token cost before it starts — read that line first, and
Ctrl-C if it is higher than you want:

```bash
tkv ingest https://www.tiktok.com/@somechannel
tkv watch @somechannel
```

Then open `vault/somechannel/` as an Obsidian vault (Obsidian → *Open folder as
vault*). Plain markdown — any editor works too.

### Environment variables

| Variable | Required? | Used for |
|---|---|---|
| `ANTHROPIC_API_KEY` | Only for the `anthropic-api` backend | Enrichment + frame vision |
| `GROQ_API_KEY` | Only if you set `stt_backend: watch-skill` (step 5) | Groq-hosted Whisper transcription |

**With the shipped defaults you need neither key**: the Claude CLI backend
covers the AI stages and `faster-whisper` transcribes locally.

## Commands

```bash
tkv ingest @handle                          # full history, all 6 stages
tkv ingest @handle --since 2021-01-01 --until 2023-06-30
tkv ingest @handle --no-vision              # transcripts only (cheaper)
tkv watch @handle --mode scene              # frames + vision pass (prints cost estimate first)
tkv watch @handle --mode fps --fps 1 --video <id>
tkv resume @handle                          # continue an interrupted run
tkv resume @handle --retry-failed
tkv enrich @handle --retag                  # re-run AI tagging
tkv build-vault @handle --out ./vault
tkv rules @handle --focus ux                # regenerate consolidated rulebook
tkv status @handle                          # counts, failures, gaps
```

Config lives in [tkv.config.yaml](tkv.config.yaml). API keys come **only**
from environment variables.

## Pipeline

```
[1 Discover] → [2 Acquire] → [3 Transcribe] → [3b Watch] → [4 Enrich] → [5 Vault]
```

Every stage checkpoints per-video status in `data/<handle>/manifest.jsonl`
(`discovered → acquired → transcribed → watched → enriched → published`), so
runs are idempotent and resumable. Failures log-and-skip; `tkv status` lists
them. Temp audio/video is deleted after use; extracted frames are kept so the
vault can embed them.

## AI-consumption contract

Every vault note in `videos/` carries grep-filterable YAML frontmatter:

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

An AI agent can answer "what should I implement for a mobile networking app?"
with plain file operations — no database:

```bash
grep -rl -- "- mobile" vault/securitytok/videos | xargs grep -l -- "- networking"
```

See [CLAUDE.md](CLAUDE.md) for prompts/instructions Claude Code uses to query
vaults and operate the tool. The consolidated rulebook at
`vault/<handle>/rules/<handle>-standards.md` is the file to hand an AI
assistant as project standards.

## Ethical use

This tool is for **personal knowledge management**. Respect creators' rights:
don't republish transcripts or frames, keep vaults private, and credit
creators via the `source_url` links. Automated scraping may violate TikTok's
Terms of Service — you assume responsibility for how you use it. Audio and
video files are only stored temporarily; no full videos are retained.

## Extending

- `Discoverer` (in `tkv/discover.py`) is an interface — plug in the TikTok
  Research API, Apify, or browser automation if yt-dlp breaks.
- Taxonomy (platform/domain tags) is config-defined per channel.
- AI provider defaults to Claude; the enrichment calls are isolated in
  `tkv/enrich.py`, `tkv/watch.py`, `tkv/rules.py` for easy swapping.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ffmpeg: command not found` | Install ffmpeg and reopen your shell (step 1). |
| Discovery returns 0 videos | TikTok changed its layout, or the profile is private. Update yt-dlp: `pip install -U yt-dlp`. |
| `401` / `authentication_error` | `ANTHROPIC_API_KEY` is unset or invalid in *this* shell. Check with `echo $ANTHROPIC_API_KEY`. |
| Rate-limited or blocked by TikTok | Raise `request_delay` in the config (try `5.0`). |
| Some videos stuck as `failed` | `tkv status @handle` lists why; `tkv resume @handle --retry-failed` retries them. |
| Vision pass costs too much | `tkv ingest --no-vision`, or lower `watch.max_frames_per_video`. |

Interrupted runs are always safe to restart — every stage is idempotent.
`tkv resume @handle` picks up exactly where it stopped.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Issues and pull requests are welcome.

## License

MIT — see [LICENSE](LICENSE).
