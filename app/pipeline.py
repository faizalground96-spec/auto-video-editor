"""pipeline.py — Tahap 9: alur ujung-ke-ujung dipakai CLI dan GUI.

Tahapan: probe -> transkrip -> face track -> analisis (Gemini/Fake) ->
validasi -> render (+QA). Mendukung 3 mode (auto/preset/auto+kunci),
dry-run, from-edl, preview, dan pembatalan.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .analyze import FakeClient, GeminiClient, analyze_video
from .presets import apply_fixed as preset_apply_fixed
from .presets import load_preset, preset_allowed_ids
from .probe import probe
from .reframe import ensure_face_track
from .registry import EffectRegistry
from .render import render_edl
from .transcribe import transcribe
from .utils import app_dirs, resource_path
from .validate import validate_edl

log = logging.getLogger("auto_video_editor.pipeline")


@dataclass
class PipelineOptions:
    input: Path
    out: Optional[Path] = None
    aspect: str = "9:16"          # atau "auto" -> ikuti sumber
    reframe: str = "auto"         # auto/smart_crop/blur_fill/letterbox
    mode: str = "auto"            # auto/preset/auto+kunci
    preset: Optional[str] = None
    disable: list[str] = field(default_factory=list)
    intensity: Optional[str] = None   # None -> Gemini/preset default
    user_notes: str = ""
    lang: Optional[str] = None
    no_sfx: bool = False
    dry_run: bool = False
    from_edl: Optional[Path] = None
    preview: Optional[float] = None   # detik, draft rendah
    force_reanalyze: bool = False
    fake_llm: Optional[Path] = None
    no_ai: bool = False          # EDL dari aturan preset, tanpa Gemini
    seed: Optional[int] = None
    work_dir: Optional[Path] = None
    api_key: Optional[str] = None


class Pipeline:
    """Orkestrasi satu render. Progress via on_progress(stage, frac)."""

    STAGES = ("probe", "transkrip", "analisis", "validasi", "render", "qa")

    def __init__(self, config: dict, on_progress: Optional[Callable] = None,
                 on_log: Optional[Callable[[str], None]] = None,
                 cancel_event: Optional[threading.Event] = None):
        self.config = config
        self.on_progress = on_progress or (lambda s, f: None)
        self.on_log = on_log or (lambda m: None)
        self.cancel = cancel_event or threading.Event()
        self.registry = EffectRegistry(resource_path("catalog"),
                                       resource_path("assets")).load()
        self.dirs = app_dirs()

    def _p(self, stage: str, frac: float):
        self.on_progress(stage, frac)

    def _log(self, msg: str):
        log.info(msg)
        self.on_log(msg)

    def _check_cancel(self):
        if self.cancel.is_set():
            raise InterruptedError("dibatalkan pengguna")

    # -- API key -----------------------------------------------------------
    def _api_key(self, opt: PipelineOptions) -> Optional[str]:
        if opt.api_key:
            return opt.api_key
        import os
        key = os.environ.get("GEMINI_API_KEY", "")
        if key:
            return key
        # file di folder data (disimpan GUI)
        kf = Path(self.dirs["base"]) / "gemini_key.txt"
        if kf.is_file():
            return kf.read_text(encoding="utf-8").strip()
        return None

    # -- LLM client --------------------------------------------------------
    def _client(self, opt: PipelineOptions):
        if opt.fake_llm:
            return FakeClient(opt.fake_llm)
        key = self._api_key(opt)
        if not key:
            raise RuntimeError(
                "API key Gemini tak ada. Isi di GUI atau set GEMINI_API_KEY.")
        return GeminiClient(key, self.config.get("gemini", {}))

    # -- run ---------------------------------------------------------------
    def run(self, opt: PipelineOptions) -> dict:
        opt.input = Path(opt.input)
        if opt.work_dir:
            work = Path(opt.work_dir)
        else:
            import re, hashlib
            stem = re.sub(r"[^\w\-. ]+", "_",
                          opt.input.stem).strip() or "video"
            if len(stem) > 60:
                h = hashlib.sha256(stem.encode()).hexdigest()[:8]
                stem = stem[:50] + "_" + h
            work = self.dirs["work"] / stem
        work.mkdir(parents=True, exist_ok=True)
        # log ke berkas (plan: log pipeline tersimpan)
        fh = logging.FileHandler(work / "pipeline.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger("auto_video_editor").addHandler(fh)
        try:
            return self._run(opt, work)
        finally:
            logging.getLogger("auto_video_editor").removeHandler(fh)
            fh.close()

    def _run(self, opt: PipelineOptions, work: Path) -> dict:
        self._p("probe", 0.0)
        self._log(f"Probe: {opt.input.name}")
        info = probe(opt.input)
        self._check_cancel()

        aspect = opt.aspect
        if aspect == "auto":
            aspect = {"vertical": "9:16", "horizontal": "16:9",
                      "square": "1:1"}.get(info.orientation, "9:16")
        self._log(f"Aspek: {aspect} (sumber {info.orientation})")

        # -- mode & preset -------------------------------------------------
        preset = load_preset(opt.preset) if opt.preset else None
        if opt.mode == "preset" and preset is None:
            self._log(f"Paket '{opt.preset}' tak ada -> fallback auto")
            opt.mode = "auto"
        allowed = preset_allowed_ids(preset, self.registry) \
            if preset else None
        denied = list(opt.disable) or None
        if opt.mode == "preset" and preset:
            self._log(f"Mode preset: {preset['name']} "
                      f"({len(allowed)} efek boleh)")
        elif denied:
            self._log(f"Mode auto+kunci: matikan {denied}")

        # -- from-edl (tanpa Gemini) ---------------------------------------
        if opt.from_edl:
            self._log(f"Render dari EDL: {opt.from_edl}")
            return self._render_only(opt, work, info, aspect,
                                     json.loads(Path(opt.from_edl)
                                                .read_text(encoding="utf-8")))

        # -- transkrip ------------------------------------------------------
        self._p("transkrip", 0.05)
        self._log("Transkripsi...")
        tr = transcribe(opt.input, work, self.config["transcribe"],
                        lang=opt.lang,
                        model_dir=self.dirs["base"] / "models",
                        cancel_event=self.cancel)
        vdir = tr["video_dir"]
        words = json.loads((vdir / "words.json").read_text(encoding="utf-8"))
        silences = json.loads((vdir / "silences.json").read_text(
            encoding="utf-8"))
        self._log(f"Transkrip: {len(words)} kata")
        self._check_cancel()

        # -- face track (bila perlu smart_crop) -----------------------------
        self._p("transkrip", 0.09)
        face_track = ensure_face_track(
            opt.input, vdir, {"face_sample_interval": 0.5},
            resource_path("assets/models/face_detection_yunet_2023mar.onnx"),
            info)
        n_face = sum(1 for s in face_track.get("samples", []) if s.get("faces"))
        face_summary = f"{n_face}/{len(face_track.get('samples', []))} sampel ada wajah"

        # -- analisis --------------------------------------------------------
        self._p("analisis", 0.10)
        intensity_hint = opt.intensity or (
            preset.get("default_intensity") if preset else None)
        notes = opt.user_notes or ""
        if intensity_hint:
            notes = (notes + f" [intensitas: {intensity_hint}]").strip()
        if opt.no_ai:
            self._log("Mode tanpa AI: EDL dari aturan preset...")
            from .analyze import rule_based_edl
            raw = rule_based_edl(info.duration, aspect, words, silences,
                                 preset, self.registry)
        else:
            self._log("Analisis Gemini...")
            client = self._client(opt)
            raw = analyze_video(opt.input, words, silences, face_summary,
                                self.registry, client, self.config, vdir,
                                aspect=aspect, user_notes=notes,
                                seed=opt.seed,
                                force_reanalyze=opt.force_reanalyze,
                                cancel_event=self.cancel,
                                allowed=allowed, denied=denied)
        raw = preset_apply_fixed(raw, preset)
        self._check_cancel()

        # -- validasi ---------------------------------------------------------
        self._p("validasi", 0.30)
        ok, errors, edl = validate_edl(
            raw, registry=self.registry, words=words, silences=silences,
            duration=info.duration, aspect=aspect, cfg=self.config,
            dry_run=opt.dry_run, work_dir=vdir,
            face_detected=n_face > 0, allowed=allowed, denied=denied)
        if not ok:
            raise RuntimeError("EDL tak valid: " + "; ".join(errors[:3]))
        self._log(f"EDL valid: {len(edl['segments'])} segmen")
        edl_json = work / "edl.json"
        edl_json.write_text(json.dumps(raw, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        why_txt = work / "edl_why.txt"
        why_txt.write_text(self._why_text(edl), encoding="utf-8")
        self._log(f"EDL tersimpan: {edl_json}")

        if opt.dry_run:
            self._p("qa", 1.0)
            return {"edl": str(edl_json), "why": str(why_txt),
                    "dry_run": True, "work_dir": str(work)}

        return self._render_only(opt, work, info, aspect, raw, words=words)

    # -- render --------------------------------------------------------------
    def _render_only(self, opt: PipelineOptions, work: Path, info,
                     aspect: str, edl_dict: dict,
                     words: Optional[list] = None) -> dict:
        self._p("render", 0.35)
        out = Path(opt.out) if opt.out else (
            self.dirs["output"] / f"{opt.input.stem}_edited.mp4")
        out.parent.mkdir(parents=True, exist_ok=True)

        cfg = dict(self.config)
        if opt.no_sfx:
            cfg = {**cfg, "sfx": {**cfg.get("sfx", {}), "enabled": False}}
        # reframe override
        if opt.reframe != "auto":
            cfg = {**cfg, "reframe": {"mode": opt.reframe}}
        # preview: potong sumber jadi N detik pertama
        src = opt.input
        if opt.preview:
            from .utils import run_ffmpeg, find_ffmpeg
            pv = work / f"preview_{int(opt.preview)}s.mp4"
            if not pv.is_file():
                self._log(f"Preview: potong {opt.preview} dtk")
                run_ffmpeg(["-i", str(src), "-t", str(opt.preview),
                            "-c", "copy", str(pv)])
            src = pv
            cfg = {**cfg, "output": {**cfg.get("output", {}),
                                     "crf": 30, "preset": "ultrafast"}}

        edl_p = work / "edl_render.json"
        edl_p.write_text(json.dumps(edl_dict, ensure_ascii=False),
                         encoding="utf-8")
        self._log(f"Render -> {out.name}")

        def _prog(f: float):
            self._p("render", 0.35 + f * 0.55)

        res = render_edl(edl_p, src, out, words=words or [], config=cfg,
                         work_root=work / "render",
                         catalog_dir=resource_path("catalog"),
                         assets_dir=resource_path("assets"),
                         model_dir=self.dirs["base"] / "models",
                         on_progress=_prog, cancel_event=self.cancel)
        self._p("qa", 0.95)
        qa = res["qa"]
        self._log(f"QA: {'LULUS' if qa['passed'] else 'GAGAL'}")
        self._p("qa", 1.0)
        return {"output": str(out), "qa": qa, "work_dir": str(work),
                "edl": str(edl_p)}

    # -- teks why --------------------------------------------------------------
    def _why_text(self, edl: dict) -> str:
        lines = []
        g = edl.get("global", {}) or {}
        lines.append(
            f"Gaya: {(g.get('text_style') or {}).get('id')} + "
            f"{(g.get('grade') or {}).get('id')} "
            f"({g.get('intensity')})")
        for s in edl.get("segments", []):
            lines.append(f"\n[{s['start']:.0f}-{s['end']:.0f}] "
                         f"{s.get('role')}: {s.get('why') or ''}")
            for e in s.get("effects", []):
                at = e.get("at")
                lines.append(f"  - {e['id']}" + (f" @ {at:.1f}s"
                                                 if at is not None else ""))
        if edl.get("closing"):
            lines.append(f"\nClosing: {edl['closing']}")
        return "\n".join(lines)
