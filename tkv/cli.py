"""TKV command-line interface."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from .config import load_config
from .manifest import Manifest

app = typer.Typer(help="TikTok Knowledge Vault — turn a TikTok channel into an "
                       "AI-queryable Obsidian vault.", no_args_is_help=True)


def _cfg(config: Optional[str]):
    return load_config(config)


def _date(value: Optional[str]):
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def _handle(profile: str) -> str:
    from .discover import normalize_profile
    return normalize_profile(profile)[0]


@app.command()
def ingest(
    profile: str = typer.Argument(..., help="TikTok profile URL or @handle"),
    since: Optional[str] = typer.Option(None, help="Only videos on/after YYYY-MM-DD"),
    until: Optional[str] = typer.Option(None, help="Only videos on/before YYYY-MM-DD"),
    no_vision: bool = typer.Option(False, "--no-vision", help="Skip the frame/vision pass"),
    config: Optional[str] = typer.Option(None, help="Path to tkv.config.yaml"),
):
    """Full pipeline: discover, acquire, transcribe, watch, enrich, build vault."""
    from .acquire import run_acquire
    from .discover import run_discover
    from .enrich import run_enrich
    from .transcribe import run_transcribe
    from .vault import run_build_vault
    from .watch import run_watch

    cfg = _cfg(config)
    typer.echo("[1/6] Discovering videos…")
    handle, new = run_discover(cfg, profile, _date(since), _date(until))
    typer.echo(f"       {new} new videos discovered for @{handle}")

    typer.echo("[2/6] Acquiring captions/audio…")
    ok, failed = run_acquire(cfg, handle)
    typer.echo(f"       acquired={ok} failed={failed}")

    typer.echo("[3/6] Transcribing…")
    ok, failed = run_transcribe(cfg, handle)
    typer.echo(f"       transcribed={ok} failed={failed}")

    typer.echo("[4/6] Watching (frames + vision)…" + (" [skipped]" if no_vision else ""))
    ok, failed = run_watch(cfg, handle, no_vision=no_vision)
    typer.echo(f"       watched={ok} failed={failed}")

    typer.echo("[5/6] Enriching with AI…")
    ok, failed = run_enrich(cfg, handle)
    typer.echo(f"       enriched={ok} failed={failed}")

    typer.echo("[6/6] Building vault…")
    vault = run_build_vault(cfg, handle)
    typer.echo(f"Done. Vault at: {vault}")


@app.command()
def watch(
    profile: str = typer.Argument(...),
    mode: str = typer.Option(None, help="scene | fps"),
    fps: float = typer.Option(None, help="Frames per second for fps mode"),
    video: Optional[str] = typer.Option(None, help="Single video id"),
    retry_failed: bool = typer.Option(False, "--retry-failed"),
    config: Optional[str] = typer.Option(None),
):
    """Frame extraction + Claude vision pass."""
    from .watch import estimate_cost, run_watch
    cfg = _cfg(config)
    handle = _handle(profile)
    manifest = Manifest(cfg.channel_dir(handle))
    n = len(manifest.pending("watched", retry_failed=retry_failed))
    typer.echo("Cost estimate: " + estimate_cost(n, cfg.watch.max_frames_per_video))
    ok, failed = run_watch(cfg, handle, mode=mode, fps=fps, only_video=video,
                           retry_failed=retry_failed)
    typer.echo(f"watched={ok} failed={failed}")


@app.command()
def resume(
    profile: str = typer.Argument(...),
    retry_failed: bool = typer.Option(False, "--retry-failed"),
    config: Optional[str] = typer.Option(None),
):
    """Continue an interrupted run from where it stopped."""
    from .acquire import run_acquire
    from .enrich import run_enrich
    from .transcribe import run_transcribe
    from .vault import run_build_vault
    from .watch import run_watch
    cfg = _cfg(config)
    handle = _handle(profile)
    for name, fn in [("acquire", run_acquire), ("transcribe", run_transcribe),
                     ("watch", run_watch), ("enrich", run_enrich)]:
        ok, failed = fn(cfg, handle, retry_failed=retry_failed)
        typer.echo(f"{name}: ok={ok} failed={failed}")
    typer.echo(f"vault: {run_build_vault(cfg, handle)}")


@app.command()
def enrich(
    profile: str = typer.Argument(...),
    retag: bool = typer.Option(False, "--retag", help="Re-run AI tagging on all videos"),
    retry_failed: bool = typer.Option(False, "--retry-failed"),
    config: Optional[str] = typer.Option(None),
):
    """Run/re-run the AI enrichment stage."""
    from .enrich import run_enrich
    ok, failed = run_enrich(_cfg(config), _handle(profile), retag=retag,
                            retry_failed=retry_failed)
    typer.echo(f"enriched={ok} failed={failed}")


@app.command("build-vault")
def build_vault(
    profile: str = typer.Argument(...),
    out: Optional[Path] = typer.Option(None, help="Vault output directory"),
    force: bool = typer.Option(False, "--force", help="Overwrite manual frontmatter edits"),
    config: Optional[str] = typer.Option(None),
):
    """Assemble/refresh the Obsidian vault."""
    from .vault import run_build_vault
    vault = run_build_vault(_cfg(config), _handle(profile), out=out, force=force)
    typer.echo(f"Vault at: {vault}")


@app.command()
def rules(
    profile: str = typer.Argument(...),
    focus: Optional[str] = typer.Option(None, help='e.g. "ux" or "mobile security"'),
    out: Optional[Path] = typer.Option(None),
    config: Optional[str] = typer.Option(None),
):
    """Regenerate the consolidated rulebook."""
    from .rules import run_rules
    path = run_rules(_cfg(config), _handle(profile), focus=focus, out=out)
    typer.echo(f"Rulebook at: {path}")


@app.command()
def status(
    profile: str = typer.Argument(...),
    config: Optional[str] = typer.Option(None),
):
    """Show pipeline counts, failures, and gaps."""
    cfg = _cfg(config)
    handle = _handle(profile)
    manifest = Manifest(cfg.channel_dir(handle))
    if not manifest.videos:
        typer.echo(f"No data for @{handle} yet — run: tkv ingest @{handle}")
        raise typer.Exit(1)
    typer.echo(f"@{handle}: {len(manifest.videos)} videos")
    for stage, count in sorted(manifest.counts().items()):
        typer.echo(f"  {stage:>20}: {count}")
    failures = [r for r in manifest.videos.values()
                if r.get("status", "").startswith("failed:")]
    if failures:
        typer.echo("\nFailures:")
        for r in failures:
            typer.echo(f"  {r['video_id']} [{r['status']}] {r.get('error','')[:100]}")
        typer.echo("\nRetry with: tkv resume @" + handle + " --retry-failed")


if __name__ == "__main__":
    app()
