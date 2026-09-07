"""Configuration loading for TKV.

Config lives in tkv.config.yaml (cwd or --config path). API keys come ONLY
from environment variables (ANTHROPIC_API_KEY), never from the config file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_TAXONOMY = {
    "platform": ["web", "mobile", "desktop", "general"],
    "domain": [
        "networking", "database", "auth", "ui-ux", "performance",
        "security", "testing", "devops", "architecture", "general",
    ],
}


@dataclass
class WatchConfig:
    backend: str = "builtin"          # builtin | claude-watch-skill
    mode: str = "scene"               # scene | fps
    fps: float = 1.0
    max_frames_per_video: int = 20
    max_width: int = 1280
    scene_threshold: float = 0.3
    frame_budget_per_run: int = 2000


@dataclass
class Config:
    data_dir: Path = Path("data")
    vault_dir: Path = Path("vault")
    ai_backend: str = "auto"              # auto | claude-cli | anthropic-api
    model: str = "claude-sonnet-5"
    vision_model: str = "claude-sonnet-5"
    stt_backend: str = "faster-whisper"   # faster-whisper | none
    whisper_model: str = "small"
    request_delay: float = 2.0            # polite delay between TikTok requests
    max_retries: int = 3
    translate: bool = False
    taxonomy: dict = field(default_factory=lambda: dict(DEFAULT_TAXONOMY))
    watch: WatchConfig = field(default_factory=WatchConfig)

    @property
    def anthropic_api_key(self) -> str | None:
        return os.environ.get("ANTHROPIC_API_KEY")

    def channel_dir(self, handle: str) -> Path:
        return self.data_dir / handle.lstrip("@")


def load_config(path: str | Path | None = None) -> Config:
    """Load tkv.config.yaml if present; fall back to defaults."""
    cfg = Config()
    candidates = [Path(path)] if path else [Path("tkv.config.yaml")]
    for p in candidates:
        if p and p.exists():
            raw = yaml.safe_load(p.read_text()) or {}
            for key in ("model", "vision_model", "stt_backend", "whisper_model", "ai_backend"):
                if key in raw:
                    setattr(cfg, key, raw[key])
            for key in ("request_delay", "max_retries", "translate"):
                if key in raw:
                    setattr(cfg, key, raw[key])
            if "data_dir" in raw:
                cfg.data_dir = Path(raw["data_dir"])
            if "vault_dir" in raw:
                cfg.vault_dir = Path(raw["vault_dir"])
            if "taxonomy" in raw:
                cfg.taxonomy.update(raw["taxonomy"])
            for key, val in (raw.get("watch") or {}).items():
                if hasattr(cfg.watch, key):
                    setattr(cfg.watch, key, val)
            break
    return cfg
