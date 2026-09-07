"""Unit tests for TKV core logic (no network, no API)."""

from pathlib import Path

from tkv.config import load_config
from tkv.discover import normalize_profile
from tkv.manifest import Manifest
from tkv.transcribe import parse_vtt
from tkv.vault import run_build_vault, slugify


def test_normalize_profile():
    assert normalize_profile("https://www.tiktok.com/@securitytok") == (
        "securitytok", "https://www.tiktok.com/@securitytok")
    assert normalize_profile("@securitytok")[0] == "securitytok"
    assert normalize_profile("securitytok")[0] == "securitytok"


def test_manifest_roundtrip_and_resume(tmp_path):
    m = Manifest(tmp_path)
    m.upsert("v1", url="u", status="discovered")
    m.upsert("v2", url="u", status="discovered")
    m.mark("v1", "acquired")
    m.mark("v2", "failed:acquire", error="boom")

    m2 = Manifest(tmp_path)
    assert m2.reached("v1", "acquired")
    assert not m2.reached("v1", "transcribed")
    # v1 pending for transcription; failed v2 excluded unless retry_failed
    assert [r["video_id"] for r in m2.pending("transcribed")] == ["v1"]
    assert [r["video_id"] for r in m2.pending("acquired", retry_failed=True)] == ["v2"]
    assert m2.counts() == {"acquired": 1, "failed:acquire": 1}


def test_parse_vtt(tmp_path):
    vtt = tmp_path / "x.vtt"
    vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhello <b>world</b>\n\n"
        "00:00:03.000 --> 00:00:05.000\nhello world\n\n"
        "00:00:05.000 --> 00:00:07.000\nsecond line\n"
    )
    segs = parse_vtt(vtt)
    assert segs[0] == ("00:01", "hello world")
    assert segs[-1][1] == "second line"
    assert len(segs) == 2  # consecutive duplicate deduped


def test_slugify():
    assert slugify("Always Pin Your TLS Certs!!") == "always-pin-your-tls-certs"
    assert slugify("") == "video"


def test_vault_build_and_frontmatter_grep(tmp_path):
    cfg = load_config(None)
    cfg.data_dir = tmp_path / "data"
    cfg.vault_dir = tmp_path / "vault"
    ch = cfg.channel_dir("demo")
    ch.mkdir(parents=True)
    (ch / "enriched").mkdir()
    (ch / "enriched" / "v1.json").write_text(
        '{"summary":"S","takeaways":["Pin TLS certs"],"keywords":["tls"],'
        '"platform":["mobile"],"domain":["networking"],"tags":["tls"]}'
    )
    m = Manifest(ch)
    m.upsert("v1", url="https://x", date="2024-03-15", title="Pin your certs",
             status="enriched", enriched_file=str(ch / "enriched" / "v1.json"))
    m.save()

    vault = run_build_vault(cfg, "demo")
    note = vault / "videos" / "2024-03-15-pin-your-certs.md"
    text = note.read_text()
    assert "- mobile" in text and "- networking" in text  # grep contract
    assert (vault / "topics" / "networking.md").exists()
    assert (vault / "INDEX.md").exists()

    # Manual frontmatter edits respected without --force
    note.write_text(text.replace("- mobile", "- web"))
    run_build_vault(cfg, "demo")
    assert "- web" in note.read_text()
    run_build_vault(cfg, "demo", force=True)
    assert "- mobile" in note.read_text()
