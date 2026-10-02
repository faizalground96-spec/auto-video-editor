"""Uji Tahap 6: Gemini -> EDL (offline; FakeClient, tanpa jaringan)."""
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.analyze import (FakeClient, analyze_video, build_system_prompt,  # noqa: E402
                         build_transcript_indexed, fallback_edl)
from app.registry import EffectRegistry  # noqa: E402
from app.utils import resource_path  # noqa: E402
from app.validate import validate_edl  # noqa: E402

ROOT = resource_path(".")
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
FIX = ROOT / "tests" / "fixtures"

WORDS = [{"i": i, "word": w, "start": round(i * 0.4, 3),
          "end": round(i * 0.4 + 0.32, 3), "prob": 0.99}
         for i, w in enumerate(
             "ini adalah contoh kata untuk uji efek teks kinetik".split())]
SILENCES = [{"start": 3.6, "end": 4.0}]
DUR = 10.0


def _reg():
    return EffectRegistry(ROOT / "catalog", ROOT / "assets").load()


def _val(raw, **kw):
    args = dict(registry=_reg(), words=WORDS, silences=SILENCES,
                duration=DUR, aspect="9:16", cfg=CFG, dry_run=True)
    args.update(kw)
    return validate_edl(raw, **args)


# -- FakeClient -------------------------------------------------------------
def test_fakeclient_bagus_lulus():
    raw = FakeClient(FIX / "gemini_bagus.json").analyze(None)
    ok, errors, edl = _val(raw)
    assert ok, errors
    assert edl["global"]["intensity"] == "medium"
    assert edl["segments"][0]["effects"][0]["id"] == "camera.slow_zoom"
    assert edl["emphasis_words"][0]["word"] == "contoh"


def test_fakeclient_rusak_diperbaiki():
    raw = FakeClient(FIX / "gemini_rusak.json").analyze(None)
    ok, errors, edl = _val(raw)
    val = edl["_validation"]
    dropped = " ".join(val["dropped"])
    fixed = " ".join(val["fixed"])

    # ID palsu & status beta dibuang
    assert "efek.tidak_ada" in dropped
    assert "face_grid" in dropped
    # param di luar batas dijepit, param tak dikenal dibuang
    assert edl["global"]["grade"]["params"]["strength"] == 1.0
    assert "param_ngawur" not in edl["global"]["grade"]["params"]
    # intensity & reframe dikoreksi
    assert edl["global"]["intensity"] == "medium"
    assert edl["canvas"]["reframe"]["mode"] in (
        "none", "smart_crop", "blur_fill", "fit_letterbox")
    # kategori kamera ganda -> satu dibuang
    cam = [e for e in edl["segments"][0]["effects"]
           if e["id"].startswith("camera.")]
    assert len(cam) == 1
    # emoji_burst tanpa at dibuang (requires_at)
    assert not any(e["id"] == "overlay.emoji_burst"
                   for s in edl["segments"] for e in s["effects"])
    # emphasis salah dibuang semua
    assert edl["emphasis_words"] == []
    # closing ber-URL dibuang
    assert edl["closing"] is None
    # timestamp di luar durasi dijepit
    assert all(s["end"] <= DUR + 0.01 for s in edl["segments"])
    assert ok or errors  # boleh lulus dengan perbaikan


def test_snapping_ke_batas_kata():
    raw = {"schema_version": 2, "canvas": {"aspect": "9:16"},
           "global": {"intensity": "calm"},
           "segments": [{"start": 0.05, "end": 3.9, "role": "body",
                         "effects": []}]}
    ok, errors, edl = _val(raw)
    assert ok, errors
    # 0.05 -> 0.0 (batas kata), 3.9 -> 3.8 (tengah jeda 3.6-4.0)
    assert edl["segments"][0]["start"] == 0.0
    assert edl["segments"][0]["end"] == pytest.approx(3.8)


def test_anggaran_efek_kuat():
    # 6 emoji_burst (strong) dalam 10 detik, intensitas calm (batas 1)
    effs = [{"id": "overlay.emoji_burst", "at": float(t),
             "params": {"sticker": "burst"}} for t in range(6)]
    raw = {"schema_version": 2, "canvas": {"aspect": "9:16"},
           "global": {"intensity": "calm"},
           "segments": [{"start": 0.0, "end": 9.0, "role": "body",
                         "effects": effs}]}
    ok, errors, edl = _val(raw)
    kept = [e for s in edl["segments"] for e in s["effects"]]
    assert len(kept) <= 1  # calm: maks 1 kuat per 10 detik


def test_fallback_edl_valid():
    raw = fallback_edl(DUR, "9:16")
    ok, errors, edl = _val(raw)
    assert ok, errors


def test_analyze_video_dengan_fakeclient(tmp_path):
    import subprocess
    reg = _reg()
    src = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=320x240:d=2:r=30",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=2",
                    "-shortest", str(src)], check=True)
    raw = analyze_video(src, WORDS, SILENCES, "1 wajah tengah",
                        reg, FakeClient(FIX / "gemini_bagus.json"),
                        CFG, tmp_path / "work", aspect="9:16")
    assert raw["global"]["intensity"] == "medium"
    # cache dipakai kedua kali
    raw2 = analyze_video(src, WORDS, SILENCES, "1 wajah tengah",
                         reg, FakeClient(FIX / "gemini_rusak.json"),
                         CFG, tmp_path / "work", aspect="9:16")
    assert raw2["global"]["intensity"] == "medium"  # dari cache, bukan rusak


def test_prompt_terisi():
    p = build_system_prompt(CFG, "9:16", "vertical", "vertical", "lebih kalem")
    assert "{aspect}" not in p and "9:16" in p
    assert "lebih kalem" in p


def test_transcript_indexed():
    t = build_transcript_indexed(WORDS[:3])
    assert t == "[0] ini [1] adalah [2] contoh"
