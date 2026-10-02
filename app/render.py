"""render.py — mesin render inti (Tahap 4).

Arsitektur:
  linimasa dipartisi jadi chunk (segmen EDL + celah) ->
  tiap chunk dirender terpisah (video saja) dengan manifest/resume ->
  chunk digabung via concat demuxer ->
  pass akhir: bakar ASS sekali untuk seluruh linimasa + audio ->
  QA otomatis.

Waktu di EDL = waktu video sumber. Efek berbasis `t` memakai waktu
LOKAL chunk (trim+setpts me-reset ke 0); ASS memakai waktu absolut.
Urutan lapisan baku (1.3): normalisasi -> reframe -> kamera -> grade ->
layout/insert -> overlay/transisi -> teks ASS (pass akhir) -> audio.
Maksimal dua kali encode video.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

import yaml

from .canvas import Canvas, resolve_aspect
from .probe import SourceInfo, probe
from .qa import QACtx, run_qa
from .reframe import ensure_face_track, smart_crop_curve
from .registry import EffectRegistry
from .schema import Edl, EffectContext, EffectOutput
from .subtitles import build_ass, write_srt
from .utils import (CancelledError, app_dirs, ff_filter_path, find_ffmpeg,
                    log, resource_path, run_ffmpeg)

CHUNK_CRF = 16
FINAL_CRF_FALLBACK = 20


def _video_dir(work_root: Path, source: Path) -> Path:
    stem = re.sub(r"[^\w\-. ]+", "_", source.stem).strip() or "video"
    d = work_root / stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ffmpeg_version() -> str:
    out = subprocess.run([str(find_ffmpeg()), "-hide_banner", "-version"],
                         capture_output=True, text=True)
    return (out.stdout or "").splitlines()[0] if out.stdout else "?"


def _partition(duration: float, segments: list) -> list[tuple]:
    """Partisi linimasa -> [(start, end, segment|None)]."""
    bounds = {0.0, duration}
    for s in segments:
        bounds.add(max(0.0, s.start))
        bounds.add(min(duration, s.end))
    b = sorted(bounds)
    chunks = []
    for a, c in zip(b[:-1], b[1:]):
        if c - a < 1e-6:
            continue
        seg = next((s for s in segments
                    if s.start <= a + 1e-6 and s.end >= c - 1e-6), None)
        chunks.append((a, c, seg))
    return chunks


def _chunk_hash(source_hash: str, chunk_edl: dict, ffmpeg_v: str,
                fingerprint: str, extra: dict) -> str:
    h = hashlib.sha256()
    h.update(json.dumps({"sh": source_hash, "edl": chunk_edl,
                         "ff": ffmpeg_v, "fp": fingerprint,
                         "x": extra}, sort_keys=True).encode())
    return h.hexdigest()[:16]


def _face_boxes_at_factory(mode: str, curve, src_w: int, src_h: int,
                           canvas: Canvas, face_track: Optional[dict]):
    """Kembalikan fn(t) -> kotak wajah dalam piksel kanvas (utk hindari teks)."""
    W, H = canvas.width, canvas.height

    def fn(t: float) -> list[tuple]:
        if not face_track:
            return []
        samples = face_track.get("samples", [])
        best, bd = None, 1e9
        for s in samples:
            d = abs(s["t"] - t)
            if d < bd:
                best, bd = s, d
        if best is None or bd > 1.0 or not best["faces"]:
            return []
        boxes = []
        for f in best["faces"]:
            fx, fy = f["x"] * src_w, f["y"] * src_h
            fw, fh = f["w"] * src_w, f["h"] * src_h
            if mode == "smart_crop" and curve:
                from .qa import _curve_center_at
                cx, cy = _curve_center_at(curve, t)
                cw, ch = curve["crop_w"], curve["crop_h"]
                ox = (fx - (cx - cw / 2)) * (W / cw)
                oy = (fy - (cy - ch / 2)) * (H / ch)
                ow, oh = fw * (W / cw), fh * (H / ch)
            elif mode in ("blur_fill", "fit_letterbox", "none"):
                sc = min(W / src_w, H / src_h)
                ox = fx * sc + (W - src_w * sc) / 2
                oy = fy * sc + (H - src_h * sc) / 2
                ow, oh = fw * sc, fh * sc
            else:
                continue
            boxes.append((ox, oy, ow, oh))
        return boxes

    return fn


def render_edl(
    edl_path: str | Path,
    source: str | Path,
    output: Optional[str | Path] = None,
    words: Optional[list[dict]] = None,
    config: Optional[dict] = None,
    work_root: Optional[str | Path] = None,
    catalog_dir: Optional[str | Path] = None,
    assets_dir: Optional[str | Path] = None,
    model_dir: Optional[str | Path] = None,
    on_progress: Optional[Callable[[float], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> dict:
    """Render EDL -> video + QA. Kembalikan {"output", "qa", "work_dir"}."""
    source = Path(source)
    edl = Edl.model_validate(json.loads(Path(edl_path).read_text()))

    if config is None:
        config = yaml.safe_load(
            resource_path("config.yaml").read_text(encoding="utf-8"))
    if work_root is None:
        work_root = app_dirs()["work"]
    work_root = Path(work_root)
    if catalog_dir is None:
        catalog_dir = resource_path("catalog")
    if assets_dir is None:
        assets_dir = resource_path("assets")
    assets_dir = Path(assets_dir)

    info = probe(source)
    aspect = edl.canvas.aspect
    if aspect == "auto":
        aspect = resolve_aspect("auto", info.aspect_ratio())
    canvas = Canvas.from_aspect(aspect)

    vdir = _video_dir(work_root, source)
    cdir = vdir / "chunks"
    cdir.mkdir(parents=True, exist_ok=True)

    registry = EffectRegistry(catalog_dir, assets_dir).load()
    fingerprint = registry.fingerprint()
    ffmpeg_v = _ffmpeg_version()

    # -- kata (satu sumber kebenaran timing) --------------------------------
    if words is None:
        from .transcribe import transcribe
        r = transcribe(source, work_root, config["transcribe"],
                       model_dir=Path(model_dir) if model_dir else None)
        words = json.loads((r["video_dir"] / "words.json").read_text())
        source_hash = r["meta"]["key"]["source_hash"]
    else:
        from .transcribe import _hash_source
        source_hash = _hash_source(source)

    # -- face track (sumber kebenaran posisi wajah) --------------------------
    yunet = assets_dir / "models" / "face_detection_yunet_2023mar.onnx"
    face_track = ensure_face_track(
        source, vdir, config.get("reframe", {}),
        yunet if yunet.is_file() else None, info)
    has_faces = face_track.get("n_faces_total", 0) > 0

    # -- mode reframe (termasuk aturan cadangan 'auto') -----------------------
    mode = edl.canvas.reframe.mode
    if mode == "auto":
        mode = _auto_reframe(info, canvas, face_track)
        log.info("reframe auto -> %s", mode)
    curve = None
    if mode == "smart_crop":
        if not has_faces:
            log.warning("smart_crop tanpa wajah terdeteksi -> blur_fill")
            mode = "blur_fill"
        else:
            curve = smart_crop_curve(
                face_track, info.width, info.height,
                canvas.width, canvas.height,
                config.get("reframe", {}), info.duration)
            if curve is None:
                log.warning("smart_crop: wajah terlalu lebar -> blur_fill")
                mode = "blur_fill"
            else:
                (vdir / "smart_crop_curve.json").write_text(
                    json.dumps({"points": curve["points"],
                                "crop_w": curve["crop_w"],
                                "crop_h": curve["crop_h"],
                                "axis": curve["axis"]}))
                log.info("smart_crop: %d titik kurva, sumbu %s",
                         len(curve["points"]), curve["axis"])
    if info.width < 700:
        log.warning("sumber beresolusi rendah (%dx%d): hasil akan lembut",
                    info.width, info.height)

    # -- partisi & render chunk ----------------------------------------------
    chunks = _partition(info.duration, sorted(edl.segments,
                                              key=lambda s: s.start))
    manifest_p = vdir / "render_manifest.json"
    manifest = (json.loads(manifest_p.read_text(encoding="utf-8"))
                if manifest_p.is_file() else {"chunks": {}})
    chunk_files: list[Path] = []
    total_chunks = len(chunks)

    for idx, (s0, s1, seg) in enumerate(chunks):
        cid = f"chunk_{idx:03d}"
        chunk_edl = {
            "seg": seg.model_dump(mode="json") if seg else None,
            "global": edl.global_.model_dump(mode="json"),
            "canvas": {"aspect": aspect, "reframe": mode},
        }
        want_hash = _chunk_hash(source_hash, chunk_edl, ffmpeg_v,
                                fingerprint,
                                {"crf": CHUNK_CRF, "seg": [s0, s1]})
        got = manifest.get("chunks", {}).get(cid)
        cfile = cdir / f"{cid}.mp4"
        if (got and got.get("hash") == want_hash and cfile.is_file()
                and not (cancel_event and cancel_event.is_set())):
            log.info("[%d/%d] %s: pakai ulang", idx + 1, total_chunks, cid)
            chunk_files.append(cfile)
            continue
        if cancel_event and cancel_event.is_set():
            raise CancelledError("render dibatalkan")
        log.info("[%d/%d] %s: render %.2f-%.2fs", idx + 1, total_chunks,
                 cid, s0, s1)
        ctx = EffectContext(
            canvas=canvas, source=info, words=words, work_dir=cdir,
            assets_dir=assets_dir, config=config, face_track=face_track,
            seg_start=s0, seg_end=s1, smart_crop_curve=curve)
        _render_chunk(source, info, canvas, mode, registry, ctx, edl,
                      seg, s0, s1, cfile, config, cancel_event)
        manifest.setdefault("chunks", {})[cid] = {
            "hash": want_hash, "file": cfile.name}
        manifest_p.write_text(json.dumps(manifest, indent=2))
        chunk_files.append(cfile)
        if on_progress:
            on_progress(s1)  # kasar: progres per chunk

    # -- gabung + pass akhir --------------------------------------------------
    if output is None:
        outdir = app_dirs()["output"]
        outdir.mkdir(parents=True, exist_ok=True)
        output = outdir / (f"{source.stem}_edited_"
                           f"{aspect.replace(':', 'x')}.mp4")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    # kumpulkan ASS dari efek teks (global)
    ass_events: list[dict] = []
    if edl.global_.text_style:
        t = edl.global_.text_style
        ctx0 = EffectContext(canvas=canvas, source=info, words=words,
                             work_dir=vdir, assets_dir=assets_dir,
                             config=config, face_track=face_track)
        ass_events.extend(registry.build(t.id, ctx0, None, t.params)
                          .ass_events)
    for s in edl.segments:  # (cadangan: efek teks per segmen)
        for e in s.effects:
            try:
                if registry.get(e.id).meta.category == "text":
                    ctx0 = EffectContext(
                        canvas=canvas, source=info, words=words,
                        work_dir=vdir, assets_dir=assets_dir, config=config,
                        face_track=face_track,
                        seg_start=s.start, seg_end=s.end)
                    ass_events.extend(
                        registry.build(e.id, ctx0, e.at, e.params).ass_events)
            except KeyError:
                pass

    ass_path = None
    if ass_events:
        face_fn = _face_boxes_at_factory(
            mode, curve, info.width, info.height, canvas, face_track)
        ass_text = build_ass(ass_events, canvas, config,
                             assets_dir / "fonts", face_fn)
        ass_path = vdir / "subs.ass"
        ass_path.write_text(ass_text, encoding="utf-8")
        if config["output"].get("export_srt"):
            write_srt(ass_events, output.with_suffix(".srt"))

    # -- SFX (Tahap 7) ------------------------------------------------------
    from .sfx import build_sfx_track, collect_cues
    sfx_cfg = config.get("sfx", {})
    density = (config.get("density", {}) or {}).get(
        (edl.global_.intensity or "medium").lower(), {})
    sfx_on = bool(sfx_cfg.get("enabled", True)) and bool(
        density.get("sfx", True))
    sfx_cues: list[dict] = []
    sfx_track = None
    sfx_volume = 0.4
    if sfx_on and info.has_audio:
        sfx_cues = collect_cues(edl, registry, words)
        sfx_volume = float(density.get("sfx_volume",
                                       sfx_cfg.get("volume", 0.4)))
        if sfx_cues:
            sfx_track = build_sfx_track(
                sfx_cues, info.duration, assets_dir / "sfx",
                vdir / "sfx_track.wav", volume=sfx_volume,
                cancel_event=cancel_event)
            log.info("%d cue SFX -> %s", len(sfx_cues), sfx_track)

    _final_pass(chunk_files, source, info, output, ass_path, assets_dir,
                config, cancel_event,
                sfx_track=sfx_track, sfx_volume=sfx_volume)

    # -- QA -------------------------------------------------------------------
    q = QACtx(output=output, source=source, source_info=info, canvas=canvas,
              config={**config, "fonts_dir": str(assets_dir / "fonts")},
              edl=edl, registry=registry, face_track=face_track,
              smart_crop_curve=curve, ass_path=ass_path, sfx_cues=sfx_cues)
    q.sfx_track = sfx_track  # trek SFX mentah (untuk ukur level, Tahap 7)
    report = run_qa(q, vdir)
    return {"output": output, "qa": report, "work_dir": vdir,
            "reframe_mode": mode}


def _auto_reframe(info: SourceInfo, canvas: Canvas,
                  face_track: Optional[dict]) -> str:
    """Aturan cadangan bila Gemini gagal / mode 'auto' (Bagian 0)."""
    src_ar = info.width / info.height
    tgt_ar = canvas.width / canvas.height
    if abs(src_ar - tgt_ar) / tgt_ar <= 0.03:
        return "none"
    samples = (face_track or {}).get("samples", [])
    faces_now = [f for s in samples[:8] for f in s["faces"]]
    if not faces_now:
        return "blur_fill"  # wajah tidak terdeteksi
    # gabungan kotak > 85% lebar crop -> blur_fill
    xs = [f["x"] for f in faces_now]
    xe = [f["x"] + f["w"] for f in faces_now]
    combined = max(xe) - min(xs)
    # perkiraan lebar crop relatif: min(1, tgt_ar/src_ar)
    rel_crop_w = min(1.0, tgt_ar / src_ar)
    if len(faces_now) >= 2 and combined > 0.85 * rel_crop_w:
        return "blur_fill"
    return "smart_crop"


def _render_chunk(source: Path, info: SourceInfo, canvas: Canvas, mode: str,
                  registry: EffectRegistry, ctx: EffectContext, edl: Edl,
                  seg, s0: float, s1: float, cfile: Path, config: dict,
                  cancel_event) -> None:
    """Render satu chunk video (tanpa audio).

    Kontrak filter efek:
    - reframe (selalu pertama): string berlabel penuh [vbase] -> [vref].
    - efek lain: tiap string boleh memakai placeholder [CUR] (label video
      saat ini) dan [NEXT] (label keluaran); bila tak ada label sama
      sekali, dibungkus otomatis [cur]...[nxt].
    - [INPUTi] merujuk ke extra_inputs efek itu (indeks lokal).
    """
    W, H = canvas.width, canvas.height

    # Kumpulkan semua build dulu (dibutuhkan untuk needs_source & inputs).
    built: list[EffectOutput] = []
    if mode == "none":
        if (info.width, info.height) == (W, H):
            built.append(_out("[vbase]null[vref]"))
        else:
            built.append(_out(
                f"[vbase]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H}[vref]"))
    else:
        out = registry.build(f"reframe.{mode}", ctx, None, {})
        assert len(out.video_filters) == 1 and \
            "[vbase]" in out.video_filters[0], \
            f"kontrak reframe dilanggar: {mode}"
        built.append(out)
    if edl.global_.grade:
        g = edl.global_.grade
        built.append(registry.build(g.id, ctx, None, g.params))
    if seg:
        for e in sorted(seg.effects, key=lambda x: x.at or 0.0):
            at = None if e.at is None else e.at - s0
            built.append(registry.build(e.id, ctx, at, e.params))

    # Bila ada efek butuh sumber mentah: split [0:v] dulu.
    needy = [o for o in built if o.needs_source]
    if needy:
        vsrc_labels = "".join(f"[vsrc{i}]" for i in range(len(needy)))
        segs = [f"[0:v]split={1 + len(needy)}[vin]{vsrc_labels};",
                f"[vin]trim=start={s0:.3f}:end={s1:.3f},"
                f"setpts=PTS-STARTPTS,fps=30,setsar=1,format=yuv420p"]
    else:
        segs = [f"[0:v]trim=start={s0:.3f}:end={s1:.3f},setpts=PTS-STARTPTS,"
                f"fps=30,setsar=1,format=yuv420p"]
    # Catatan: rotasi metadata ditangani autorotate bawaan ffmpeg
    # (default aktif) -> frame yang masuk filter SUDAH terotasi benar,
    # konsisten dengan app.probe. Jangan tambah transpose manual.
    segs[1 if needy else 0] += "[vbase];"

    # Indeks input global.
    input_files: list[str] = []
    for out in built:
        for p in out.extra_inputs:
            if p not in input_files:
                input_files.append(p)
    base_of: list[int] = []  # offset input global per efek
    off = 0
    for out in built:
        base_of.append(off)
        off += len(out.extra_inputs)

    # Rangkai filter.
    cur = "vref"
    counter = 0
    needy_idx = 0
    for out, base in zip(built, base_of):
        # [VSRC] -> label salinan sumber milik efek ini
        vsrc_label = None
        if out.needs_source:
            vsrc_label = f"[vsrc{needy_idx}]"
            needy_idx += 1
        for f in out.video_filters:
            # [INPUTi] lokal -> [N:v] global
            def _repl(m, _base=base):
                return f"[{_base + 1 + int(m.group(1))}:v]"
            f = re.sub(r"\[INPUT(\d+)\]", _repl, f)
            if vsrc_label:
                f = f.replace("[VSRC]", vsrc_label)
            if "[CUR]" in f or "[NEXT]" in f:
                nxt = f"n{counter}"
                counter += 1
                if "[CUR]" not in f:
                    # efek tak pakai input: konsumsi label lama agar
                    # tak menggantung (error binding filtergraph)
                    segs.append(f"[{cur}]nullsink;")
                f = f.replace("[CUR]", f"[{cur}]").replace("[NEXT]",
                                                           f"[{nxt}]")
                segs.append(f + ";")
                cur = nxt
            elif "[" in f:
                segs.append(f + ";")  # sudah berlabel penuh (reframe)
            else:
                nxt = f"n{counter}"
                counter += 1
                segs.append(f"[{cur}]{f}[{nxt}];")
                cur = nxt
    segs.append(f"[{cur}]null[vout]")

    fg = ctx.work_dir / f"chunk_{s0:.2f}.txt"
    fg.write_text("\n".join(segs), encoding="utf-8")
    args = ["-i", str(source)]
    for p in input_files:
        args += ["-i", p]
    args += ["-filter_complex_script", str(fg),
             "-map", "[vout]", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", str(CHUNK_CRF), "-pix_fmt", "yuv420p",
             "-r", "30", "-g", "30", "-an", str(cfile)]
    run_ffmpeg(args, cancel_event=cancel_event, cwd=ctx.work_dir)


def _out(filt: str) -> EffectOutput:
    """EffectOutput satu filter (untuk reframe 'none' internal)."""
    return EffectOutput(video_filters=[filt])


def _final_pass(chunk_files: list[Path], source: Path, info: SourceInfo,
                output: Path, ass_path: Optional[Path], assets_dir: Path,
                config: dict, cancel_event,
                sfx_track: Optional[Path] = None,
                sfx_volume: float = 0.4) -> None:
    """Gabung chunk (concat demuxer) + bakar ASS + audio -> output.

    Bila sfx_track diberikan: campur audio asli + SFX dengan ducking
    (sidechaincompress; ucapan = kunci), lalu amix normalize=0.
    """
    from .sfx import ducking_filter
    workdir = output.parent
    lst = workdir / "concat_list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in chunk_files),
                   encoding="utf-8")
    out_cfg = config["output"]
    enc = out_cfg.get("encoder", "libx264")

    args = ["-f", "concat", "-safe", "0", "-i", str(lst),
            "-i", str(source)]
    use_sfx = bool(sfx_track and info.has_audio)
    if use_sfx:
        args += ["-i", str(sfx_track)]

    vfilter = None
    if ass_path:
        fontsdir = assets_dir / "fonts"
        vfilter = (f"[0:v]ass='{ff_filter_path(ass_path)}':"
                   f"fontsdir='{ff_filter_path(fontsdir)}'[vout]")
    afilter = ducking_filter(sfx_volume) if use_sfx else None
    if vfilter or afilter:
        fc = ";".join(f for f in (vfilter, afilter) if f)
        args += ["-filter_complex", fc]
    args += ["-map", "[vout]" if vfilter else "0:v"]
    if info.has_audio:
        args += ["-map", "[aout]" if use_sfx else "1:a"]
        # Dengan SFX audio harus di-encode ulang; tanpa SFX copy bila AAC.
        if use_sfx:
            args += ["-c:a", "aac", "-b:a", "192k"]
        else:
            args += ["-c:a", "copy"] if info.audio_codec == "aac" \
                else ["-c:a", "aac", "-b:a", "192k"]
    else:
        args += ["-an"]

    def build_args(encoder: str) -> list[str]:
        a = list(args)
        if ass_path:
            a += ["-c:v", encoder, "-preset",
                  out_cfg.get("preset", "veryfast"),
                  "-crf", str(out_cfg.get("crf", FINAL_CRF_FALLBACK)),
                  "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                  "-r", "30"]
        else:
            a += ["-c:v", "copy"]
        a.append(str(output))
        return a

    try:
        run_ffmpeg(build_args(enc), cancel_event=cancel_event, cwd=workdir)
    except subprocess.CalledProcessError:
        if enc != "libx264":
            log.warning("encoder %s gagal, coba libx264", enc)
            run_ffmpeg(build_args("libx264"), cancel_event=cancel_event,
                       cwd=workdir)
        else:
            raise
    log.info("render selesai: %s", output)
