"""Demo Tahap 5 di video flying fox (energetic vlog).
Transkrip Whisper dilewati (unduhan model gagal 2x via proxy);
caption kinetik tak dipakai agar tak menduplikasi teks bakar bawaan video.
Fokus: kamera, grade, overlay, transisi Tahap 5.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yaml
from app.render import render_edl
from app.utils import resource_path

BASE = Path(__file__).resolve().parent
SRC = (Path.home() / "workspace/user/media_library/video/47/"
       "472b5211fe9d7d10d8ad64c47a63f6d1362d0fa2f650da4c1ef7d76f257b372e.mp4")

EDL = {
    "schema_version": 1,
    "canvas": {"aspect": "9:16", "reframe": {"mode": "none"}},
    "global": {
        "intensity": "high",
        "grade": {"id": "grade.warm_pop", "params": {"strength": 0.8}},
    },
    "segments": [
        {"start": 0.0, "end": 9.0, "role": "hook", "effects": [
            {"id": "camera.slow_zoom", "at": None,
             "params": {"factor": 1.15}},
            {"id": "overlay.progress_bar", "at": None,
             "params": {"color": "yellow", "thickness": 0.008}},
        ]},
        {"start": 9.0, "end": 20.0, "role": "isi", "effects": [
            {"id": "transition.whip", "at": 9.0,
             "params": {"direction": "in", "duration": 0.3, "way": "left"}},
            {"id": "camera.whip_pan", "at": 11.0,
             "params": {"direction": "right", "duration": 0.4}},
            {"id": "overlay.emoji_burst", "at": 13.5,
             "params": {"sticker": "burst", "pos": "top_right",
                        "scale": 0.25, "duration": 1.0}},
        ]},
        {"start": 20.0, "end": 28.0, "role": "isi", "effects": [
            {"id": "transition.whip", "at": 20.0,
             "params": {"direction": "in", "duration": 0.3, "way": "right"}},
            {"id": "overlay.emoji_burst", "at": 21.5,
             "params": {"sticker": "alert", "pos": "top_left",
                        "scale": 0.22, "duration": 0.9}},
        ]},
        {"start": 28.0, "end": 43.0, "role": "isi", "effects": [
            {"id": "transition.whip", "at": 28.0,
             "params": {"direction": "in", "duration": 0.3, "way": "left"}},
            {"id": "camera.slow_zoom", "at": None,
             "params": {"factor": 1.1}},
        ]},
        {"start": 43.0, "end": 60.0, "role": "isi", "effects": [
            {"id": "transition.whip", "at": 43.0,
             "params": {"direction": "in", "duration": 0.3, "way": "right"}},
            {"id": "overlay.emoji_burst", "at": 46.0,
             "params": {"sticker": "burst", "pos": "center",
                        "scale": 0.28, "duration": 1.0}},
            {"id": "camera.whip_pan", "at": 52.0,
             "params": {"direction": "left", "duration": 0.4}},
        ]},
        {"start": 60.0, "end": 80.0, "role": "isi", "effects": [
            {"id": "transition.whip", "at": 60.0,
             "params": {"direction": "in", "duration": 0.3, "way": "left"}},
            {"id": "camera.slow_zoom", "at": None,
             "params": {"factor": 1.12}},
        ]},
        {"start": 80.0, "end": 101.0, "role": "puncak", "effects": [
            {"id": "transition.whip", "at": 80.0,
             "params": {"direction": "in", "duration": 0.3, "way": "right"}},
            {"id": "overlay.emoji_burst", "at": 83.0,
             "params": {"sticker": "alert", "pos": "top_right",
                        "scale": 0.25, "duration": 1.0}},
            {"id": "camera.whip_pan", "at": 90.0,
             "params": {"direction": "left", "duration": 0.4}},
        ]},
        {"start": 101.0, "end": 110.13, "role": "penutup", "effects": [
            {"id": "transition.whip", "at": 101.0,
             "params": {"direction": "in", "duration": 0.3, "way": "left"}},
            {"id": "transition.zoom_blur", "at": 109.5,
             "params": {"direction": "out", "duration": 0.5}},
        ]},
    ],
}

edl_path = BASE / "work_flyingfox" / "edl_flyingfox.json"
edl_path.write_text(json.dumps(EDL, indent=2), encoding="utf-8")

config = yaml.safe_load((resource_path("config.yaml")).read_text(encoding="utf-8"))
out = BASE / "output" / "flyingfox_edited.mp4"
out.parent.mkdir(parents=True, exist_ok=True)

res = render_edl(edl_path, SRC, out, words=[], config=config,
                 work_root=BASE / "work_flyingfox",
                 assets_dir=resource_path("assets"),
                 model_dir=BASE / "models")
print("OUTPUT:", res["output"])
qa = res.get("qa", {})
print("QA:", qa.get("verdict") or qa)
