"""sfx.py — Tahap 7: trek SFX otomatis + ducking.

Alur: kumpulkan cue dari EDL (field `sfx` di META tiap efek) ->
bangun satu trek WAV (adelay per cue) -> campur dengan audio asli
memakai sidechaincompress (ucapan = kunci, SFX = sinyal utama)
lalu amix normalize=0 agar level ucapan tidak turun.

Intensitas `calm` -> tanpa SFX (boleh juga dimatikan via opsi).
"""
from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .utils import run_ffmpeg

log = logging.getLogger("auto_video_editor.sfx")

SR = 44100
# SFX yang dikenal (dibuat tools/make_sfx.py)
KNOWN_SFX = ("swoosh", "boom", "pop", "riser")


# ---------------------------------------------------------------------------
# Kumpulkan cue
# ---------------------------------------------------------------------------
def collect_cues(edl: Any, registry, words: list[dict]) -> list[dict]:
    """Kembalikan [{'t': float, 'sfx': str, 'why': str}]."""
    cues: list[dict] = []
    # waktu emphasis per segmen (dari EDL tervalidasi; dukung dict/objek)
    def _ew_start(ew) -> float:
        return float(ew["start"] if isinstance(ew, dict) else ew.start)

    emph_by_seg: dict[int, list[float]] = {}
    for si, seg in enumerate(edl.segments):
        s_start = seg.start if not isinstance(seg, dict) else seg["start"]
        s_end = seg.end if not isinstance(seg, dict) else seg["end"]
        emph_by_seg[si] = [
            _ew_start(ew) for ew in (edl.emphasis_words or [])
            if s_start <= _ew_start(ew) < s_end
        ]

    for si, seg in enumerate(edl.segments):
        for ef in seg.effects:
            entry = registry.entries.get(ef.id)
            if entry is None:
                continue
            sfx = entry.meta.sfx
            if not sfx or sfx not in KNOWN_SFX:
                continue
            cat = entry.meta.category
            if cat == "text" and emph_by_seg[si]:
                for t in emph_by_seg[si]:
                    cues.append({"t": round(t, 3), "sfx": sfx,
                                 "why": f"{ef.id} emphasis"})
            else:
                t = float(ef.at) if ef.at is not None else float(seg.start)
                cues.append({"t": round(t, 3), "sfx": sfx,
                             "why": ef.id})
    # dedupe: cue sejenis dalam 0,15 dtk -> gabung
    cues.sort(key=lambda c: c["t"])
    deduped: list[dict] = []
    for c in cues:
        if deduped and c["sfx"] == deduped[-1]["sfx"] \
                and c["t"] - deduped[-1]["t"] < 0.15:
            continue
        deduped.append(c)
    return deduped


# ---------------------------------------------------------------------------
# Bangun trek SFX
# ---------------------------------------------------------------------------
def build_sfx_track(cues: list[dict], duration: float, sfx_dir: Path,
                    out_path: Path, volume: float = 0.4,
                    cancel_event=None) -> Optional[Path]:
    """Satu WAV sepanjang `duration` berisi semua cue. None bila tanpa cue."""
    if not cues:
        return None
    sfx_dir = Path(sfx_dir)
    out_path = Path(out_path)
    inputs: list[str] = []
    filters: list[str] = []
    for i, c in enumerate(cues):
        wav = sfx_dir / f"{c['sfx']}.wav"
        if not wav.is_file():
            log.warning("SFX tak ada: %s, dilewati", wav.name)
            continue
        inputs += ["-i", str(wav)]
        ms = int(c["t"] * 1000)
        filters.append(f"[{i}:a]aresample={SR},volume={volume},"
                       f"adelay={ms}|{ms}[s{i}]")
    if not filters:
        return None
    n = len(filters)
    mix = "".join(f"[s{i}]" for i in range(n)) \
        + f"amix=inputs={n}:normalize=0:duration=longest[sfx]"
    # pad ke durasi penuh
    filt = ";".join(filters + [mix,
                               f"[sfx]apad=whole_dur={duration:.3f}[padded]"])
    run_ffmpeg(inputs + ["-filter_complex", filt, "-map", "[padded]",
                         "-c:a", "pcm_s16le", "-ar", str(SR), "-ac", "2",
                         str(out_path)],
               cancel_event=cancel_event)
    return out_path


# ---------------------------------------------------------------------------
# Filter pencampuran (ducking)
# ---------------------------------------------------------------------------
def ducking_filter(sfx_volume: float = 0.4) -> str:
    """Filter untuk [1:a]=ucapan, [2:a]=trek SFX -> [aout].

    Ucapan di-split: satu jadi kunci sidechain, satu dicampur langsung.
    SFX dikompres saat ucapan berbunyi, lalu dijumlah tanpa normalisasi
    agar level ucapan tidak turun.
    """
    return (
        "[1:a]aresample=44100,asplit=2[spk][key];"
        f"[2:a]aresample=44100,volume={sfx_volume}[sfxv];"
        "[sfxv][key]sidechaincompress=threshold=0.03:ratio=8:"
        "attack=20:release=300:makeup=1[sfxd];"
        "[spk][sfxd]amix=inputs=2:normalize=0[aout]"
    )


# ---------------------------------------------------------------------------
# Pengukuran untuk QA / uji
# ---------------------------------------------------------------------------
def rms_db(wav_path: Path, start: float, end: float) -> float:
    """Level RMS (dBFS) pada jendela [start, end). -inf bila hening."""
    with wave.open(str(wav_path), "rb") as w:
        sr, n, sw = w.getframerate(), w.getnframes(), w.getsampwidth()
        dur = n / sr
        s0 = max(0, int(start * sr))
        s1 = min(n, int(end * sr))
        if s1 <= s0:
            return float("-inf")
        w.setpos(s0)
        raw = w.readframes(s1 - s0)
    dtype = np.int16 if sw == 2 else np.int32
    pcm = np.frombuffer(raw, dtype=dtype).astype(np.float64)
    pcm = pcm.reshape(-1, w.getnchannels()).mean(axis=1)
    peak = np.abs(pcm).max()
    if peak == 0:
        return float("-inf")
    rms = np.sqrt(np.mean((pcm / (2 ** (8 * sw - 1))) ** 2))
    if rms <= 0:
        return float("-inf")
    return float(20 * np.log10(rms))


def extract_wav(source: Path, out: Path, start: float = 0.0,
                end: Optional[float] = None) -> Path:
    """Ekstrak audio jadi WAV 44.1kHz mono-16bit (untuk ukur)."""
    args = ["-i", str(source), "-vn", "-ar", "44100", "-ac", "1",
            "-c:a", "pcm_s16le"]
    if start:
        args += ["-ss", f"{start:.3f}"]
    if end is not None:
        args += ["-t", f"{end - start:.3f}"]
    args.append(str(out))
    run_ffmpeg(args)
    return out
