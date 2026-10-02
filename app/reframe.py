"""reframe.py — pelacakan wajah & kurva smart_crop.

- ensure_face_track(): sampel frame tiap face_sample_interval detik,
  deteksi wajah (YuNet, cadangan Haar) -> work/<video>/face_track.json.
  face_track.json adalah SUMBER KEBENARAN posisi wajah.
- smart_crop_curve(): dari face track -> kurva pusat crop (t, cx, cy)
  dengan deadzone, peredam eksponensial, batas kecepatan, dan lompatan
  yang hanya diizinkan di titik cut.
- curve_to_crop_expr(): kurva -> ekspresi ffmpeg untuk filter crop
  (disederhanakan dulu dengan Ramer-Douglas-Peucker).

Keputusan arsitektur (terdokumentasi sesuai plan): kurva diungkapkan
sebagai ekspresi `t` bersarang di filter `crop` (bukan sendcmd, bukan
pipe OpenCV). Alasan: tetap satu arsitektur filter untuk semua efek,
tidak ada batas panjang (via -filter_complex_script), dan uji getar
(QA) memvalidasi kehalusannya. Cadangan bila gagal: pipe OpenCV.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .probe import SourceInfo
from .utils import find_ffmpeg, log, run_ffmpeg


# ---------------------------------------------------------------------------
# Pelacakan wajah
# ---------------------------------------------------------------------------
def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    size = path.stat().st_size
    h.update(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(1_000_000))
        if size > 2_000_000:
            f.seek(size // 2)
            h.update(f.read(1_000_000))
    return h.hexdigest()


def _load_detector(model_path: Optional[Path]):
    import cv2
    if model_path and Path(model_path).is_file():
        try:
            det = cv2.FaceDetectorYN.create(
                str(model_path), "", (320, 320),
                score_threshold=0.6, nms_threshold=0.3)
            log.info("detektor wajah: YuNet")
            return ("yunet", det)
        except Exception as e:
            log.warning("YuNet gagal (%s), pakai Haar", e)
    haar = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    log.info("detektor wajah: Haar cascade (cadangan)")
    return ("haar", haar)


def _detect_in_frame(kind, det, img):
    import cv2
    h, w = img.shape[:2]
    boxes = []
    if kind == "yunet":
        det.setInputSize((w, h))
        _, faces = det.detect(img)
        if faces is not None:
            for f in faces:
                x, y, fw, fh = (float(v) for v in f[:4])
                boxes.append({"x": x / w, "y": y / h,
                              "w": fw / w, "h": fh / h})
    else:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        for (x, y, fw, fh) in det.detectMultiScale(gray, 1.2, 4):
            boxes.append({"x": x / w, "y": y / h,
                          "w": fw / w, "h": fh / h})
    return boxes


def _hist_corr(a, b) -> float:
    import cv2
    import numpy as np
    ha = cv2.calcHist([a], [0], None, [32], [0, 256])
    hb = cv2.calcHist([b], [0], None, [32], [0, 256])
    cv2.normalize(ha, ha)
    cv2.normalize(hb, hb)
    return float(cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL))


def ensure_face_track(source: Path, vdir: Path, cfg: dict,
                      model_path: Optional[Path],
                      info: Optional[SourceInfo] = None) -> dict:
    """Bangun (atau pakai cache) face_track.json. Kembalikan datanya."""
    import cv2
    out = vdir / "face_track.json"
    shash = _hash_file(source)
    if out.is_file():
        try:
            old = json.loads(out.read_text(encoding="utf-8"))
            if old.get("source_hash") == shash:
                log.info("face_track cache dipakai: %s", vdir.name)
                return old
        except (json.JSONDecodeError, OSError):
            pass

    interval = float(cfg.get("face_sample_interval", 0.25))
    vdir.mkdir(parents=True, exist_ok=True)
    tmpd = Path(tempfile.mkdtemp(prefix="faces_"))
    try:
        # Frame sudah terotasi benar (autorotate default ffmpeg).
        run_ffmpeg(["-i", str(source), "-vf",
                    f"fps={1 / interval:.3f},scale=320:-1",
                    str(tmpd / "f_%05d.jpg")])
        frames = sorted(tmpd.glob("f_*.jpg"))
        kind, det = _load_detector(model_path)
        samples, cuts = [], []
        prev_gray = None
        for n, fp in enumerate(frames):
            img = cv2.imread(str(fp))
            if img is None:
                continue
            t = round(n * interval, 3)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            if prev_gray is not None and _hist_corr(prev_gray, gray) < 0.45:
                cuts.append(t)
            prev_gray = gray
            samples.append({"t": t,
                            "faces": _detect_in_frame(kind, det, img)})
        data = {"source_hash": shash, "interval": interval,
                "samples": samples, "cuts": cuts,
                "n_faces_total": sum(len(s["faces"]) for s in samples)}
        out.write_text(json.dumps(data), encoding="utf-8")
        log.info("face_track: %d sampel, %d wajah, %d cut",
                 len(samples), data["n_faces_total"], len(cuts))
        return data
    finally:
        for fp in tmpd.glob("*"):
            fp.unlink(missing_ok=True)
        tmpd.rmdir()


# ---------------------------------------------------------------------------
# Kurva smart_crop
# ---------------------------------------------------------------------------
def _even(x: float) -> int:
    return int(round(x / 2) * 2)


def _iou(a: dict, b: dict) -> float:
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    ix = max(0, min(ax2, bx2) - max(a["x"], b["x"]))
    iy = max(0, min(ay2, by2) - max(a["y"], b["y"]))
    inter = ix * iy
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def rdp(points: list[tuple[float, float]], eps: float
        ) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker untuk (t, c)."""
    if len(points) < 3:
        return points
    (t0, c0), (t1, c1) = points[0], points[-1]
    dx, dc = t1 - t0, c1 - c0
    norm = math.hypot(dx, dc) or 1.0
    dmax, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        t, c = points[i]
        d = abs(dc * t - dx * c + t1 * c0 - t0 * c1) / norm
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        left = rdp(points[:idx + 1], eps)
        right = rdp(points[idx:], eps)
        return left[:-1] + right
    return [points[0], points[-1]]


def smart_crop_curve(track: dict, src_w: int, src_h: int,
                     canvas_w: int, canvas_h: int, cfg: dict,
                     duration: float) -> Optional[dict]:
    """Hitung kurva pusat crop. Kembalikan None bila harus fallback blur_fill.

    Aturan: satu subjek utama (terbesar & paling sering muncul, dengan
    hysteresis); gabungan dipakai bila muat <= 85% lebar crop.
    """
    target_ar = canvas_w / canvas_h
    src_ar = src_w / src_h
    if src_ar > target_ar:
        crop_w, crop_h, axis = src_h * target_ar, float(src_h), "x"
    else:
        crop_w, crop_h, axis = float(src_w), src_w / target_ar, "y"
    crop_w, crop_h = _even(crop_w), _even(crop_h)

    deadzone = float(cfg.get("deadzone", 0.06)) * crop_w
    max_speed = float(cfg.get("max_speed", 0.20)) * crop_w  # px/detik
    tau = float(cfg.get("smooth_tau", 0.6))
    dt = 0.1

    # -- lacak wajah antar sampel (IoU) untuk "paling sering muncul" --
    samples = track.get("samples", [])
    samp_by_t = {s["t"]: s["faces"] for s in samples}
    interval = float(track.get("interval", 0.25) or 0.25)
    tracks: list[dict] = []  # {box, count, area_sum, last_t}
    main_id: Optional[int] = None

    def nearest_faces(t: float) -> list[dict]:
        best, best_d = [], 1e9
        for st, faces in samp_by_t.items():
            d = abs(st - t)
            if d < best_d:
                best, best_d = faces, d
        return best if best_d <= interval * 1.5 else []

    def update_tracks(faces: list[dict], t: float) -> None:
        nonlocal main_id
        used = set()
        for f in sorted(faces, key=lambda b: b["w"] * b["h"], reverse=True):
            bi, bj = -1, 0.0
            for i, tr in enumerate(tracks):
                if i in used:
                    continue
                j = _iou(f, tr["box"])
                if j > bj:
                    bi, bj = i, j
            if bi >= 0 and bj > 0.3:
                tr = tracks[bi]
                tr["box"], tr["last_t"] = f, t
                tr["count"] += 1
                tr["area_sum"] += f["w"] * f["h"]
                used.add(bi)
            else:
                tracks.append({"box": f, "last_t": t, "count": 1,
                               "area_sum": f["w"] * f["h"]})
        # subjek utama: skor count * area rata-rata, dengan hysteresis
        scored = sorted(
            range(len(tracks)),
            key=lambda i: tracks[i]["count"] *
            (tracks[i]["area_sum"] / max(tracks[i]["count"], 1)),
            reverse=True)
        if scored:
            top = scored[0]
            if main_id is not None and main_id < len(tracks):
                # hysteresis: pertahankan bila masih terlihat & cukup besar
                cur = tracks[main_id]
                if (t - cur["last_t"] < 1.0 and
                        cur["area_sum"] / max(cur["count"], 1) >
                        0.5 * tracks[top]["area_sum"] /
                        max(tracks[top]["count"], 1)):
                    return
            main_id = top

    cuts = sorted(track.get("cuts", []))
    points: list[tuple[float, float, float]] = []  # (t, cx, cy)
    cx = src_w / 2.0
    cy = src_h / 2.0
    hold_until = -1.0
    last_seen_t = -1.0

    # inisialisasi: cari subjek utama dari 2 detik pertama
    t_init = 0.0
    while t_init < min(2.0, duration):
        update_tracks(nearest_faces(t_init), t_init)
        t_init += dt

    n_steps = int(duration / dt) + 1
    for n in range(n_steps):
        t = round(n * dt, 3)
        if t > duration:
            break
        faces = nearest_faces(t)
        update_tracks(faces, t)
        at_cut = any(abs(t - c) < dt / 2 + 1e-9 for c in cuts)

        # target dari wajah
        tx: Optional[float] = None
        if faces and main_id is not None and main_id < len(tracks):
            main = tracks[main_id]["box"]
            # hanya wajah utama yang masih terlihat baru-baru ini
            if t - tracks[main_id]["last_t"] < 0.75:
                if len(faces) > 1:
                    xs = [f["x"] for f in faces]
                    ws = [f["w"] for f in faces]
                    combined_w = (max(x + w for x, w in zip(xs, ws)) -
                                  min(xs)) * src_w
                    if combined_w <= 0.85 * crop_w:
                        cx_all = (min(xs) + max(x + w for x, w in
                                                zip(xs, ws))) / 2 * src_w
                        cy_all = sum(f["y"] + f["h"] / 2
                                     for f in faces) / len(faces) * src_h
                        tx, ty = cx_all, cy_all
                    else:
                        return None  # terlalu lebar -> fallback blur_fill
                if tx is None:
                    tx = (main["x"] + main["w"] / 2) * src_w
                    ty = (main["y"] + main["h"] / 2) * src_h
                last_seen_t = t
                hold_until = -1.0

        if tx is None:
            # wajah hilang: tahan 2 dtk, lalu melayang ke tengah
            if t - last_seen_t < 2.0 or last_seen_t < 0:
                tx, ty = cx, cy
            else:
                tx, ty = src_w / 2.0, src_h / 2.0

        # deadzone + peredam + batas kecepatan (kecuali di cut)
        cur = cx if axis == "x" else cy
        tgt = tx if axis == "x" else ty
        if at_cut:
            cur = tgt
        else:
            if abs(tgt - cur) > deadzone:
                alpha = 1 - math.exp(-dt / max(tau, 1e-6))
                step = (tgt - cur) * alpha
                vmax = max_speed * dt
                step = max(-vmax, min(vmax, step))
                cur += step
        if axis == "x":
            cx = min(max(cur, crop_w / 2), src_w - crop_w / 2)
        else:
            cy = min(max(cur, crop_h / 2), src_h - crop_h / 2)
        points.append((t, cx, cy))

    return {"points": points, "crop_w": crop_w, "crop_h": crop_h,
            "axis": axis, "src_w": src_w, "src_h": src_h,
            "canvas_w": canvas_w, "canvas_h": canvas_h}


def curve_to_crop_expr(curve: dict, seg_start: float, seg_end: float
                       ) -> tuple[str, str]:
    """Kurva global -> ekspresi crop x/y dalam WAKTU LOKAL segmen."""
    axis = curve["axis"]
    pts = []
    for p in curve["points"]:
        t = p[0]
        if seg_start - 1e-9 <= t <= seg_end + 1e-9:
            c = p[1] if axis == "x" else p[2]
            pts.append((t - seg_start, c))
    if not pts:
        c = curve["points"][0]
        v = c[1] if curve["axis"] == "x" else c[2]
        pts = [(0.0, v), (seg_end - seg_start, v)]
    # sederhanakan (RDP): eps 0,5% lebar crop
    eps = 0.005 * curve["crop_w"]
    simp = rdp(pts, eps)
    if len(simp) == 1:
        simp = [simp[0], (seg_end - seg_start, simp[0][1])]

    # interpolasi linear bersarang: if(lt(t,t1), x0+(x1-x0)*(t-t0)/(t1-t0), ...)
    expr = f"{simp[-1][1]:.2f}"
    for (t0, x0), (t1, x1) in zip(reversed(simp[:-1]), reversed(simp[1:])):
        if t1 - t0 < 1e-6:
            continue
        expr = (f"if(lt(t,{t1:.3f}),{x0:.2f}+({x1:.2f}-{x0:.2f})"
                f"*(t-{t0:.3f})/{t1 - t0:.3f},{expr})")
    expr = f"if(lt(t,{simp[0][0]:.3f}),{simp[0][1]:.2f},{expr})"
    # x = kiri atas crop; y analog (sumbu diam = konstanta tengah)
    if curve["axis"] == "x":
        x_expr = f"({expr})-{curve['crop_w'] / 2:.2f}"
        y_c = (curve["src_h"] - curve["crop_h"]) / 2
        y_expr = f"{y_c:.2f}"
    else:
        y_expr = f"({expr})-{curve['crop_h'] / 2:.2f}"
        x_c = (curve["src_w"] - curve["crop_w"]) / 2
        x_expr = f"{x_c:.2f}"
    return x_expr, y_expr
