"""render.py — KERANGKA mesin render (Tahap 3).

Hanya cukup untuk membuktikan jalur ujung-ke-ujung dengan 4 efek pertama:
normalisasi -> reframe -> grade -> efek segmen -> bakar ASS -> audio copy.
Tahap 4 akan mengganti ini dengan mesin penuh (chunk, manifest, resume,
smart_crop, dsb).
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Callable, Optional

from .canvas import Canvas, resolve_aspect
from .probe import probe
from .registry import EffectRegistry
from .schema import Edl, EffectContext
from .utils import CancelledError, ff_filter_path, log, run_ffmpeg


def _ass_time(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _write_ass(events: list[dict], canvas: Canvas, config: dict,
               fonts_dir: Path, path: Path) -> Path:
    """Tulis file ASS minimal untuk dibakar libass (pass akhir)."""
    cap = config["caption"]
    font_px = canvas.font_px(cap["font_pct"][canvas.aspect])
    anchor_y = cap["anchor_y"][canvas.aspect]
    margin_v = max(10, int(canvas.height * (1 - anchor_y) - font_px * 0.75))
    margin_lr = canvas.w(canvas.safe_side)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {canvas.width}
PlayResY: {canvas.height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{cap['font_family']},{font_px},&H00FFFFFF,&H000019FF,&H00141414,&H99000000,-1,0,0,0,100,100,0,0,1,2,1,2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for ev in events:
        text = ev["text"].replace("\n", "\\N")
        lines.append(
            f"Dialogue: 0,{_ass_time(ev['start'])},{_ass_time(ev['end'])},"
            f"{ev.get('style', 'Caption')},,0,0,0,,{text}")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _video_dir(work_root: Path, source: Path) -> Path:
    stem = re.sub(r"[^\w\-. ]+", "_", source.stem).strip() or "video"
    d = work_root / stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def render_edl(
    edl_path: str | Path,
    source: str | Path,
    output: str | Path,
    words: Optional[list[dict]] = None,
    config: Optional[dict] = None,
    work_root: Optional[str | Path] = None,
    catalog_dir: Optional[str | Path] = None,
    assets_dir: Optional[str | Path] = None,
    model_dir: Optional[str | Path] = None,
    on_progress: Optional[Callable[[float], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Path:
    """Render EDL tulisan tangan (kerangka). Mengembalikan path output."""
    import yaml  # impor lokal agar modul ringan

    source = Path(source)
    output = Path(output)
    edl = Edl.model_validate(json.loads(Path(edl_path).read_text()))

    if config is None:
        from .utils import resource_path
        config = yaml.safe_load(
            (resource_path("config.yaml")).read_text(encoding="utf-8"))

    info = probe(source)
    aspect = edl.canvas.aspect
    if aspect == "auto":
        aspect = resolve_aspect("auto", info.aspect_ratio())
    canvas = Canvas.from_aspect(aspect)

    if work_root is None:
        from .utils import app_dirs
        work_root = app_dirs()["work"]
    vdir = _video_dir(Path(work_root), source)
    rdir = vdir / "render_skeleton"
    rdir.mkdir(parents=True, exist_ok=True)

    if catalog_dir is None:
        from .utils import resource_path
        catalog_dir = resource_path("catalog")
    registry = EffectRegistry(catalog_dir, assets_dir).load()

    if words is None:
        from .transcribe import transcribe
        r = transcribe(source, work_root, config["transcribe"],
                       model_dir=Path(model_dir) if model_dir else None)
        words = json.loads((r["video_dir"] / "words.json").read_text())

    ctx = EffectContext(canvas=canvas, source=info, words=words,
                        work_dir=rdir,
                        assets_dir=Path(assets_dir) if assets_dir
                        else Path("assets"),
                        config=config, face_track=None)

    segs: list[str] = []
    segs.append("[0:v]fps=30,setsar=1,format=yuv420p[vbase];")

    # -- reframe ---------------------------------------------------------
    mode = edl.canvas.reframe.mode
    if mode == "none":
        if (info.width, info.height) == (canvas.width, canvas.height):
            segs.append("[vbase]null[vref];")
        else:
            segs.append(
                f"[vbase]scale={canvas.width}:{canvas.height}:"
                f"force_original_aspect_ratio=increase,"
                f"crop={canvas.width}:{canvas.height}[vref];")
    else:
        out = registry.build(f"reframe.{mode}", ctx, None, {})
        assert len(out.video_filters) == 1 and "[vbase]" in out.video_filters[0]
        segs.append(out.video_filters[0] + ";")

    # -- grade global ----------------------------------------------------
    cur = "vref"
    if edl.global_.grade:
        g = edl.global_.grade
        out = registry.build(g.id, ctx, None, g.params)
        nxt = "vg"
        for f in out.video_filters:
            segs.append(f"[{cur}]{f}[{nxt}];")
            cur = nxt

    # -- efek per segmen (diurut waktu; pakai ekspresi t, tanpa split) ----
    seg_effects = []
    for s in edl.segments:
        for e in s.effects:
            seg_effects.append(e)
    seg_effects.sort(key=lambda e: (e.at if e.at is not None else 0.0))
    for k, e in enumerate(seg_effects):
        out = registry.build(e.id, ctx, e.at, e.params)
        for f in out.video_filters:
            nxt = f"vs{k}"
            segs.append(f"[{cur}]{f}[{nxt}];")
            cur = nxt

    # -- teks ASS (pass akhir) -------------------------------------------
    ass_events: list[dict] = []
    if edl.global_.text_style:
        t = edl.global_.text_style
        out = registry.build(t.id, ctx, None, t.params)
        ass_events.extend(out.ass_events)
    fonts_dir = Path(assets_dir) / "fonts" if assets_dir else Path("assets/fonts")
    ass_path = _write_ass(ass_events, canvas, config, fonts_dir,
                          rdir / "subs.ass")
    segs.append(f"[{cur}]ass='{ff_filter_path(ass_path)}':"
                f"fontsdir='{ff_filter_path(fonts_dir)}'[vout];")

    filtergraph = "\n".join(segs)
    fg_path = rdir / "filter_complex.txt"
    fg_path.write_text(filtergraph, encoding="utf-8")

    args = ["-i", str(source), "-filter_complex_script", str(fg_path),
            "-map", "[vout]",
            "-c:v", config["output"].get("encoder", "libx264"),
            "-preset", config["output"].get("preset", "veryfast"),
            "-crf", str(config["output"].get("crf", 20)),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-r", "30"]
    if info.has_audio:
        args += ["-map", "0:a", "-c:a", "copy"]
    else:
        args += ["-an"]
    args.append(str(output))

    output.parent.mkdir(parents=True, exist_ok=True)
    if cancel_event and cancel_event.is_set():
        raise CancelledError("render dibatalkan")
    run_ffmpeg(args, on_progress=on_progress, cancel_event=cancel_event,
               cwd=rdir)
    log.info("render selesai: %s", output)
    return output
