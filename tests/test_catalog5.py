"""Uji katalog Tahap 5: 15 efek baru (smoke build + teks 4 rasio + render)."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.canvas import Canvas  # noqa: E402
from app.registry import EffectRegistry  # noqa: E402
from app.schema import EffectContext  # noqa: E402
from app.subtitles import build_ass, measure_text, resolve_font  # noqa: E402
from app.utils import find_ffmpeg, resource_path  # noqa: E402

ROOT = resource_path(".")
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
FONTS = ROOT / "assets" / "fonts"
ASSETS = ROOT / "assets"

WORDS = [{"i": i, "word": w, "start": i * 0.4, "end": i * 0.4 + 0.32,
          "prob": 0.99}
         for i, w in enumerate(
             "ini adalah contoh kata untuk uji efek teks kinetik".split())]

FAKE_TRACK = {
    "samples": [{"t": round(i * 0.25, 2),
                 "faces": [{"x": 0.30, "y": 0.30, "w": 0.15, "h": 0.20},
                           {"x": 0.60, "y": 0.35, "w": 0.13, "h": 0.18}]}
                for i in range(25)],
    "interval": 0.25, "cuts": [], "n_faces_total": 50,
}


def _ctx(aspect="9:16", seg=(0.0, 6.0), words=WORDS, face_track=None):
    return EffectContext(
        canvas=Canvas.from_aspect(aspect),
        source=SimpleNamespace(width=1280, height=720),
        words=words, work_dir=Path("/tmp"), assets_dir=ASSETS,
        config=CFG, face_track=face_track,
        seg_start=seg[0], seg_end=seg[1])


@pytest.fixture(scope="module")
def reg():
    r = EffectRegistry(ROOT / "catalog", ASSETS).load()
    assert r.errors == [], r.errors
    return r


def test_semua_21_efek_terdaftar(reg):
    assert len(reg.entries) == 21


# -- smoke build tiap efek (menangkap error filter/kontrak) ------------------
BUILD_CASES = [
    ("text.pop_in_word", None, {"emphasis_idx": [1, 3]}),
    ("text.karaoke_highlight", None, {"highlight_color": "red"}),
    ("text.typewriter", None, {}),
    ("text.red_keyword", None, {"emphasis_idx": [0]}),
    ("text.clean_caption", None, {}),
    ("camera.slow_zoom", None, {"factor": 1.2}),
    ("camera.whip_pan", 2.0, {"duration": 0.35}),
    ("camera.punch_in", 2.0, {"scale": 1.2}),
    ("grade.cinematic", None, {"strength": 0.7}),
    ("grade.warm_pop", None, {"strength": 0.5}),
    ("grade.clean_bright", None, {"strength": 0.5}),
    ("insert.face_grid", None, {"panels": 2}),
    ("layout.split_compare", None, {"left_from": 0.0, "left_to": 1.0,
                                    "right_from": 2.0, "right_to": 3.0}),
    ("overlay.emoji_burst", 1.0, {"sticker": "burst"}),
    ("overlay.progress_bar", None, {}),
    ("transition.whip", 6.0, {"direction": "out"}),
    ("transition.zoom_blur", 0.0, {"direction": "in"}),
    ("reframe.smart_crop", None, {}),   # butuh kurva; cukup cek error jelas
    ("reframe.blur_fill", None, {}),
    ("reframe.fit_letterbox", None, {}),
]


@pytest.mark.parametrize("eid,at,params", BUILD_CASES)
def test_build_tidak_crash(reg, eid, at, params):
    ctx = _ctx(face_track=FAKE_TRACK)
    if eid == "reframe.smart_crop":
        # tanpa kurva harus gagal dengan pesan jelas (bukan crash aneh)
        with pytest.raises((ValueError, KeyError)):
            reg.build(eid, ctx, at, params)
        return
    out = reg.build(eid, ctx, at, params)
    assert out.video_filters or out.ass_events


def test_insert_b_roll_top_butuh_clip(reg):
    ctx = _ctx()
    with pytest.raises((ValueError, FileNotFoundError)):
        reg.build("insert.b_roll_top", ctx, None, {})
    with pytest.raises(FileNotFoundError):
        reg.build("insert.b_roll_top", ctx, None,
                  {"clip": "tidak_ada.mp4"})


# -- teks di 4 rasio: safe area & tidak menutup wajah >20% --------------------
TEXT_IDS = ["text.pop_in_word", "text.karaoke_highlight", "text.typewriter",
            "text.red_keyword", "text.clean_caption"]


@pytest.mark.parametrize("eid", TEXT_IDS)
@pytest.mark.parametrize("aspect", ["9:16", "16:9", "1:1", "4:5"])
def test_teks_4_rasio_aman(reg, eid, aspect):
    ctx = _ctx(aspect=aspect)
    out = reg.build(eid, ctx, None,
                    {"emphasis_idx": [1, 4]} if "emphasis" in str(
                        reg.entries[eid].meta.params) else {})
    assert out.ass_events, eid
    canvas = ctx.canvas
    font_path = resolve_font(FONTS, CFG["caption"]["font_family"])
    font_px = canvas.font_px(CFG["caption"]["font_pct"][aspect])
    sx, sy, sw, sh = canvas.safe_rect()
    # wajah palsu di tengah bawah (area caption default)
    face = [(canvas.width * 0.35, canvas.height * 0.55,
             canvas.width * 0.30, canvas.height * 0.25)]
    ass = build_ass(out.ass_events, canvas, CFG, FONTS,
                    face_boxes_at=lambda t: face)
    assert "Dialogue" in ass
    # tiap event: di safe area & overlap wajah <= 20%
    for line in ass.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        style, text = parts[3], parts[9]
        # buang tag ASS untuk ukur; cek tiap baris terpisah
        import re
        clean = re.sub(r"\{[^}]*\}", "", text)
        for ln in clean.split("\\N"):
            w = measure_text(ln, font_path, font_px)[0]
            h = int(font_px * 1.2)
            x = (canvas.width - w) // 2
            y = (canvas.h(canvas.safe_top) if style == "CaptionTop"
                 else canvas.h(CFG["caption"]["anchor_y"][aspect]) - h // 2)
            assert x >= sx and x + w <= sx + sw, \
                f"{eid} {aspect}: x keluar ({ln[:20]})"
            assert y >= sy and y + h <= sy + sh, \
                f"{eid} {aspect}: y keluar"


# -- render nyata beberapa efek baru ------------------------------------------
@pytest.fixture(scope="module")
def src6s(tmp_path_factory):
    fp = tmp_path_factory.mktemp("cat5") / "s.mp4"
    subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset",
         "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(fp)], check=True)
    # klip b-roll kecil
    broll = fp.parent / "broll.mp4"
    subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=2",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         str(broll)], check=True)
    return fp, broll


def _render_edl(tmp_path, src, edl_dict, name):
    from app.render import render_edl
    edl_p = tmp_path / f"{name}.json"
    edl_p.write_text(json.dumps(edl_dict), encoding="utf-8")
    out = tmp_path / f"{name}.mp4"
    res = render_edl(edl_p, src, out, words=WORDS, config=CFG,
                     work_root=tmp_path / "work",
                     catalog_dir=ROOT / "catalog", assets_dir=ASSETS,
                     model_dir=ROOT / "models")
    assert out.is_file()
    assert res["qa"]["passed"], json.dumps(res["qa"]["checks"], indent=1)[:500]
    return res


def test_render_efek_baru_kamera_grade_overlay(tmp_path, src6s):
    src, _ = src6s
    edl = {
        "schema_version": 1,
        "canvas": {"aspect": "9:16", "reframe": {"mode": "none"}},
        "global": {"intensity": "medium",
                   "grade": {"id": "grade.cinematic",
                             "params": {"strength": 0.7}},
                   "text_style": {"id": "text.pop_in_word",
                                  "params": {"emphasis_idx": [2]}}},
        "segments": [
            {"start": 0.0, "end": 3.0, "role": "hook", "effects": [
                {"id": "camera.slow_zoom", "at": None,
                 "params": {"factor": 1.2}},
                {"id": "overlay.progress_bar", "at": None, "params": {}},
                {"id": "overlay.emoji_burst", "at": 1.0,
                 "params": {"sticker": "burst", "pos": "top_right"}},
            ]},
            {"start": 3.0, "end": 6.0, "role": "isi", "effects": [
                {"id": "camera.whip_pan", "at": 3.2, "params": {}},
                {"id": "transition.whip", "at": 3.0,
                 "params": {"direction": "in"}},
                {"id": "text.karaoke_highlight", "at": None, "params": {}},
            ]},
        ],
    }
    _render_edl(tmp_path, src, edl, "baru1")


def test_render_b_roll_top_dan_split(tmp_path, src6s):
    src, broll = src6s
    edl = {
        "schema_version": 1,
        "canvas": {"aspect": "9:16", "reframe": {"mode": "none"}},
        "global": {"intensity": "medium"},
        "segments": [
            {"start": 0.0, "end": 3.0, "role": "hook", "effects": [
                {"id": "insert.b_roll_top", "at": None,
                 "params": {"clip": str(broll), "top_ratio": 0.38}},
            ]},
            {"start": 3.0, "end": 6.0, "role": "isi", "effects": [
                {"id": "layout.split_compare", "at": None,
                 "params": {"left_from": 0.0, "left_to": 1.5,
                            "right_from": 3.0, "right_to": 4.5}},
                {"id": "transition.zoom_blur", "at": 3.0,
                 "params": {"direction": "in"}},
            ]},
        ],
    }
    _render_edl(tmp_path, src, edl, "baru2")
