"""Analisis Tahap 6 untuk video santai (cewek selingkuh)."""
import json
import os
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv

load_dotenv(".env")
from app.analyze import GeminiClient, analyze_video
from app.probe import probe
from app.reframe import ensure_face_track
from app.registry import EffectRegistry
from app.transcribe import transcribe
from app.utils import resource_path, sanitize_proxy_env
from app.validate import validate_edl

sanitize_proxy_env()
BASE = Path(__file__).resolve().parent
CFG = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
SRC = (Path.home() / "workspace/user/media_library/video/ee/"
       "ee1f6b6fba2efcdbbae5061da1d1c9ed9493db8b6af66b91ede2477b90636252.mp4")

registry = EffectRegistry(BASE / "catalog", BASE / "assets").load()
client = GeminiClient(os.environ["GEMINI_API_KEY"], CFG["gemini"])
work = BASE / "work_tahap6_santai"
work.mkdir(parents=True, exist_ok=True)
info = probe(SRC)

r = transcribe(SRC, work, CFG["transcribe"], lang="id")
vdir = r["video_dir"]
words = json.loads((vdir / "words.json").read_text(encoding="utf-8"))
silences = json.loads((vdir / "silences.json").read_text(encoding="utf-8"))
print(f"kata: {len(words)}", flush=True)

ft = ensure_face_track(SRC, vdir, {"face_sample_interval": 0.5},
                       BASE / "assets/models/face_detection_yunet_2023mar.onnx",
                       info)
samples = ft.get("samples", [])
with_face = sum(1 for s in samples if s.get("faces"))
face_summary = f"{with_face}/{len(samples)} sampel ada wajah"
print("wajah:", face_summary, flush=True)

raw = analyze_video(SRC, words, silences, face_summary, registry,
                    client, CFG, work, aspect="9:16", seed=7)
ok, errors, edl = validate_edl(
    raw, registry=registry, words=words, silences=silences,
    duration=info.duration, aspect="9:16", cfg=CFG, dry_run=False,
    work_dir=work, face_detected=with_face > 0)
print("valid:", ok, errors[:3] if errors else "", flush=True)
g = edl["global"]
ts = (g.get("text_style") or {}).get("id")
gr = (g.get("grade") or {}).get("id")
inten = g.get("intensity")
a = edl.get("analysis", {})
print(f"genre={a.get('genre')} mood={a.get('mood')} energy={a.get('energy')}")
print(f"-> teks={ts} grade={gr} intensitas={inten}", flush=True)
n_strong = sum(1 for s in edl["segments"] for e in s["effects"]
               if registry.entries[e["id"]].meta.strong)
print(f"segmen={len(edl['segments'])} efek_kuat={n_strong} "
      f"densitas={n_strong/(info.duration/10):.2f}/10s", flush=True)
