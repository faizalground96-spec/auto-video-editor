"""Matriks orientasi Tahap 4 (wajib): render tiap kombinasi sumber->target,
kumpulkan qa_report.json + contact_sheet.jpg per kombinasi ke work/matrix/.
Jalankan: .venv/bin/python tools/run_matrix.py
"""
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import yaml  # noqa: E402
from app.render import render_edl  # noqa: E402
from app.utils import resource_path  # noqa: E402

ROOT = resource_path(".")
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
SAMPLES = Path("/tmp/samples")
CERAMAH = Path.home() / ("workspace/user/media_library/video/0f/"
                         "0f89567aebce545bce6536c55c4ce3709be28d676fc86a5aa7770f61d8889a46.mp4")

COMBOS = [
    # (nama, sumber, aspek target, mode reframe)
    ("01_vert-ke-vert", SAMPLES / "vertical.mp4", "9:16", "none"),
    ("02_horiz-ke-horiz", SAMPLES / "horizontal.mp4", "16:9", "none"),
    ("03_horiz-ke-vert_smartcrop", SAMPLES / "horizontal.mp4", "9:16",
     "smart_crop"),   # tanpa wajah -> diharapkan fallback blur_fill
    ("04_horiz-ke-vert_blurfill", SAMPLES / "horizontal.mp4", "9:16",
     "blur_fill"),
    ("05_vert-ke-horiz_blurfill", SAMPLES / "vertical.mp4", "16:9",
     "blur_fill"),
    ("06_horiz-ke-1x1_smartcrop", SAMPLES / "horizontal.mp4", "1:1",
     "smart_crop"),   # tanpa wajah -> diharapkan fallback blur_fill
    ("07_horiz-ke-4x5_smartcrop", SAMPLES / "horizontal.mp4", "4:5",
     "smart_crop"),   # tanpa wajah -> diharapkan fallback blur_fill
    ("08_rotated-ke-vert", SAMPLES / "rotated.mp4", "9:16", "none"),
    ("09_vfr-ke-vert", SAMPLES / "vfr.mp4", "9:16", "none"),
    ("10_ceramah-ke-1x1_smartcrop", CERAMAH, "1:1", "smart_crop"),
]


def main():
    matrix_dir = ROOT / "work" / "matrix"
    matrix_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for name, src, aspect, mode in COMBOS:
        assert src.is_file(), f"sumber hilang: {src}"
        edl = {
            "schema_version": 1,
            "canvas": {"aspect": aspect,
                       "reframe": {"mode": mode,
                                   "why": f"matriks Tahap 4 {name}"}},
            "global": {"intensity": "medium"},
            "segments": [],
        }
        edl_p = matrix_dir / f"{name}.edl.json"
        edl_p.write_text(json.dumps(edl, indent=1), encoding="utf-8")
        t0 = time.time()
        res = render_edl(edl_p, src, None, words=[], config=CFG,
                         work_root=ROOT / "work",
                         catalog_dir=ROOT / "catalog",
                         assets_dir=ROOT / "assets",
                         model_dir=ROOT / "models")
        dt = time.time() - t0
        out = res["output"]
        dest = matrix_dir / name
        dest.mkdir(exist_ok=True)
        shutil.copy(out, dest / out.name)
        shutil.copy(res["work_dir"] / "qa_report.json",
                    dest / "qa_report.json")
        shutil.copy(res["work_dir"] / "contact_sheet.jpg",
                    dest / "contact_sheet.jpg")
        qa = res["qa"]
        failed = qa["failed"]
        summary.append({
            "combo": name, "reframe_aktual": res["reframe_mode"],
            "qa": "LULUS" if qa["passed"] else f"GAGAL {failed}",
            "waktu_s": round(dt, 1),
            "ukuran_kb": round(out.stat().st_size / 1024),
        })
        print(f"{name}: reframe={res['reframe_mode']} "
              f"qa={'LULUS' if qa['passed'] else 'GAGAL '+str(failed)} "
              f"{dt:.1f}s", flush=True)
    (matrix_dir / "ringkasan.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n=== RINGKASAN ===")
    for s in summary:
        print(f"{s['combo']:32s} {s['reframe_aktual']:10s} "
              f"{s['qa']:20s} {s['waktu_s']:>6}s {s['ukuran_kb']:>7}KB")


if __name__ == "__main__":
    main()
