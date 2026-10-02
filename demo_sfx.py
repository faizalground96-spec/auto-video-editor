"""Uji nyata Tahap 7: render video santai + SFX, ukur level."""
import json
import sys
import yaml
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from app.render import render_edl

CFG = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
SRC = (Path.home() / "workspace/user/media_library/video/ee/"
       "ee1f6b6fba2efcdbbae5061da1d1c9ed9493db8b6af66b91ede2477b90636252.mp4")

edl = {
    "schema_version": 2,
    "canvas": {"aspect": "9:16", "reframe": {"mode": "none"}},
    "global": {
        "intensity": "medium",
        "text_style": {"id": "text.pop_in_word", "params": {}},
        "grade": {"id": "grade.cinematic", "params": {}},
    },
    "segments": [{
        "start": 0.0, "end": 23.0, "role": "main_content",
        "why": "uji SFX",
        "effects": [
            {"id": "camera.punch_in", "at": 5.0, "params": {}},
            {"id": "transition.whip", "at": 10.0, "params": {}},
            {"id": "overlay.emoji_burst", "at": 15.0, "params": {}},
        ],
    }],
}
work = BASE / "work_tahap7"
edl_p = work / "edl_sfx.json"
work.mkdir(parents=True, exist_ok=True)
edl_p.write_text(json.dumps(edl), encoding="utf-8")
out = BASE / "output" / "santai_sfx.mp4"

res = render_edl(edl_p, SRC, out, words=[],
                 config=CFG, work_root=work / "render",
                 catalog_dir=BASE / "catalog", assets_dir=BASE / "assets",
                 model_dir=BASE / "assets" / "models")
qa = res["qa"]
print("QA passed:", qa["passed"])
for c in qa["checks"]:
    if "audio" in c["name"] or "sfx" in c["name"]:
        print(f"  {c['name']}: {c['status']} — {c['detail']}")
        if c.get("metrics"):
            print(f"    metrics: {c['metrics']}")
print("output:", out, out.stat().st_size, "byte")
