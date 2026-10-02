"""cli.py — titik masuk command-line (Tahap 9).

Contoh:
  python -m app.cli input.mp4 --mode auto
  python -m app.cli input.mp4 --preset clean_podcast
  python -m app.cli input.mp4 --mode auto --disable text.pop_in_word,camera.punch_in
  python -m app.cli input.mp4 --dry-run --fake-llm tests/fixtures/gemini_bagus.json
  python -m app.cli input.mp4 --from-edl work/edl.json
  python -m app.cli --self-test
  python -m app.cli --list-catalog
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from app.pipeline import Pipeline, PipelineOptions  # noqa: E402
from app.presets import list_presets  # noqa: E402
from app.registry import EffectRegistry  # noqa: E402
from app.utils import resource_path, sanitize_proxy_env  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("auto_video_editor.cli")


def cmd_list_catalog(args) -> int:
    reg = EffectRegistry(resource_path("catalog"),
                         resource_path("assets")).load()
    print(f"{'ID':32} {'STATUS':12} {'ASPEK':22} CATATAN")
    print("-" * 90)
    for eid in reg.all_ids():
        m = reg.entries[eid].meta
        print(f"{eid:32} {m.status:12} {','.join(m.aspects):22} "
              f"{m.description[:40]}")
    if reg.errors:
        print("\nDilewati (tidak menjatuhkan aplikasi):")
        for fp, msg in reg.errors:
            print(f"  {fp.name}: {msg}")
    print(f"\n{len(reg.entries)} efek, {len(reg.errors)} dilewati, "
          f"fingerprint={reg.fingerprint()}")
    print("Preset:", ", ".join(list_presets()) or "-")
    return 0


def cmd_self_test(args) -> int:
    """Cek lingkungan: registry, FFmpeg, libass, font, model wajah,
    render 2 dtk sintetis + teks ASS. Tanpa API key / Whisper."""
    from app.utils import find_ffmpeg
    ok = True

    def cek(nama: str, lulus: bool, detail: str = ""):
        nonlocal ok
        print(f"[{'OK' if lulus else 'GAGAL'}] {nama}"
              + (f" — {detail}" if detail else ""))
        ok = ok and lulus

    # 1. registry
    try:
        reg = EffectRegistry(resource_path("catalog"),
                             resource_path("assets")).load()
        cek("registry", len(reg.entries) >= 20,
            f"{len(reg.entries)} efek")
    except Exception as e:  # noqa: BLE001
        cek("registry", False, str(e)[:80])

    # 2. ffmpeg
    try:
        ff = find_ffmpeg()
        cek("ffmpeg", True, str(ff))
    except Exception as e:  # noqa: BLE001
        cek("ffmpeg", False, str(e)[:80]); return 1

    # 3. libass (filter ass ada di ffmpeg)
    import subprocess
    r = subprocess.run([str(ff), "-hide_banner", "-h", "filter=ass"],
                       capture_output=True, text=True)
    cek("libass", r.returncode == 0)

    # 4. font
    cek("font Montserrat",
        (resource_path("assets/fonts/Montserrat.ttf")).is_file())

    # 5. model wajah
    cek("model YuNet",
        (resource_path("assets/models/face_detection_yunet_2023mar.onnx"))
        .is_file())

    # 6. render 2 dtk sintetis + ASS
    try:
        import tempfile
        from app.render import render_edl
        tmp = Path(tempfile.mkdtemp(prefix="selftest_"))
        src = tmp / "src.mp4"
        subprocess.run(
            [str(ff), "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc=size=540x960:rate=30:duration=2",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset",
             "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
             str(src)], check=True)
        import json as _json
        edl = {"schema_version": 2,
               "canvas": {"aspect": "9:16",
                          "reframe": {"mode": "none"}},
               "global": {"intensity": "medium",
                          "text_style": {"id": "text.clean_caption",
                                         "params": {}},
                          "grade": {"id": "grade.clean_bright",
                                    "params": {}}},
               "segments": [{"start": 0.0, "end": 2.0, "role": "main",
                             "why": "self-test",
                             "effects": [{"id": "camera.punch_in", "at": 0.5,
                                          "params": {}}]}]}
        edl_p = tmp / "edl.json"
        edl_p.write_text(_json.dumps(edl), encoding="utf-8")
        out = tmp / "out.mp4"
        words = [{"i": 0, "word": " halo", "start": 0.2, "end": 0.6,
                  "prob": 0.99},
                 {"i": 1, "word": " dunia", "start": 0.7, "end": 1.1,
                  "prob": 0.99}]
        config = yaml.safe_load(
            (resource_path("config.yaml")).read_text(encoding="utf-8"))
        res = render_edl(edl_p, src, out, words=words, config=config,
                         work_root=tmp / "work",
                         catalog_dir=resource_path("catalog"),
                         assets_dir=resource_path("assets"),
                         model_dir=resource_path("assets/models"))
        cek("render sintetis + ASS + QA",
            out.is_file() and res["qa"]["passed"])
    except Exception as e:  # noqa: BLE001
        cek("render sintetis + ASS + QA", False, str(e)[:100])

    print("\nSELF-TEST:", "LULUS" if ok else "GAGAL")
    return 0 if ok else 1


def cmd_run(args) -> int:
    config = yaml.safe_load(
        (resource_path("config.yaml")).read_text(encoding="utf-8"))
    if args.mode == "preset" and not args.preset:
        print("ERROR: --mode preset butuh --preset NAMA", file=sys.stderr)
        return 2
    opt = PipelineOptions(
        input=Path(args.input),
        out=Path(args.out) if args.out else None,
        aspect=args.aspect, reframe=args.reframe, mode=args.mode,
        preset=args.preset,
        disable=[d.strip() for d in (args.disable or "").split(",")
                 if d.strip()],
        intensity=args.intensity, user_notes=args.user_notes or "",
        lang=None if args.lang == "auto" else args.lang,
        no_sfx=args.no_sfx, dry_run=args.dry_run,
        from_edl=Path(args.from_edl) if args.from_edl else None,
        preview=args.preview, force_reanalyze=args.force_reanalyze,
        fake_llm=Path(args.fake_llm) if args.fake_llm else None,
        seed=args.seed,
        work_dir=Path(args.work_dir) if args.work_dir else None,
    )
    pipe = Pipeline(config,
                    on_progress=lambda s, f: print(f"  [{s}] {f*100:.0f}%",
                                                   flush=True),
                    on_log=print)
    try:
        res = pipe.run(opt)
    except InterruptedError:
        print("Dibatalkan.", file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001
        print(f"GALAT: {e}", file=sys.stderr)
        return 1
    if res.get("dry_run"):
        print("dry-run selesai:")
        print("  EDL:", res["edl"])
        print("  Why:", res["why"])
    else:
        print("SELESAI:", res["output"])
        qa = res["qa"]
        print("QA:", "LULUS" if qa["passed"] else "GAGAL")
        for n, c in qa["checks"].items():
            if c["status"] != "pass":
                print(f"  {n}: {c['status']} — {c['detail']}")
    return 0


def main(argv=None) -> int:
    sanitize_proxy_env()
    ap = argparse.ArgumentParser(prog="auto-video-editor",
                                 description="Auto Video Editor (CLI)")
    ap.add_argument("--list-catalog", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("input", nargs="?", help="video sumber")
    ap.add_argument("--from-edl", metavar="EDL")
    ap.add_argument("--out", metavar="OUT")
    ap.add_argument("--work-dir", metavar="DIR")
    ap.add_argument("--mode", default="auto",
                    choices=["auto", "preset"],
                    help="mode paket gaya")
    ap.add_argument("--preset", metavar="NAMA",
                    help=f"paket gaya ({', '.join(list_presets())})")
    ap.add_argument("--disable", metavar="ID,ID",
                    help="matikan efek (mode auto+kunci)")
    ap.add_argument("--aspect", default="9:16",
                    choices=["auto", "9:16", "16:9", "1:1", "4:5"])
    ap.add_argument("--reframe", default="auto",
                    choices=["auto", "smart_crop", "blur_fill",
                             "letterbox", "none"])
    ap.add_argument("--intensity", default=None,
                    choices=["calm", "medium", "aggressive"],
                    help="paksa intensitas (default: Gemini/preset)")
    ap.add_argument("--user-notes", default="",
                    help="arahan untuk Gemini")
    ap.add_argument("--lang", default="auto",
                    help="bahasa ucapan (auto/id/en/...)")
    ap.add_argument("--no-sfx", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="hanya analisis -> edl.json + edl_why.txt")
    ap.add_argument("--preview", type=float, metavar="DETIK",
                    help="render draft N detik pertama")
    ap.add_argument("--force-reanalyze", action="store_true")
    ap.add_argument("--fake-llm", metavar="JSON",
                    help="pakai fixture offline (uji)")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)

    if args.list_catalog:
        return cmd_list_catalog(args)
    if args.self_test:
        return cmd_self_test(args)
    if not args.input:
        ap.print_help()
        return 2
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
