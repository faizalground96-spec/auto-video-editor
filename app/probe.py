"""probe.py — ffprobe -> objek SourceInfo.

Menangani kasus khas video ponsel: metadata rotasi, frame rate variabel (VFR),
SAR non-persegi, dan HDR. Video tanpa audio tetap lolos (pipeline jalan tanpa
transkrip/caption).
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from .utils import find_ffmpeg, log


@dataclass
class SourceInfo:
    path: Path
    duration: float            # detik
    width: int                 # piksel TERENCANA (setelah rotasi)
    height: int
    coded_width: int           # piksel mentah sebelum rotasi
    coded_height: int
    fps: float                 # fps rata-rata
    is_vfr: bool
    video_codec: str
    rotation: int              # 0/90/180/270 (sudah dinormalisasi)
    sar: str                   # sample aspect ratio, mis. "1:1"
    needs_sar_fix: bool        # True bila SAR != 1:1
    is_hdr: bool               # True bila terdeteksi HDR/HLG/10-bit
    hdr_info: str              # ringkasan untuk log
    has_audio: bool
    audio_codec: str = ""
    audio_duration: float = 0.0
    orientation: str = "horizontal"  # vertical | horizontal | square

    def aspect_ratio(self) -> float:
        return self.width / self.height if self.height else 0.0


def _parse_fps(value: str) -> float:
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return 0.0


def _rotation_of(stream: dict) -> int:
    """Baca rotasi dari tag maupun side data, normalisasi ke 0/90/180/270."""
    rot = 0
    tags = stream.get("tags", {}) or {}
    for key in ("rotate", "rotation"):
        if key in tags:
            try:
                rot = int(float(tags[key]))
                break
            except (ValueError, TypeError):
                pass
    if not rot:
        for sd in stream.get("side_data_list", []) or []:
            if "rotation" in sd:
                try:
                    rot = int(float(sd["rotation"]))
                    break
                except (ValueError, TypeError):
                    pass
    rot %= 360
    # bulatkan ke kelipatan 90 terdekat
    return int(round(rot / 90) % 4) * 90


def _detect_vfr(ffprobe: Path, path: Path, sample: int = 120) -> bool:
    """Deteksi VFR dari durasi paket yang sebenarnya (ground truth).

    Membaca s/d `sample` paket video pertama; VFR bila durasinya tidak
    seragam. Jauh lebih andal daripada heuristik avg_frame_rate vs
    r_frame_rate (yang sering sama persis pada file VFR).
    """
    cmd = [str(ffprobe), "-v", "error", "-select_streams", "v:0",
           "-show_entries", "packet=duration_time",
           "-of", "csv=p=0", "-read_intervals", f"%+#{sample}", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             check=True, timeout=30,
                             encoding="utf-8", errors="replace")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    durs = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            durs.append(float(line))
        except ValueError:
            pass
    if len(durs) < 3:
        return False
    first = durs[0]
    # toleransi 2%: variasi kecil akibat pembulatan bukan VFR
    return any(abs(d - first) / max(first, 1e-9) > 0.02 for d in durs[1:])
    """Baca rotasi dari tag maupun side data, normalisasi ke 0/90/180/270."""
    rot = 0
    tags = stream.get("tags", {}) or {}
    for key in ("rotate", "rotation"):
        if key in tags:
            try:
                rot = int(float(tags[key]))
                break
            except (ValueError, TypeError):
                pass
    if not rot:
        for sd in stream.get("side_data_list", []) or []:
            if "rotation" in sd:
                try:
                    rot = int(float(sd["rotation"]))
                    break
                except (ValueError, TypeError):
                    pass
    rot %= 360
    # bulatkan ke kelipatan 90 terdekat
    return int(round(rot / 90) % 4) * 90


def probe(path: str | Path) -> SourceInfo:
    """Jalankan ffprobe dan kembalikan SourceInfo."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"file tidak ada: {path}")
    ffprobe_cand = find_ffmpeg().parent / (
        "ffprobe.exe" if os.name == "nt" else "ffprobe")
    if not ffprobe_cand.is_file():
        import shutil
        which = shutil.which("ffprobe")
        if not which:
            raise FileNotFoundError("ffprobe tidak ditemukan")
        ffprobe_cand = Path(which)

    cmd = [str(ffprobe_cand), "-v", "error", "-show_format", "-show_streams",
           "-print_format", "json", str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True,
                         encoding="utf-8", errors="replace")
    data = json.loads(out.stdout)

    fmt = data.get("format", {})
    duration = float(fmt.get("duration", 0) or 0)

    vstreams = [s for s in data.get("streams", [])
                if s.get("codec_type") == "video"]
    if not vstreams:
        raise ValueError(f"tidak ada stream video di {path}")
    vs = vstreams[0]

    astreams = [s for s in data.get("streams", [])
                if s.get("codec_type") == "audio"]

    coded_w = int(vs.get("width", 0))
    coded_h = int(vs.get("height", 0))
    rotation = _rotation_of(vs)
    if rotation in (90, 270):
        width, height = coded_h, coded_w
    else:
        width, height = coded_w, coded_h

    avg_fps = _parse_fps(vs.get("avg_frame_rate", "0/0"))
    r_fps = _parse_fps(vs.get("r_frame_rate", "0/0"))
    # Heuristik cepat: avg != r_frame. Dilengkapi uji paket (ground truth)
    # karena keduanya sering sama persis pada file VFR.
    heuristic_vfr = (avg_fps > 0 and r_fps > 0
                     and abs(avg_fps - r_fps) / max(r_fps, 1e-9) > 0.01)
    is_vfr = heuristic_vfr or _detect_vfr(ffprobe_cand, path)

    sar = vs.get("sample_aspect_ratio", "1:1") or "1:1"
    try:
        sar_f = float(Fraction(sar))
    except (ValueError, ZeroDivisionError):
        sar_f = 1.0
    needs_sar_fix = abs(sar_f - 1.0) > 0.01

    pix_fmt = vs.get("pix_fmt", "")
    color_transfer = (vs.get("color_transfer") or "").lower()
    color_primaries = (vs.get("color_primaries") or "").lower()
    is_hdr = (
        color_transfer in ("smpte2084", "arib-std-b67")
        or color_primaries == "bt2020"
        or "10le" in pix_fmt or "10be" in pix_fmt or "p010" in pix_fmt
    )
    hdr_info = (f"transfer={color_transfer or '?'} "
                f"primaries={color_primaries or '?'} pix_fmt={pix_fmt}")
    if is_hdr:
        log.warning("Sumber %s terdeteksi HDR/HLG/10-bit (%s). "
                    "Akan dikonversi ke bt709 SDR sebisanya; "
                    "hasil bisa tampak pucat.", path.name, hdr_info)

    if width >= height * 1.05:
        orientation = "horizontal"
    elif height >= width * 1.05:
        orientation = "vertical"
    else:
        orientation = "square"

    has_audio = len(astreams) > 0
    audio_codec = astreams[0].get("codec_name", "") if has_audio else ""
    audio_duration = float(astreams[0].get("duration", 0) or 0) if has_audio else 0.0
    if not has_audio:
        log.info("Sumber %s tanpa audio: lewati transkrip & caption.",
                 path.name)

    info = SourceInfo(
        path=path, duration=duration, width=width, height=height,
        coded_width=coded_w, coded_height=coded_h, fps=avg_fps,
        is_vfr=is_vfr, video_codec=vs.get("codec_name", ""),
        rotation=rotation, sar=sar, needs_sar_fix=needs_sar_fix,
        is_hdr=is_hdr, hdr_info=hdr_info, has_audio=has_audio,
        audio_codec=audio_codec, audio_duration=audio_duration,
        orientation=orientation,
    )
    log.info("probe %s: %dx%d (%s), %.2fs, %.2ffps%s%s%s",
             path.name, width, height, orientation, duration, avg_fps,
             " VFR" if is_vfr else "",
             f" rot={rotation}" if rotation else "",
             " no-audio" if not has_audio else "")
    return info
