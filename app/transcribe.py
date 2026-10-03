"""transcribe.py — transkrip per kata (faster-whisper) + deteksi jeda.

Keluaran di work/<nama_video>/:
  audio.wav       audio mono 16kHz hasil ekstraksi
  words.json      [{"i": 0, "word": "...", "start": 0.00, "end": 0.00,
                    "prob": 0.97}]  (indeks i dipakai Gemini & validator)
  transcript.txt  teks berindeks untuk prompt ("[12] rahasia")
  sentences.json  kalimat/klausa (pisah tanda baca atau jeda > 0,6 dtk)
  silences.json   jeda dari ffmpeg silencedetect (untuk snapping & Fase 2)
  meta.json       kunci cache: hash isi sumber + model + bahasa

Cache dipakai hanya bila kuncinya sama persis, bukan sekadar "file ada".
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .probe import SourceInfo, probe
from .utils import CancelledError, find_ffmpeg, log, run_ffmpeg

# Model diunduh ke folder data aplikasi (bukan bundel), dengan progres.
# Diisi saat runtime oleh pemanggil (app_dirs()/config); default: ~/.cache.
DEFAULT_MODEL_DIR = Path.home() / ".cache" / "autovideoeditor" / "models"

_SENT_END = re.compile(r"[.!?…]+$")


def _hash_source(path: Path) -> str:
    """Hash isi file: ukuran + sha256 potongan awal/tengah/akhir (1MB tiap)."""
    size = path.stat().st_size
    h = hashlib.sha256()
    h.update(str(size).encode())
    if size == 0:
        return h.hexdigest()
    chunk = 1_000_000
    with open(path, "rb") as f:
        h.update(f.read(chunk))                       # awal
        if size > 2 * chunk:
            f.seek(size // 2)
            h.update(f.read(chunk))                   # tengah
            f.seek(max(0, size - chunk))
            h.update(f.read(chunk))                   # akhir
    return h.hexdigest()


def _video_dir(work_root: Path, source: Path) -> Path:
    """Folder kerja per video: work/<nama_video>/ (nama disterilkan)."""
    stem = re.sub(r"[^\w\-. ]+", "_", source.stem).strip() or "video"
    d = work_root / stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def extract_audio(source: Path, wav_path: Path,
                  cancel_event: Optional[threading.Event] = None) -> None:
    """Ekstrak audio mono 16kHz untuk Whisper."""
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-i", str(source), "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le", str(wav_path)],
               cancel_event=cancel_event)
    log.info("audio diekstrak: %s", wav_path.name)


def detect_silences(wav_path: Path, noise_db: float = -35.0,
                    min_dur: float = 0.25) -> list[dict]:
    """Jeda via ffmpeg silencedetect. -> [{"start":.., "end":..}]"""
    ffmpeg = str(find_ffmpeg())
    cmd = [ffmpeg, "-hide_banner", "-i", str(wav_path),
           "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
           "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    silences: list[dict] = []
    cur_start: Optional[float] = None
    for line in (out.stderr or "").splitlines():
        m1 = re.search(r"silence_start:\s*([0-9.]+)", line)
        m2 = re.search(r"silence_end:\s*([0-9.]+)", line)
        if m1:
            cur_start = float(m1.group(1))
        elif m2 and cur_start is not None:
            silences.append({"start": round(cur_start, 3),
                             "end": round(float(m2.group(1)), 3)})
            cur_start = None
    return silences


def _normalize_words(raw: list[dict]) -> list[dict]:
    """Pastikan timestamp monoton naik dan tidak tumpang tindih.

    Whisper kadang memberi end > start kata berikutnya; jepit agar
    invariant yang diminta plan selalu terpenuhi.
    """
    words = []
    for i, w in enumerate(raw):
        words.append({
            "i": i,
            "word": w["word"],
            "start": round(float(w["start"]), 3),
            "end": round(float(w["end"]), 3),
            "prob": round(float(w.get("prob", 0.0)), 3),
        })
    for i in range(len(words) - 1):
        if words[i]["end"] > words[i + 1]["start"]:
            words[i]["end"] = words[i + 1]["start"]
        if words[i]["start"] > words[i]["end"]:
            words[i]["start"] = words[i]["end"]
    return words


def _make_sentences(words: list[dict]) -> list[dict]:
    """Kelompokkan kata jadi kalimat: pisah di tanda baca atau jeda > 0,6 dtk."""
    sentences: list[dict] = []
    cur: list[dict] = []

    def flush():
        if cur:
            sentences.append({
                "start": cur[0]["start"],
                "end": cur[-1]["end"],
                "text": "".join(w["word"] for w in cur).strip(),
                "word_idx": [cur[0]["i"], cur[-1]["i"]],
            })
            cur.clear()

    for n, w in enumerate(words):
        cur.append(w)
        gap = words[n + 1]["start"] - w["end"] if n + 1 < len(words) else 0
        if _SENT_END.search(w["word"].strip()) or gap > 0.6:
            flush()
    flush()
    return sentences


def transcribe(
    source: str | Path,
    work_root: str | Path,
    cfg: dict,
    lang: Optional[str] = None,
    model_dir: Optional[Path] = None,
    on_progress: Optional[Callable[[str, float], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> dict:
    """Transkrip per kata. Mengembalikan dict berisi path hasil + ringkasan.

    cfg: bagian `transcribe:` dari config.yaml.
    lang: override bahasa ("id"/"en"/...); None -> pakai cfg (auto=None).
    """
    from faster_whisper import WhisperModel  # impor lambat (berat)
    from .utils import sanitize_proxy_env
    sanitize_proxy_env()  # no_proxy bracket merusak httpx (huggingface_hub)

    source = Path(source)
    work_root = Path(work_root)
    vdir = _video_dir(work_root, source)
    info: SourceInfo = probe(source)

    model_name = cfg.get("model", "small")
    language = lang or cfg.get("language", "auto")
    if language == "auto":
        language = None

    meta_path = vdir / "meta.json"
    key = {
        "source_hash": _hash_source(source),
        "model": model_name,
        "language": language or "auto",
    }
    if meta_path.is_file():
        try:
            old = json.loads(meta_path.read_text(encoding="utf-8"))
            if old.get("key") == key and (vdir / "words.json").is_file():
                log.info("transkrip cache dipakai: %s", vdir.name)
                return {"video_dir": vdir, "cached": True,
                        "meta": old, "info": info}
        except (json.JSONDecodeError, OSError):
            pass  # cache rusak -> transkrip ulang

    if cancel_event and cancel_event.is_set():
        raise CancelledError("transkrip dibatalkan")

    if not info.has_audio:
        meta = {"key": key, "no_speech": True, "reason": "no_audio",
                "words": 0}
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        (vdir / "words.json").write_text("[]", encoding="utf-8")
        (vdir / "transcript.txt").write_text("", encoding="utf-8")
        (vdir / "sentences.json").write_text("[]", encoding="utf-8")
        (vdir / "silences.json").write_text("[]", encoding="utf-8")
        log.info("tanpa audio -> transkrip dilewati: %s", source.name)
        return {"video_dir": vdir, "cached": False, "meta": meta, "info": info}

    if on_progress:
        on_progress("audio", 0.0)
    wav_path = vdir / "audio.wav"
    extract_audio(source, wav_path, cancel_event)

    if on_progress:
        on_progress("silence", 0.0)
    silences = detect_silences(wav_path)
    (vdir / "silences.json").write_text(
        json.dumps(silences, indent=2), encoding="utf-8")
    log.info("%d jeda terdeteksi", len(silences))

    if on_progress:
        on_progress("whisper", 0.0)
    t0 = time.time()
    log.info("Memuat model Whisper '%s' (unduh otomatis bila belum ada)...",
             model_name)
    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type=cfg.get("compute_type", "int8"),
        cpu_threads=int(cfg.get("cpu_threads", 0)),
        download_root=str(model_dir or DEFAULT_MODEL_DIR),
    )
    segments, sw_info = model.transcribe(
        str(wav_path),
        language=language,
        word_timestamps=True,
        vad_filter=bool(cfg.get("vad_filter", True)),
        condition_on_previous_text=False,  # kurangi halusinasi berulang
    )
    raw: list[dict] = []
    for seg in segments:
        if cancel_event and cancel_event.is_set():
            raise CancelledError("transkrip dibatalkan")
        for w in seg.words or []:
            raw.append({"word": w.word, "start": w.start, "end": w.end,
                        "prob": w.probability})
    dt = time.time() - t0

    words = _normalize_words(raw)
    (vdir / "words.json").write_text(
        json.dumps(words, indent=2, ensure_ascii=False), encoding="utf-8")
    (vdir / "transcript.txt").write_text(
        "\n".join(f"[{w['i']}] {w['word'].strip()}" for w in words),
        encoding="utf-8")
    sentences = _make_sentences(words)
    (vdir / "sentences.json").write_text(
        json.dumps(sentences, indent=2, ensure_ascii=False), encoding="utf-8")

    meta = {"key": key, "no_speech": len(words) == 0,
            "words": len(words), "sentences": len(sentences),
            "silences": len(silences),
            "transcribe_s": round(dt, 1),
            "time_factor": round(dt / max(sw_info.duration, 0.01), 3),
            "detected_language": getattr(sw_info, "language", None),
            "language_probability": round(
                getattr(sw_info, "language_probability", 0.0), 3)}
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    factor = meta["time_factor"]
    log.info("transkrip selesai: %d kata, %d kalimat, faktor waktu %.2f",
             len(words), len(sentences), factor)
    return {"video_dir": vdir, "cached": False, "meta": meta, "info": info}
