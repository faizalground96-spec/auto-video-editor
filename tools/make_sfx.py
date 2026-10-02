#!/usr/bin/env python3
"""tools/make_sfx.py — sintesis SFX orisinal via numpy (bebas lisensi).

Jenis (44.1kHz, mono, 16-bit WAV):
  swoosh : sapuan frekuensi 200->2000 Hz, 0,4 dtk  (transisi, whip)
  boom   : sinus 60 Hz + decay eksponensial, 0,5 dtk (zoom, punch)
  pop    : klik 1200 Hz sangat pendek, 0,09 dtk   (penekanan, emoji)
  riser  : derau tersaring menanjak, 1,0 dtk      (closing, penutup)

Jalankan:  python tools/make_sfx.py  -> menulis ke assets/sfx/
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

SR = 44100


def _envelope(n: int, attack: float = 0.01, release: float = 0.15) -> np.ndarray:
    """Amplop attack/release halus (hindari klik)."""
    env = np.ones(n)
    a = max(1, int(n * attack))
    r = max(1, int(n * release))
    env[:a] = np.linspace(0, 1, a)
    env[-r:] = np.linspace(1, 0, r)
    return env


def swoosh(dur: float = 0.4) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    # sapuan frekuensi eksponensial 200 -> 2000 Hz
    f0, f1 = 200.0, 2000.0
    phase = 2 * np.pi * f0 * dur / np.log(f1 / f0) * (
        np.exp(np.log(f1 / f0) * t / dur) - 1)
    sig = np.sin(phase)
    return sig * _envelope(n, 0.05, 0.3)


def boom(dur: float = 0.5) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    sig = np.sin(2 * np.pi * 60 * t) * np.exp(-t * 9)
    sig += 0.4 * np.sin(2 * np.pi * 120 * t) * np.exp(-t * 12)
    return sig * _envelope(n, 0.005, 0.4)


def pop(dur: float = 0.09) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    sig = np.sin(2 * np.pi * 1200 * t) * np.exp(-t * 70)
    return sig * _envelope(n, 0.02, 0.5)


def riser(dur: float = 1.0) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    noise = np.random.default_rng(7).standard_normal(n)
    # lolos-rendah sederhana (rata-rata bergerak) + amplitudo menanjak
    k = 64
    kernel = np.ones(k) / k
    smooth = np.convolve(noise, kernel, mode="same")
    ramp = (t / dur) ** 1.5
    sig = smooth / (np.abs(smooth).max() + 1e-9) * ramp
    return sig * _envelope(n, 0.02, 0.1)


MAKERS = {"swoosh": swoosh, "boom": boom, "pop": pop, "riser": riser}


def write_wav(path: Path, sig: np.ndarray, target_rms_db: float = -20.0) -> None:
    import wave
    # normalisasi ke RMS target agar SFX duduk jauh di bawah ucapan
    rms = np.sqrt(np.mean(sig ** 2)) + 1e-9
    sig = sig / rms * 10 ** (target_rms_db / 20)
    sig = np.clip(sig, -1, 1)
    pcm = (sig * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main() -> int:
    out_dir = Path(__file__).resolve().parent.parent / "assets" / "sfx"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, fn in MAKERS.items():
        p = out_dir / f"{name}.wav"
        write_wav(p, fn())
        print(f"OK: {p} ({p.stat().st_size} byte)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
