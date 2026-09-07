"""Stage 1 — Discover: enumerate a channel's videos into the manifest.

Discoverer is an interface so alternate backends (TikTok Research API,
Apify, browser automation) can be plugged in when yt-dlp breaks.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date, datetime
from typing import Iterator, Protocol

from .config import Config
from .manifest import Manifest


class Discoverer(Protocol):
    def discover(self, profile_url: str, since: date | None, until: date | None) -> Iterator[dict]:
        """Yield dicts with at least: video_id, url, date, title."""
        ...


def normalize_profile(profile: str) -> tuple[str, str]:
    """Accept a full URL or @handle; return (handle, url)."""
    profile = profile.strip().rstrip("/")
    if profile.startswith("http"):
        handle = profile.split("@")[-1].split("/")[0].split("?")[0]
    else:
        handle = profile.lstrip("@")
    return handle, f"https://www.tiktok.com/@{handle}"


class YtDlpDiscoverer:
    def __init__(self, config: Config):
        self.config = config

    def discover(self, profile_url: str, since: date | None, until: date | None) -> Iterator[dict]:
        cmd = [
            "yt-dlp", "--flat-playlist", "--dump-json", "--ignore-errors",
            "--sleep-requests", str(self.config.request_delay),
        ]
        if since:
            cmd += ["--dateafter", since.strftime("%Y%m%d")]
        if until:
            cmd += ["--datebefore", until.strftime("%Y%m%d")]
        cmd.append(profile_url)

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                info = json.loads(line)
            except json.JSONDecodeError:
                continue
            vid = str(info.get("id", ""))
            if not vid:
                continue
            ts = info.get("timestamp")
            vdate = datetime.fromtimestamp(ts).date().isoformat() if ts else info.get("upload_date")
            if vdate and len(vdate) == 8 and vdate.isdigit():
                vdate = f"{vdate[:4]}-{vdate[4:6]}-{vdate[6:]}"
            yield {
                "video_id": vid,
                "url": info.get("url") or info.get("webpage_url") or f"{profile_url}/video/{vid}",
                "date": vdate,
                "title": info.get("title") or "",
                "view_count": info.get("view_count"),
                "duration": info.get("duration"),
            }
        proc.wait()


def tiktok_id_date(video_id: str) -> date | None:
    """TikTok video IDs embed a unix timestamp in the top 32 bits."""
    try:
        ts = int(video_id) >> 32
        if 1_200_000_000 < ts < 4_100_000_000:
            return datetime.fromtimestamp(ts).date()
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _in_range(info: dict, since: date | None, until: date | None) -> bool:
    if not since and not until:
        return True
    d = None
    if info.get("date"):
        try:
            d = date.fromisoformat(info["date"])
        except ValueError:
            d = None
    if d is None:
        d = tiktok_id_date(info["video_id"])
    if d is None:
        return True  # can't tell; keep it and let acquire fill the real date
    if since and d < since:
        return False
    if until and d > until:
        return False
    return True


def run_discover(config: Config, profile: str, since: date | None = None,
                 until: date | None = None) -> tuple[str, int]:
    """Discover videos and record them in the manifest. Returns (handle, new_count)."""
    handle, url = normalize_profile(profile)
    channel_dir = config.channel_dir(handle)
    channel_dir.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(channel_dir)

    discoverer = YtDlpDiscoverer(config)
    new = 0
    for info in discoverer.discover(url, since, until):
        vid = info["video_id"]
        # Post-filter by date too (flat-playlist entries often lack dates until acquire).
        if not _in_range(info, since, until):
            continue
        fields = {k: v for k, v in info.items() if k != "video_id"}
        if vid not in manifest.videos:
            new += 1
            manifest.upsert(vid, **fields, channel=f"@{handle}", status="discovered")
        else:
            manifest.upsert(vid, **{k: v for k, v in fields.items() if v})
    manifest.save()
    return handle, new
