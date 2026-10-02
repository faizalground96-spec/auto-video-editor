"""Uji reframe: kurva smart_crop, RDP, ekspresi crop, cadangan."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.reframe import (curve_to_crop_expr, rdp,  # noqa: E402
                         smart_crop_curve)
from app.utils import find_ffmpeg, resource_path  # noqa: E402

ROOT = resource_path(".")
CFG = {"deadzone": 0.06, "max_speed": 0.20, "smooth_tau": 0.6}


def _track(face_fn=None, n=21, cuts=(), interval=0.25):
    samples = []
    for i in range(n):
        t = round(i * interval, 3)
        faces = face_fn(t) if face_fn else []
        samples.append({"t": t, "faces": faces})
    return {"samples": samples, "interval": interval, "cuts": list(cuts),
            "n_faces_total": sum(len(s["faces"]) for s in samples)}


def _one_face(cx):
    return [{"x": cx - 0.06, "y": 0.4, "w": 0.12, "h": 0.2}]


def test_rdp_menyederhanakan_garis_lurus():
    pts = [(float(i), 2.0 * i) for i in range(50)]
    assert rdp(pts, 0.01) == [pts[0], pts[-1]]


def test_rdp_mempertahankan_belokan():
    pts = [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]
    assert len(rdp(pts, 0.01)) == 3


def test_kurva_diam_saat_wajah_dalam_deadzone():
    track = _track(lambda t: _one_face(0.5))  # wajah diam di tengah
    c = smart_crop_curve(track, 1280, 720, 1080, 1920, CFG, 5.0)
    xs = [p[1] for p in c["points"]]
    assert max(xs) - min(xs) < 1.0  # praktis tidak bergerak


def test_kurva_mengejar_dengan_batas_kecepatan():
    # wajah bergerak cepat 0.2 -> 0.8 dalam 5 dtk (153 px/dtk di 1280)
    track = _track(lambda t: _one_face(0.2 + 0.12 * t))
    c = smart_crop_curve(track, 1280, 720, 1080, 1920, CFG, 5.0)
    pts = c["points"]
    assert pts[-1][1] > pts[0][1]  # bergerak mengikuti
    vmax = max(abs(b[1] - a[1]) / 0.1 for a, b in zip(pts[:-1], pts[1:]))
    assert vmax <= 0.20 * c["crop_w"] * 1.01  # batas 20%/dtk


def test_kurva_wajah_hilang_tahan_lalu_kembali():
    def faces(t):
        return _one_face(0.3) if t < 1.0 else []
    track = _track(faces, n=41)  # 10 dtk
    c = smart_crop_curve(track, 1280, 720, 1080, 1920, CFG, 10.0)
    pts = c["points"]
    x_at_2 = next(p[1] for p in pts if p[0] >= 2.0)
    x_at_1 = next(p[1] for p in pts if p[0] >= 1.0)
    assert abs(x_at_2 - x_at_1) < 2.0  # tahan ~2 dtk
    x_at_9 = next(p[1] for p in pts if p[0] >= 9.0)
    assert abs(x_at_9 - 640) < abs(x_at_1 - 640)  # melayang ke tengah


def test_kurva_lompat_hanya_di_cut():
    def faces(t):
        return _one_face(0.2 if t < 2.5 else 0.8)
    track = _track(faces, n=21, cuts=[2.5])
    c = smart_crop_curve(track, 1280, 720, 1080, 1920, CFG, 5.0)
    pts = c["points"]
    # ada lompatan besar tepat di sekitar cut
    jumps = [(p[0], abs(b[1] - a[1])) for a, b, p
             in zip(pts[:-1], pts[1:], pts[1:])]
    big = [t for t, j in jumps if j > 0.05 * c["crop_w"]]
    assert big and min(abs(t - 2.5) for t in big) < 0.2


def test_kurva_dua_wajah_lebar_minta_fallback():
    def faces(t):
        return [{"x": 0.05, "y": 0.4, "w": 0.12, "h": 0.2},
                {"x": 0.83, "y": 0.4, "w": 0.12, "h": 0.2}]
    track = _track(faces)
    assert smart_crop_curve(track, 1280, 720, 1080, 1920, CFG, 5.0) is None


def test_kurva_dua_wajah_dekat_pakai_gabungan():
    def faces(t):
        return [{"x": 0.40, "y": 0.4, "w": 0.10, "h": 0.2},
                {"x": 0.52, "y": 0.4, "w": 0.10, "h": 0.2}]
    track = _track(faces)
    c = smart_crop_curve(track, 1280, 720, 1080, 1920, CFG, 5.0)
    assert c is not None
    # pusat gabungan ~0.51*1280 = 653
    assert abs(c["points"][-1][1] - 653) < 60


def test_ekspresi_crop_valid_di_ffmpeg(tmp_path):
    track = _track(lambda t: _one_face(0.2 + 0.1 * t))
    c = smart_crop_curve(track, 1280, 720, 1080, 1920, CFG, 5.0)
    x_expr, y_expr = curve_to_crop_expr(c, 0.0, 5.0)
    src = tmp_path / "in.mp4"
    subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=2",
         "-vf", f"crop=w={int(c['crop_w'])}:h={int(c['crop_h'])}:"
                 f"x='{x_expr}':y='{y_expr}'",
         "-c:v", "libx264", "-preset", "veryfast", str(tmp_path / "o.mp4")],
        check=True)
    from app.probe import probe
    i = probe(tmp_path / "o.mp4")
    assert (i.width, i.height) == (int(c["crop_w"]), int(c["crop_h"]))
