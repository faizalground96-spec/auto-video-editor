"""Uji Tahap 7: SFX otomatis — sintesis, cue, trek, ducking, QA audio."""
import json
import subprocess
import sys
import wave
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.render import render_edl  # noqa: E402
from app.sfx import (build_sfx_track, collect_cues, ducking_filter,  # noqa: E402
                     rms_db)
from app.utils import find_ffmpeg, resource_path  # noqa: E402

ROOT = resource_path(".")
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
SFX_DIR = ROOT / "assets" / "sfx"


def _wav_dur(p: Path) -> float:
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


# --- sintesis ---------------------------------------------------------------
def test_sfx_files_ada_dan_valid():
    for name in ("swoosh", "boom", "pop", "riser"):
        p = SFX_DIR / f"{name}.wav"
        assert p.is_file(), f"{name}.wav tak ada"
        with wave.open(str(p)) as w:
            assert w.getnchannels() == 1
            assert w.getframerate() == 44100
        # ternormalisasi ke -20 dBFS
        assert abs(rms_db(p, 0, _wav_dur(p)) - (-20.0)) < 1.5


# --- cue --------------------------------------------------------------------
class _Meta:
    def __init__(self, sfx, category):
        self.sfx = sfx
        self.category = category


class _Entry:
    def __init__(self, sfx, category="camera"):
        self.meta = _Meta(sfx, category)


class _Reg:
    def __init__(self, mapping):
        self.entries = {k: _Entry(*v) for k, v in mapping.items()}


class _Ef:
    def __init__(self, id, at, params=None):
        self.id = id
        self.at = at
        self.params = params or {}


class _Seg:
    def __init__(self, start, end, effects):
        self.start = start
        self.end = end
        self.effects = effects


class _Edl:
    def __init__(self, segments, emphasis=None):
        self.segments = segments
        self.emphasis_words = emphasis or []


def test_collect_cues_dari_at_dan_seg_start():
    reg = _Reg({"camera.whip_pan": ("swoosh", "transition"),
                "overlay.emoji_burst": ("pop", "overlay"),
                "camera.slow_zoom": (None, "camera")})
    edl = _Edl([_Seg(0.0, 10.0, [_Ef("camera.whip_pan", 3.0),
                                 _Ef("overlay.emoji_burst", None),
                                 _Ef("camera.slow_zoom", None)])])
    cues = collect_cues(edl, reg, [])
    assert {(c["t"], c["sfx"]) for c in cues} == {(3.0, "swoosh"), (0.0, "pop")}


def test_collect_cues_teks_hanya_di_emphasis():
    reg = _Reg({"text.pop_in_word": ("pop", "text")})
    edl = _Edl([_Seg(0.0, 10.0, [_Ef("text.pop_in_word", None)])],
               emphasis=[{"start": 2.0, "end": 2.3, "word": "x"},
                         {"start": 5.0, "end": 5.3, "word": "y"}])
    cues = collect_cues(edl, reg, [])
    assert [c["t"] for c in cues] == [2.0, 5.0]


def test_collect_cues_dedupe():
    reg = _Reg({"overlay.emoji_burst": ("pop", "overlay")})
    edl = _Edl([_Seg(0.0, 10.0, [_Ef("overlay.emoji_burst", 1.0),
                                 _Ef("overlay.emoji_burst", 1.05)])])
    assert len(collect_cues(edl, reg, [])) == 1


# --- trek -------------------------------------------------------------------
def test_build_sfx_track(tmp_path):
    cues = [{"t": 0.5, "sfx": "pop", "why": "x"},
            {"t": 1.5, "sfx": "swoosh", "why": "y"}]
    out = tmp_path / "sfx.wav"
    got = build_sfx_track(cues, 3.0, SFX_DIR, out, volume=0.4)
    assert got == out and out.is_file()
    assert abs(_wav_dur(out) - 3.0) < 0.1
    # ada energi di sekitar cue, hening di awal
    assert rms_db(out, 0.0, 0.4) == float("-inf")
    assert rms_db(out, 0.5, 0.7) > float("-inf")


def test_build_sfx_track_tanpa_cue(tmp_path):
    assert build_sfx_track([], 3.0, SFX_DIR, tmp_path / "x.wav") is None


def test_ducking_filter_memakai_sidechain():
    f = ducking_filter(0.4)
    assert "sidechaincompress" in f
    assert "normalize=0" in f
    assert "[aout]" in f


# --- render ujung-ke-ujung ---------------------------------------------------
@pytest.fixture(scope="module")
def src6s(tmp_path_factory):
    out = tmp_path_factory.mktemp("sfx6")
    fp = out / "s6.mp4"
    subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=540x960:rate=30:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset",
         "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(fp)], check=True)
    return fp


def _edl_sfx() -> dict:
    return {
        "schema_version": 2,
        "canvas": {"aspect": "9:16", "reframe": {"mode": "none"}},
        "global": {"intensity": "medium",
                   "text_style": {"id": "text.pop_in_word", "params": {}},
                   "grade": {"id": "grade.cinematic", "params": {}}},
        "segments": [{
            "start": 0.0, "end": 6.0, "role": "main_content", "why": "uji",
            "effects": [
                {"id": "camera.punch_in", "at": 1.0, "params": {}},
                {"id": "transition.whip", "at": 3.0, "params": {}},
            ],
        }],
    }


def test_render_dengan_sfx_qa_lulus(tmp_path, src6s):
    edl_p = tmp_path / "edl.json"
    edl_p.write_text(json.dumps(_edl_sfx()), encoding="utf-8")
    out = tmp_path / "out.mp4"
    res = render_edl(edl_p, src6s, out, words=[], config=CFG,
                     work_root=tmp_path / "work",
                     catalog_dir=ROOT / "catalog",
                     assets_dir=ROOT / "assets",
                     model_dir=ROOT / "assets" / "models")
    assert out.is_file()
    qa = res["qa"]
    assert qa["passed"], json.dumps(qa["checks"], indent=1)
    ac = qa["checks"]["audio"]
    assert ac["status"] == "pass", ac["detail"]
    m = ac["metrics"]
    assert m["max_diff_db"] <= 0.5, m          # ucapan ±0,5 dB
    assert m["min_sfx_margin_db"] >= 10.0, m   # SFX >= 10 dB di bawah


def test_render_calm_tanpa_sfx(tmp_path, src6s):
    edl = _edl_sfx()
    edl["global"]["intensity"] = "calm"
    # calm: maks 1 efek kuat / 10 dtk -> sisakan satu
    edl["segments"][0]["effects"] = [
        {"id": "camera.punch_in", "at": 1.0, "params": {}}]
    edl_p = tmp_path / "edl.json"
    edl_p.write_text(json.dumps(edl), encoding="utf-8")
    out = tmp_path / "out.mp4"
    res = render_edl(edl_p, src6s, out, words=[], config=CFG,
                     work_root=tmp_path / "work",
                     catalog_dir=ROOT / "catalog",
                     assets_dir=ROOT / "assets",
                     model_dir=ROOT / "assets" / "models")
    assert res["qa"]["passed"]
    assert "audio" in res["qa"]["checks"]  # cek biasa, bukan audio_sfx
