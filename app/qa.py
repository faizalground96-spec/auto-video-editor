"""qa.py — pemeriksaan otomatis hasil render.

Dijalankan setelah setiap render. Hasil: work/<video>/qa_report.json +
contact_sheet.jpg. Ambang di config.yaml (`qa:`) agar bisa disetel.
Semua cek kuantitatif, bukan "kelihatannya bagus".
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .canvas import Canvas
from .probe import SourceInfo, probe
from .utils import find_ffmpeg, log


@dataclass
class QACtx:
    output: Path
    source: Path
    source_info: SourceInfo
    canvas: Canvas
    config: dict
    edl: Any
    registry: Any
    face_track: Optional[dict] = None
    smart_crop_curve: Optional[dict] = None
    ass_path: Optional[Path] = None
    sfx_cues: list = field(default_factory=list)


def _check(name: str, status: str, detail: str = "", **metrics) -> dict:
    return {"status": status, "detail": detail, "metrics": metrics}


# ---------------------------------------------------------------------------
# 1. Format
# ---------------------------------------------------------------------------
def check_format(q: QACtx) -> dict:
    o = probe(q.output)
    qa = q.config.get("qa", {})
    errs = []
    if (o.width, o.height) != (q.canvas.width, q.canvas.height):
        errs.append(f"resolusi {o.width}x{o.height} != "
                    f"{q.canvas.width}x{q.canvas.height}")
    if abs(o.fps - 30) > 0.5:
        errs.append(f"fps {o.fps:.2f} != 30")
    if o.is_vfr:
        errs.append("output VFR (harus CFR)")
    if abs(o.duration - q.source_info.duration) > 1 / 30 + 1e-6:
        errs.append(f"durasi {o.duration:.3f} != sumber "
                    f"{q.source_info.duration:.3f}")
    if errs:
        return _check("format", "fail", "; ".join(errs))
    return _check("format", "pass",
                  f"{o.width}x{o.height} 30fps {o.duration:.2f}s")


# ---------------------------------------------------------------------------
# 2. Audio
# ---------------------------------------------------------------------------
def _extract_mono_f32(path: Path, out: Path) -> None:
    subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(path), "-ac", "1", "-ar", "8000", "-f", "f32le",
         str(out)], check=True)


def _audio_corr(a: Path, b: Path, tmp: Path) -> float:
    """Korelasi ternormalisasi maks dalam jendela ±100ms."""
    import numpy as np
    fa, fb = tmp / "qa_a.raw", tmp / "qa_b.raw"
    _extract_mono_f32(a, fa)
    _extract_mono_f32(b, fb)
    x = np.fromfile(fa, dtype=np.float32)
    y = np.fromfile(fb, dtype=np.float32)
    n = min(len(x), len(y))
    if n < 800:
        return 0.0
    x, y = x[:n], y[:n]
    x = (x - x.mean()) / (x.std() + 1e-9)
    y = (y - y.mean()) / (y.std() + 1e-9)
    best = 0.0
    for shift in range(-800, 801, 80):  # ±100ms, langkah 10ms
        if shift < 0:
            c = float(np.dot(x[-shift:], y[:n + shift]) / n)
        else:
            c = float(np.dot(x[:n - shift], y[shift:]) / n)
        best = max(best, c)
    return best


def check_audio(q: QACtx, tmp: Path) -> dict:
    o = probe(q.output)
    if not q.source_info.has_audio:
        if o.has_audio:
            return _check("audio", "fail", "sumber tanpa audio tapi hasil ada")
        return _check("audio", "skip", "tanpa audio")
    if not o.has_audio:
        return _check("audio", "fail", "hasil tanpa audio")
    ddur = abs(o.duration - q.source_info.duration)
    if ddur > 0.020:
        return _check("audio", "fail", f"selisih durasi audio {ddur*1000:.0f}ms")
    if q.sfx_cues:
        return _check("audio_sfx", "skip",
                      "cek SFX aktif (Tahap 7)")  # diimplementasi Tahap 7
    corr = _audio_corr(q.source, q.output, tmp)
    need = float(q.config.get("qa", {}).get("max_audio_corr_min", 0.99))
    if corr < need:
        return _check("audio", "fail",
                      f"korelasi audio {corr:.4f} < {need}", corr=corr)
    return _check("audio", "pass", f"korelasi {corr:.4f}", corr=corr)


# ---------------------------------------------------------------------------
# 3. Wajah (smart_crop)
# ---------------------------------------------------------------------------
def _curve_center_at(curve: dict, t: float) -> tuple[float, float]:
    pts = curve["points"]
    if t <= pts[0][0]:
        return pts[0][1], pts[0][2]
    for (t0, x0, y0), (t1, x1, y1) in zip(pts[:-1], pts[1:]):
        if t0 <= t <= t1:
            a = (t - t0) / max(t1 - t0, 1e-9)
            return x0 + (x1 - x0) * a, y0 + (y1 - y0) * a
    return pts[-1][1], pts[-1][2]


def check_face(q: QACtx) -> dict:
    curve = q.smart_crop_curve
    track = q.face_track
    if not curve or not track:
        return _check("face", "skip", "bukan smart_crop / tanpa face track")
    qa = q.config.get("qa", {})
    need_ratio = float(qa.get("face_inside_ratio", 0.95))
    margin = 0.03
    cw, ch = curve["crop_w"], curve["crop_h"]
    sw, sh = curve["src_w"], curve["src_h"]
    W, H = q.canvas.width, q.canvas.height
    samples = track.get("samples", [])
    interval = float(track.get("interval", 0.25) or 0.25)
    total, okc = 0, 0
    for s in samples[:: max(1, int(1.0 / interval))]:  # ~1/detik
        if not s["faces"]:
            continue
        t = s["t"]
        cx, cy = _curve_center_at(curve, t)
        for f in s["faces"]:
            total += 1
            fx, fy = (f["x"] + f["w"] / 2) * sw, (f["y"] + f["h"] / 2) * sh
            fw, fh = f["w"] * sw, f["h"] * sh
            # petakan ke kanvas output
            ox = (fx - (cx - cw / 2)) * (W / cw)
            oy = (fy - (cy - ch / 2)) * (H / ch)
            ow, oh = fw * (W / cw), fh * (H / ch)
            if (ox >= margin * W and oy >= margin * H and
                    ox + ow <= (1 - margin) * W and
                    oy + oh <= (1 - margin) * H):
                okc += 1
    if total == 0:
        return _check("face", "skip", "tak ada wajah di sampel")
    ratio = okc / total
    if ratio < need_ratio:
        return _check("face", "fail",
                      f"{okc}/{total} wajah utuh ({ratio:.2%}) < {need_ratio:.0%}",
                      ratio=ratio)
    return _check("face", "pass", f"{okc}/{total} wajah utuh", ratio=ratio)


# ---------------------------------------------------------------------------
# 4. Getar (dari kurva smart_crop)
# ---------------------------------------------------------------------------
def check_jitter(q: QACtx) -> dict:
    curve = q.smart_crop_curve
    if not curve:
        return _check("jitter", "skip", "bukan smart_crop")
    qa = q.config.get("qa", {})
    max_speed = float(qa.get("max_crop_speed", 0.20))      # fraksi/detik
    max_jump = float(qa.get("max_jump_per_frame", 0.015))  # fraksi/frame
    cw = curve["crop_w"]
    axis = curve["axis"]
    pts = curve["points"]
    # resample ke 30Hz
    ts = [p[0] for p in pts]
    dur = ts[-1] - ts[0] if len(ts) > 1 else 0
    n = max(2, int(dur * 30))
    cs = []
    for i in range(n):
        t = ts[0] + dur * i / max(n - 1, 1)
        c = _curve_center_at(curve, t)
        cs.append(c[0] if axis == "x" else c[1])
    dt = dur / max(n - 1, 1)
    worst_speed, worst_jump, reversals = 0.0, 0.0, 0
    prev_v = 0.0
    for i in range(1, n):
        v = (cs[i] - cs[i - 1]) / max(dt, 1e-9) / cw
        worst_speed = max(worst_speed, abs(v))
        worst_jump = max(worst_jump, abs(cs[i] - cs[i - 1]) / cw)
        if v * prev_v < 0 and abs(v) > 0.005 and abs(prev_v) > 0.005:
            reversals += 1
        prev_v = v
    rev_per_s = reversals / max(dur, 0.01)
    errs = []
    if worst_speed > max_speed * 1.05:
        errs.append(f"kecepatan {worst_speed:.3f} > {max_speed}")
    if worst_jump > max_jump * 1.05:
        errs.append(f"lompatan/frame {worst_jump:.4f} > {max_jump}")
    if rev_per_s > 1.0:
        errs.append(f"balik arah {rev_per_s:.2f}/dtk > 1")
    if errs:
        return _check("jitter", "fail", "; ".join(errs),
                      speed=worst_speed, jump=worst_jump,
                      reversals_per_s=rev_per_s)
    return _check("jitter", "pass",
                  f"speed {worst_speed:.3f}, jump {worst_jump:.4f}, "
                  f"rev {rev_per_s:.2f}/s",
                  speed=worst_speed, jump=worst_jump,
                  reversals_per_s=rev_per_s)


# ---------------------------------------------------------------------------
# 5. Teks (ukur dengan Pillow + font asli)
# ---------------------------------------------------------------------------
def _parse_ass(path: Path) -> list[dict]:
    evs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Dialogue:"):
            parts = line.split(",", 9)
            if len(parts) == 10:
                evs.append({"start": _t(parts[1]), "end": _t(parts[2]),
                            "style": parts[3], "text": parts[9]})
    return evs


def _t(s: str) -> float:
    h, m, rest = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def check_text(q: QACtx) -> dict:
    if not q.ass_path or not q.ass_path.is_file():
        return _check("text", "skip", "tanpa ASS")
    from .subtitles import measure_text, resolve_font
    cap = q.config["caption"]
    font_path = resolve_font(Path(q.config.get("fonts_dir", "assets/fonts")),
                             cap["font_family"])
    font_px = q.canvas.font_px(cap["font_pct"][q.canvas.aspect])
    sx, sy, sw, sh = q.canvas.safe_rect()
    evs = _parse_ass(q.ass_path)
    if not evs:
        return _check("text", "skip", "ASS tanpa dialogue")
    bad = []
    for ev in evs:
        lines = ev["text"].split("\\N")
        # buang tag override ASS {\...} sebelum ukur
        clean = [re.sub(r"\{[^}]*\}", "", t) for t in lines]
        w = max(measure_text(t, font_path, font_px)[0] for t in clean)
        h = int(len(lines) * font_px * 1.2)
        x = (q.canvas.width - w) // 2
        if ev["style"] == "CaptionTop":
            y = q.canvas.h(q.canvas.safe_top)
        else:
            y = q.canvas.h(cap["anchor_y"][q.canvas.aspect]) - h // 2
        if not (x >= sx and y >= sy and x + w <= sx + sw and
                y + h <= sy + sh):
            bad.append(f"keluar safe area: {clean[0][:20]}")
        # tutup wajah > 20%?
        if q.face_track:
            tmid = (ev["start"] + ev["end"]) / 2
            faces = _faces_at(q, tmid)
            for f in faces:
                ix = max(0, min(x + w, f[0] + f[2]) - max(x, f[0]))
                iy = max(0, min(y + h, f[1] + f[3]) - max(y, f[1]))
                if (ix * iy) / max(w * h, 1) > 0.2:
                    bad.append(f"menutup wajah >20%: {clean[0][:20]}")
                    break
        if len(bad) > 5:
            break
    if bad:
        return _check("text", "fail", "; ".join(bad[:5]))
    return _check("text", "pass", f"{len(evs)} baris di safe area")


def _faces_at(q: QACtx, t: float) -> list[tuple]:
    """Kotak wajah dalam piksel kanvas (pendekatan: tanpa reframe)."""
    if not q.face_track:
        return []
    samples = q.face_track.get("samples", [])
    best, bd = None, 1e9
    for s in samples:
        d = abs(s["t"] - t)
        if d < bd:
            best, bd = s, d
    if best is None or bd > 1.0:
        return []
    W, H = q.canvas.width, q.canvas.height
    return [(f["x"] * W, f["y"] * H, f["w"] * W, f["h"] * H)
            for f in best["faces"]]


# ---------------------------------------------------------------------------
# 6. Frame hitam
# ---------------------------------------------------------------------------
def _black_intervals(path: Path) -> list[tuple[float, float]]:
    out = subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-i", str(path),
         "-vf", "blackdetect=d=0.3:pix_th=0.10", "-f", "null", "-"],
        capture_output=True, text=True)
    ivs = []
    for line in (out.stderr or "").splitlines():
        m = re.search(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)", line)
        if m:
            ivs.append((float(m.group(1)), float(m.group(2))))
    return ivs


def check_blackframes(q: QACtx) -> dict:
    out_ivs = _black_intervals(q.output)
    if not out_ivs:
        return _check("blackframes", "pass", "tidak ada frame hitam")
    src_ivs = _black_intervals(q.source)

    def covered(iv):
        s, e = iv
        return any(ss <= s + 0.1 and e <= ee + 0.1 for ss, ee in src_ivs)

    new = [iv for iv in out_ivs if not covered(iv)]
    if new:
        return _check("blackframes", "fail",
                      f"{len(new)} segmen hitam baru: {new[:3]}")
    return _check("blackframes", "pass", "hitam hanya yang ada di sumber")


# ---------------------------------------------------------------------------
# 7. Kepadatan efek
# ---------------------------------------------------------------------------
def check_density(q: QACtx) -> dict:
    edl = q.edl
    intensity = getattr(edl.global_, "intensity", "medium")
    limit = q.config.get("density", {}).get(intensity, {}).get(
        "max_strong_per_10s", 3)
    strong_at = []
    for s in edl.segments:
        for e in s.effects:
            try:
                if q.registry.get(e.id).meta.strong:
                    strong_at.append(e.at if e.at is not None else s.start)
            except KeyError:
                pass
    if not strong_at:
        return _check("density", "pass", "tanpa efek kuat")
    dur = q.source_info.duration
    worst, w0 = 0, 0.0
    t = 0.0
    while t < dur:
        c = sum(1 for a in strong_at if t <= a < t + 10)
        if c > worst:
            worst, w0 = c, t
        t += 2.0
    if worst > limit:
        return _check("density", "fail",
                      f"{worst} efek kuat/10 dtk (batas {limit}) "
                      f"di t={w0:.0f}s", worst=worst, limit=limit)
    return _check("density", "pass",
                  f"maks {worst}/10 dtk (batas {limit})", worst=worst)


# ---------------------------------------------------------------------------
# Contact sheet & runner
# ---------------------------------------------------------------------------
def make_contact_sheet(output: Path, dest: Path) -> Path:
    info = probe(output)
    total = max(1, int(info.duration * info.fps))
    step = max(1, total // 12)
    subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(output), "-vf",
         f"select='not(mod(n\\,{step}))',scale=320:-1,tile=4x3",
         "-frames:v", "1", str(dest)], check=True)
    return dest


def run_qa(q: QACtx, work_dir: Path) -> dict:
    """Jalankan semua cek. Kembalikan report (juga ditulis ke file)."""
    tmp = work_dir / "qa_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    checks = {}
    checks["format"] = check_format(q)
    checks["audio"] = check_audio(q, tmp)
    checks["face"] = check_face(q)
    checks["jitter"] = check_jitter(q)
    checks["text"] = check_text(q)
    checks["blackframes"] = check_blackframes(q)
    checks["density"] = check_density(q)
    failed = [k for k, v in checks.items() if v["status"] == "fail"]
    sheet = work_dir / "contact_sheet.jpg"
    try:
        make_contact_sheet(q.output, sheet)
        sheet_ok = True
    except Exception as e:
        log.warning("contact sheet gagal: %s", e)
        sheet_ok = False
    report = {
        "passed": not failed,
        "failed": failed,
        "checks": checks,
        "contact_sheet": str(sheet) if sheet_ok else None,
        "output": str(q.output),
        "canvas": f"{q.canvas.width}x{q.canvas.height}",
    }
    rp = work_dir / "qa_report.json"
    rp.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                  encoding="utf-8")
    log.info("QA: %s (%s)", "LULUS" if not failed else f"GAGAL: {failed}",
             rp.name)
    return report
