"""analyze.py — Tahap 6: Gemini menganalisis video -> draf EDL.

Alur: buat proxy kecil -> unggah via Files API -> tunggu ACTIVE ->
minta JSON EDL -> validasi (app/validate.py) -> hapus file yang diunggah.

Privasi: file di Gemini WAJIB dihapus setelah analisis (delete_uploaded_after).
pytest tidak boleh butuh jaringan: pakai FakeClient + fixture.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .probe import probe
from .utils import redact, run_ffmpeg, sanitize_proxy_env

log = logging.getLogger("auto_video_editor.analyze")


# ---------------------------------------------------------------------------
# Proxy analisis
# ---------------------------------------------------------------------------
def make_proxy(source: Path, out_path: Path, cfg: dict,
               cancel_event=None) -> Path:
    """Video kecil utk analisis: tinggi maks proxy_height, CRF ~28,
    audio tetap ada, linimasa TIDAK diubah (tanpa potong)."""
    source = Path(source)
    h = int(cfg.get("proxy_height", 540))
    crf = int(cfg.get("proxy_crf", 28))
    info = probe(source)
    fps = info.fps or 30.0
    # scale: tinggi -> h bila lebih besar; pertahankan aspek; genap.
    vf = (f"scale=-2:min'(ih,{h})':eval=frame,"
          f"fps={fps:.3f},format=yuv420p")
    run_ffmpeg([
        "-i", str(source),
        "-vf", vf,
        "-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "96k", "-ac", "2",
        "-movflags", "+faststart",
        str(out_path),
    ], cancel_event=cancel_event)
    return out_path


# ---------------------------------------------------------------------------
# Klien LLM
# ---------------------------------------------------------------------------
@dataclass
class AnalyzeRequest:
    video_path: Path            # proxy (GeminiClient) / apa pun (Fake)
    transcript_indexed: str     # transkrip berindeks "[12] kata"
    catalog_text: str           # registry.describe()
    duration: float
    face_summary: str
    aspect: str
    source_orientation: str
    user_notes: str = ""
    system_prompt: str = ""
    extra: dict = field(default_factory=dict)


class LLMClient(ABC):
    @abstractmethod
    def analyze(self, req: AnalyzeRequest) -> dict:
        """Kembalikan dict JSON EDL (belum divalidasi)."""


class FakeClient(LLMClient):
    """Membaca respons rekaman dari fixture — untuk pytest offline."""

    def __init__(self, fixture_path: str | Path):
        self.fixture_path = Path(fixture_path)

    def analyze(self, req: AnalyzeRequest) -> dict:
        data = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        log.info("FakeClient memakai fixture: %s", self.fixture_path.name)
        return data


class GeminiClient(LLMClient):
    """Gemini via Files API. File dihapus setelah analisis (bila diatur)."""

    def __init__(self, api_key: str, cfg: dict):
        sanitize_proxy_env()
        from google import genai  # impor lambat
        self._genai = genai
        self.client = genai.Client(api_key=api_key)
        self.cfg = cfg
        self.model = cfg.get("model", "gemini-2.5-flash")
        self.fallback_model = cfg.get("fallback_model") or None
        self.max_net_retries = int(cfg.get("max_net_retries", 3))
        self.timeout_s = int(cfg.get("timeout_s", 300))
        self.delete_after = bool(cfg.get("delete_uploaded_after", True))
        self.temperature = float(cfg.get("temperature", 0.4))

    # -- Files API ---------------------------------------------------------
    def _upload(self, proxy: Path):
        log.info("mengunggah proxy: %s", proxy.name)
        f = self.client.files.upload(file=str(proxy))
        # tunggu ACTIVE
        t0 = time.time()
        while True:
            f = self.client.files.get(name=f.name)
            state = getattr(f.state, "name", str(f.state))
            if state == "ACTIVE":
                break
            if state == "FAILED":
                raise RuntimeError(f"upload {f.name} FAILED di Files API")
            if time.time() - t0 > self.timeout_s:
                raise TimeoutError("proxy tak kunjung ACTIVE")
            time.sleep(3)
        log.info("proxy ACTIVE: %s", redact(f.name))
        return f

    def _delete(self, uploaded) -> None:
        if not self.delete_after:
            return
        try:
            self.client.files.delete(name=uploaded.name)
            log.info("file terunggah dihapus: %s", redact(uploaded.name))
        except Exception as e:  # jangan gagalkan analisis gara-gara hapus
            log.warning("gagal hapus file terunggah: %s", e)

    # -- generate ----------------------------------------------------------
    def _generate(self, model: str, uploaded, req: AnalyzeRequest) -> str:
        prompt = (
            f"{req.system_prompt}\n\n"
            f"## Video\nDurasi: {req.duration:.1f} detik. "
            f"Ringkasan wajah: {req.face_summary}.\n\n"
            f"## Transkrip berindeks\n{req.transcript_indexed}\n\n"
            f"## Katalog efek (hanya ID ini yang boleh dipakai)\n"
            f"{req.catalog_text}\n"
        )
        if req.user_notes:
            prompt += f"\n## Arahan pengguna\n{req.user_notes}\n"
        contents = [prompt, uploaded]
        cfg_gen = self._genai.types.GenerateContentConfig(
            temperature=self.temperature,
            response_mime_type="application/json",
        )
        for attempt in range(self.max_net_retries + 1):
            try:
                resp = self.client.models.generate_content(
                    model=model, contents=contents, config=cfg_gen)
                text = (resp.text or "").strip()
                # kupas pagar kode ```json ... ```
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text
                    text = text.rsplit("```", 1)[0]
                return text.strip()
            except Exception as e:
                msg = str(e)
                log.warning("generate gagal (percobaan %d): %s",
                            attempt + 1, redact(msg)[:200])
                if any(k in msg for k in ("429", "quota", "QuotaExceeded",
                                          "RESOURCE_EXHAUSTED")):
                    raise RuntimeError(f"kuota Gemini habis: {redact(msg)[:200]}")
                if attempt >= self.max_net_retries:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("generate gagal setelah retry")

    def analyze(self, req: AnalyzeRequest) -> dict:
        uploaded = self._upload(req.video_path)
        try:
            last_err: Optional[Exception] = None
            for model in [m for m in (self.model, self.fallback_model) if m]:
                try:
                    text = self._generate(model, uploaded, req)
                    return json.loads(text)
                except (json.JSONDecodeError, RuntimeError) as e:
                    last_err = e
                    log.warning("model %s gagal: %s", model, str(e)[:150])
            raise RuntimeError(f"semua model gagal: {last_err}")
        finally:
            self._delete(uploaded)


# ---------------------------------------------------------------------------
# Orkestrasi + cache
# ---------------------------------------------------------------------------
def _cache_key(source: Path, words: list[dict], fingerprint: str,
               prompt_text: str, aspect: str, user_notes: str,
               seed: Optional[int]) -> str:
    h = hashlib.sha256()
    h.update(str(source.stat().st_size).encode())
    h.update(str(int(source.stat().st_mtime)).encode())
    h.update(json.dumps([w.get("word") for w in words],
                        ensure_ascii=False).encode())
    h.update(fingerprint.encode())
    h.update(prompt_text.encode())
    h.update(aspect.encode())
    h.update(user_notes.encode())
    h.update(str(seed).encode())
    return h.hexdigest()[:16]


def build_transcript_indexed(words: list[dict]) -> str:
    """Transkrip berindeks: '[12] kata' per kata."""
    return " ".join(f"[{w["i"]}] {w['word']}" for w in words)


def build_system_prompt(cfg: dict, aspect: str, orientation: str,
                        source_orientation: str, user_notes: str) -> str:
    from .utils import resource_path
    tpl = (resource_path("prompts/analyze_system.md")
           .read_text(encoding="utf-8"))
    density = cfg.get("density", {})
    subs = {
        "{aspect}": aspect,
        "{orientation}": orientation,
        "{source_orientation}": source_orientation,
        "{calm_budget}": str(density.get("calm", {}).get(
            "max_strong_per_10s", 1)),
        "{medium_budget}": str(density.get("medium", {}).get(
            "max_strong_per_10s", 3)),
        "{aggressive_budget}": str(density.get("aggressive", {}).get(
            "max_strong_per_10s", 5)),
        "{min_gap_s}": str(density.get("medium", {}).get("min_gap_s", 1.5)),
        "{user_notes}": user_notes or "-",
    }
    for k, v in subs.items():
        tpl = tpl.replace(k, v)
    return tpl


def analyze_video(
    source: Path,
    words: list[dict],
    silences: list[dict],
    face_summary: str,
    registry,  # EffectRegistry
    client: LLMClient,
    cfg: dict,
    work_dir: Path,
    aspect: str = "9:16",
    user_notes: str = "",
    seed: Optional[int] = None,
    force_reanalyze: bool = False,
    cancel_event=None,
) -> dict:
    """Jalankan analisis -> kembalikan dict EDL mentah (belum divalidasi).

    Cache: work_dir/edl_cache.json keyed by hash; dipakai ulang kecuali
    force_reanalyze.
    """
    from .canvas import CANVAS_SPECS
    from .validate import validate_edl

    source, work_dir = Path(source), Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    info = probe(source)
    duration = info.duration or 0.0

    prompt_text = build_system_prompt(
        cfg, aspect, CANVAS_SPECS[aspect]["orientation"],
        info.orientation, user_notes)
    key = _cache_key(source, words, registry.fingerprint(),
                     prompt_text, aspect, user_notes, seed)
    cache_path = work_dir / "edl_cache.json"
    if not force_reanalyze and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("key") == key:
                log.info("cache EDL dipakai: %s", key)
                return cached["edl"]
        except (json.JSONDecodeError, OSError):
            pass

    # proxy (FakeClient tak butuh file nyata, tapi buat konsisten)
    proxy_path = work_dir / "proxy_analyze.mp4"
    if isinstance(client, GeminiClient):
        make_proxy(source, proxy_path, cfg.get("gemini", {}),
                   cancel_event=cancel_event)

    req = AnalyzeRequest(
        video_path=proxy_path,
        transcript_indexed=build_transcript_indexed(words),
        catalog_text=registry.describe(aspect),
        duration=duration,
        face_summary=face_summary,
        aspect=aspect,
        source_orientation=info.orientation,
        user_notes=user_notes,
        system_prompt=prompt_text,
    )

    max_json = int(cfg.get("gemini", {}).get("max_json_retries", 2))
    last_errors: list[str] = []
    raw: Optional[dict] = None
    for attempt in range(max_json + 1):
        if last_errors and isinstance(client, GeminiClient):
            req.system_prompt = (prompt_text +
                                 "\n\nPerbaiki JSON berikut; galat validasi:\n"
                                 + "\n".join(last_errors[-5:]))
        try:
            raw = client.analyze(req)
        except Exception as e:
            last_errors.append(f"panggil LLM gagal: {e}")
            continue
        ok, errors, _edl = validate_edl(
            raw, registry=registry, words=words, silences=silences,
            duration=duration, aspect=aspect, cfg=cfg, dry_run=True)
        if ok:
            break
        last_errors.extend(errors)
        log.warning("EDL tak valid (percobaan %d): %s",
                    attempt + 1, "; ".join(errors[:3]))
    else:
        # rencana cadangan per plan 6e
        log.warning("pakai rencana cadangan setelah %d percobaan",
                    max_json + 1)
        raw = fallback_edl(duration, aspect)

    cache_path.write_text(json.dumps({"key": key, "edl": raw},
                                     ensure_ascii=False), encoding="utf-8")
    return raw


def fallback_edl(duration: float, aspect: str) -> dict:
    """Rencana cadangan bila Gemini gagal total (plan 6e)."""
    return {
        "schema_version": 2,
        "canvas": {"aspect": aspect,
                   "reframe": {"mode": "none",
                               "why": "Rencana cadangan: tanpa reframe."}},
        "analysis": {"topic": "", "genre": "", "mood": "netral",
                     "energy": "medium", "speech_pace": ""},
        "global": {
            "text_style": {"id": "text.clean_caption", "params": {}},
            "grade": {"id": "grade.clean_bright", "params": {}},
            "intensity": "calm",
            "why": "Rencana cadangan.",
        },
        "emphasis_words": [],
        "segments": [
            {"start": 0.0, "end": duration, "role": "body", "effects": [
                {"id": "camera.slow_zoom", "at": None,
                 "params": {"factor": 1.1}}],
             "why": "Rencana cadangan."},
        ],
    }
