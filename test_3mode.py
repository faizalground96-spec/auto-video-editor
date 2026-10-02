"""Uji nyata Tahap 8: 1 video x 3 mode (auto / preset / auto+kunci)."""
import json
import os
import sys
import time
import yaml
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from dotenv import load_dotenv

load_dotenv(BASE / ".env")
from app.analyze import GeminiClient, analyze_video
from app.presets import (apply_fixed, check_preset_compliance, load_preset,
                         preset_allowed_ids)
from app.probe import probe
from app.registry import EffectRegistry
from app.transcribe import transcribe
from app.utils import resource_path, sanitize_proxy_env
from app.validate import validate_edl

sanitize_proxy_env()
CFG = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
SRC = (Path.home() / "workspace/user/media_library/video/ee/"
       "ee1f6b6fba2efcdbbae5061da1d1c9ed9493db8b6af66b91ede2477b90636252.mp4")

registry = EffectRegistry(BASE / "catalog", BASE / "assets").load()
client = GeminiClient(os.environ["GEMINI_API_KEY"], CFG["gemini"])
work = BASE / "work_tahap8"
work.mkdir(parents=True, exist_ok=True)
info = probe(SRC)

r = transcribe(SRC, work, CFG["transcribe"], lang="id")
vdir = r["video_dir"]
words = json.loads((vdir / "words.json").read_text(encoding="utf-8"))
silences = json.loads((vdir / "silences.json").read_text(encoding="utf-8"))
face_summary = "47/47 sampel ada wajah"

MODES = [
    ("auto", None, None, None),
    ("preset:clean_podcast", "clean_podcast", None, None),
    ("auto+kunci", None, ["text.pop_in_word", "camera.punch_in"], None),
]

results = {}
for i, (label, preset_name, denied, _x) in enumerate(MODES):
    if i:
        time.sleep(20)  # jeda hemat kuota
    preset = load_preset(preset_name) if preset_name else None
    allowed = preset_allowed_ids(preset, registry) if preset else None
    wdir = work / label.replace(":", "_").replace("+", "_")
    wdir.mkdir(parents=True, exist_ok=True)
    raw = analyze_video(SRC, words, silences, face_summary, registry,
                        client, CFG, wdir, aspect="9:16", seed=7,
                        allowed=allowed, denied=denied,
                        force_reanalyze=True)
    raw = apply_fixed(raw, preset)  # kunci paket sebelum validasi
    ok, errors, edl = validate_edl(
        raw, registry=registry, words=words, silences=silences,
        duration=info.duration, aspect="9:16", cfg=CFG, dry_run=False,
        work_dir=wdir, face_detected=True,
        allowed=allowed, denied=denied)
    # apply_fixed sebelum validate: fixed dipaksa, validate memastikan
    # sisanya patuh (efek di luar allowed dibuang di validate)
    effs = sorted({e["id"] for s in edl["segments"]
                   for e in s["effects"]})
    g = edl["global"]
    combo = ((g.get("text_style") or {}).get("id"),
             (g.get("grade") or {}).get("id"), g.get("intensity"))
    results[label] = {"ok": ok, "errors": errors[:2], "effects": effs,
                      "combo": combo}
    print(f"{label}: valid={ok} combo={combo}", flush=True)
    print(f"  efek: {effs}", flush=True)
    if preset:
        bad = check_preset_compliance(raw, preset, registry)
        print(f"  compliance: {'BERSIH' if not bad else bad}", flush=True)
    if denied:
        leak = [e for e in effs if e in denied]
        print(f"  kunci bocor: {leak if leak else 'tidak ada'}", flush=True)

json.dump(results, open(work / "hasil_3mode.json", "w"), indent=1)
print("tersimpan:", work / "hasil_3mode.json")
