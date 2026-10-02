"""Uji app/transcribe.py — tanpa jaringan (model sudah diunduh), tanpa API key."""
import json
from pathlib import Path

import pytest
import yaml

from app.transcribe import (
    _make_sentences,
    _normalize_words,
    transcribe,
)
from app.utils import find_ffmpeg

import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CFG = yaml.safe_load(open(Path(__file__).resolve().parent.parent
                          / "config.yaml"))["transcribe"]
MODEL_DIR = Path(__file__).resolve().parent.parent / "assets" / "models"


def _sine_video(out: Path, name: str = "sine") -> Path:
    """Video 3 dtk: testsrc + nada sinus (tanpa ucapan)."""
    fp = out / f"{name}.mp4"
    subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset",
         "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(fp)],
        check=True)
    return fp


def _noaudio_video(out: Path) -> Path:
    fp = out / "noaudio.mp4"
    subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=2",
         "-map", "0:v", "-an", "-c:v", "libx264", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", str(fp)],
        check=True)
    return fp


def test_no_speech_sine(tmp_path):
    src = _sine_video(tmp_path)
    r = transcribe(src, tmp_path / "work", CFG, model_dir=MODEL_DIR)
    assert r["cached"] is False
    assert r["meta"]["no_speech"] is True
    words = json.loads((r["video_dir"] / "words.json").read_text())
    assert words == []
    assert (r["video_dir"] / "transcript.txt").read_text() == ""
    # jeda & kalimat tetap ada bentuknya
    assert isinstance(
        json.loads((r["video_dir"] / "silences.json").read_text()), list)


def test_no_audio_source(tmp_path):
    src = _noaudio_video(tmp_path)
    r = transcribe(src, tmp_path / "work", CFG, model_dir=MODEL_DIR)
    assert r["meta"]["no_speech"] is True
    assert r["meta"]["reason"] == "no_audio"
    assert not (r["video_dir"] / "audio.wav").exists()


def test_cache_hit(tmp_path):
    src = _sine_video(tmp_path)
    work = tmp_path / "work"
    r1 = transcribe(src, work, CFG, model_dir=MODEL_DIR)
    assert r1["cached"] is False
    r2 = transcribe(src, work, CFG, model_dir=MODEL_DIR)
    assert r2["cached"] is True
    assert r2["video_dir"] == r1["video_dir"]


def test_cache_invalidated_by_change(tmp_path):
    src = _sine_video(tmp_path, "a")
    work = tmp_path / "work"
    transcribe(src, work, CFG, model_dir=MODEL_DIR)
    # ubah isi file (tambah 1 detik via concat ulang sederhana: append byte)
    with open(src, "ab") as f:
        f.write(b"\x00" * 1000)
    r = transcribe(src, work, CFG, model_dir=MODEL_DIR)
    assert r["cached"] is False  # hash berubah -> transkrip ulang


def test_normalize_words_clamps_overlap():
    raw = [
        {"word": " halo", "start": 0.0, "end": 1.5, "prob": 0.9},
        {"word": " dunia", "start": 1.0, "end": 2.0, "prob": 0.8},
    ]
    words = _normalize_words(raw)
    assert words[0]["end"] == pytest.approx(1.0)  # dijepit ke start berikut
    assert words[0]["start"] <= words[1]["start"]
    assert words[0]["end"] <= words[1]["start"]
    assert [w["i"] for w in words] == [0, 1]


def test_make_sentences_punctuation_and_gap():
    def w(i, word, s, e):
        return {"i": i, "word": word, "start": s, "end": e, "prob": 1.0}
    words = [
        w(0, " halo", 0.0, 0.5), w(1, " dunia.", 0.6, 1.0),   # titik
        w(2, " apa", 1.1, 1.4), w(3, " kabar", 2.5, 2.8),     # jeda 1.1 dtk
        w(4, " baik", 2.9, 3.1),
    ]
    sents = _make_sentences(words)
    assert len(sents) == 3
    assert sents[0]["word_idx"] == [0, 1]
    assert sents[1]["word_idx"] == [2, 2]
    assert sents[2]["word_idx"] == [3, 4]
    assert sents[0]["start"] == 0.0 and sents[0]["end"] == 1.0
