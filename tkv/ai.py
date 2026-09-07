"""AI backend abstraction.

Two backends:
- "claude-cli" (default): shells out to the local `claude` CLI in headless mode
  (`claude -p`). Uses the user's Claude Code login/subscription — no API key.
  For vision, frame paths are passed and Claude reads the images itself.
- "anthropic-api": direct Anthropic API calls; requires ANTHROPIC_API_KEY.

Selection: config `ai_backend`, else claude-cli if the `claude` binary exists,
else anthropic-api.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path


def resolve_backend(config) -> str:
    backend = getattr(config, "ai_backend", "auto")
    if backend in ("claude-cli", "anthropic-api"):
        return backend
    if shutil.which("claude"):
        return "claude-cli"
    if config.anthropic_api_key:
        return "anthropic-api"
    raise RuntimeError(
        "No AI backend available: install the `claude` CLI (recommended, uses "
        "your Claude Code login) or set ANTHROPIC_API_KEY."
    )


def _claude_cli(prompt: str, allow_read: list[Path] | None = None,
                timeout: int = 600) -> str:
    cmd = ["claude", "-p", "--output-format", "text"]
    if allow_read:
        cmd += ["--allowedTools", "Read"]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                       timeout=timeout)
    if r.returncode != 0:
        detail = (r.stderr.strip() or r.stdout.strip())[-400:]
        if "authenticate" in detail.lower() or "OAuth" in detail:
            detail += " — run `claude login` in your terminal, or set ANTHROPIC_API_KEY."
        raise RuntimeError(f"claude CLI failed: {detail}")
    return r.stdout.strip()


def complete(config, prompt: str, max_tokens: int = 2000,
             model: str | None = None) -> str:
    """Plain text completion."""
    if resolve_backend(config) == "claude-cli":
        return _claude_cli(prompt)
    import anthropic
    msg = anthropic.Anthropic().messages.create(
        model=model or config.model, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def complete_with_images(config, prompt: str, image_paths: list[Path],
                         max_tokens: int = 2000, model: str | None = None) -> str:
    """Completion over images + text."""
    if resolve_backend(config) == "claude-cli":
        listing = "\n".join(f"- {p.resolve()} (timestamp/frame {p.stem})"
                            for p in image_paths)
        full = (
            "Read and view each of these video frame images with the Read tool:\n"
            f"{listing}\n\n{prompt}"
        )
        return _claude_cli(full, allow_read=image_paths, timeout=900)
    import anthropic
    content: list[dict] = []
    for p in image_paths:
        content.append({"type": "text", "text": f"Frame {p.stem}:"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.b64encode(p.read_bytes()).decode()},
        })
    content.append({"type": "text", "text": prompt})
    msg = anthropic.Anthropic().messages.create(
        model=model or config.vision_model, max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
    )
    return msg.content[0].text
