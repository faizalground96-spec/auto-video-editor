"""cli.py — titik masuk command-line.

Tahap 3 (minimal): --list-catalog dan render dari EDL tulisan tangan.
Diperluas di Tahap 9 (mode, preset, dry-run, preview, self-test, dll).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.registry import EffectRegistry  # noqa: E402
from app.utils import app_dirs, resource_path, sanitize_proxy_env  # noqa: E402


def cmd_list_catalog(args) -> int:
    reg = EffectRegistry(resource_path("catalog"),
                         resource_path("assets")).load()
    print(f"{'ID':32} {'STATUS':12} {'ASPEK':22} CATATAN")
    print("-" * 90)
    for eid in reg.all_ids():
        m = reg.entries[eid].meta
        print(f"{eid:32} {m.status:12} {','.join(m.aspects):22} {m.description[:40]}")
    if reg.errors:
        print("\nDilewati (tidak menjatuhkan aplikasi):")
        for fp, msg in reg.errors:
            print(f"  {fp.name}: {msg}")
    print(f"\n{len(reg.entries)} efek, {len(reg.errors)} dilewati, "
          f"fingerprint={reg.fingerprint()}")
    return 0


def cmd_render(args) -> int:
    from app.render import render_edl
    import yaml
    config = yaml.safe_load(
        (resource_path("config.yaml")).read_text(encoding="utf-8"))
    dirs = app_dirs()
    out = Path(args.out) if args.out else (
        dirs["output"] / f"{Path(args.input).stem}_edited.mp4")
    render_edl(args.from_edl, args.input, out, config=config,
               work_root=dirs["work"],
               assets_dir=resource_path("assets"),
               model_dir=dirs["base"] / "models")
    print("OK:", out)
    return 0


def main(argv=None) -> int:
    sanitize_proxy_env()
    ap = argparse.ArgumentParser(prog="auto-video-editor",
                                 description="Auto Video Editor (CLI)")
    ap.add_argument("--list-catalog", action="store_true",
                    help="tampilkan katalog efek")
    ap.add_argument("input", nargs="?", help="video sumber")
    ap.add_argument("--from-edl", metavar="EDL",
                    help="render dari file EDL (tanpa Gemini)")
    ap.add_argument("--out", metavar="OUT", help="path video hasil")
    ap.add_argument("--work-dir", metavar="DIR", help="folder work")
    args = ap.parse_args(argv)

    if args.list_catalog:
        return cmd_list_catalog(args)
    if args.from_edl:
        if not args.input:
            ap.error("--from-edl butuh INPUT video")
        return cmd_render(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
