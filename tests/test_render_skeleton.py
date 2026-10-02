"""Uji kerangka render ujung-ke-ujung: render 3 detik per efek."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.probe import probe  # noqa: E402
from app.render import render_edl  # noqa: E402
from app.utils import find_ffmpeg, resource_path  # noqa: E402

ROOT = resource_path(".")
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
MODEL_DIR = ROOT / "models"  # cache model Whisper (sudah diunduh)

WORDS = [{"i": i, "word": f" kata{i}", "start": i * 0.5,
          "end": i * 0.5 + 0.4, "prob": 0.99}
         for i in range(6)]  # 6 kata, 0-3 dtk


@pytest.fixture(scope="module")
def src3s(tmp_path_factory):
    out = tmp_path_factory.mktemp("render3")
    fp = out / "vert3.mp4"
    subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=540x960:rate=30:duration=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset",
         "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(fp)], check=True)
    return fp


def _edl(canvas=None, global_=None, segments=None) -> dict:
    return {
        "schema_version": 1,
        "canvas": canvas or {"aspect": "9:16", "reframe": {"mode": "none"}},
        "global": global_ or {"intensity": "medium"},
        "segments": segments or [],
    }


def _render(tmp_path, src, edl_dict, words=None, name="out") -> Path:
    edl_p = tmp_path / f"{name}.json"
    edl_p.write_text(json.dumps(edl_dict), encoding="utf-8")
    out = tmp_path / f"{name}.mp4"
    render_edl(edl_p, src, out, words=words, config=CFG,
               work_root=tmp_path / "work",
               catalog_dir=ROOT / "catalog",
               assets_dir=ROOT / "assets",
               model_dir=MODEL_DIR)
    assert out.is_file() and out.stat().st_size > 10_000
    return out


def _check(path: Path, w: int, h: int, dur: float = 3.0):
    i = probe(path)
    assert (i.width, i.height) == (w, h)
    assert abs(i.fps - 30) < 0.5
    assert abs(i.duration - dur) < 0.5


def test_render_clean_caption(tmp_path, src3s):
    edl = _edl(global_={"text_style": {"id": "text.clean_caption",
                                      "params": {}}})
    out = _render(tmp_path, src3s, edl, words=WORDS, name="caption")
    _check(out, 1080, 1920)
    ass = next((tmp_path / "work").rglob("subs.ass"))
    txt = ass.read_text(encoding="utf-8")
    assert "Dialogue" in txt and "kata0" in txt


def test_render_punch_in(tmp_path, src3s):
    edl = _edl(segments=[{"start": 0.0, "end": 3.0, "role": "hook",
                          "effects": [{"id": "camera.punch_in", "at": 1.0,
                                       "params": {"scale": 1.2}}]}])
    out = _render(tmp_path, src3s, edl, name="punchin")
    _check(out, 1080, 1920)


def test_render_clean_bright(tmp_path, src3s):
    edl = _edl(global_={"grade": {"id": "grade.clean_bright",
                                  "params": {"strength": 0.8}}})
    out = _render(tmp_path, src3s, edl, name="grade")
    _check(out, 1080, 1920)


def test_render_blur_fill(tmp_path, src3s):
    edl = _edl(canvas={"aspect": "16:9",
                       "reframe": {"mode": "blur_fill"}})
    out = _render(tmp_path, src3s, edl, name="blurfill")
    _check(out, 1920, 1080)


def test_render_param_out_of_range_clamped(tmp_path, src3s):
    # scale 99 -> dijepit ke 1.30 oleh registry, render tetap jalan
    edl = _edl(segments=[{"start": 0.0, "end": 3.0,
                          "effects": [{"id": "camera.punch_in", "at": 1.0,
                                       "params": {"scale": 99}}]}])
    out = _render(tmp_path, src3s, edl, name="clamped")
    _check(out, 1080, 1920)
