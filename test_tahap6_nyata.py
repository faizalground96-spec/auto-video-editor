"""Uji nyata Tahap 6: 3 video -> Gemini -> EDL -> validasi + uji variasi."""
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
ML = Path.home() / "workspace/user/media_library/video"

VIDEOS = {
    "serius": ML / "0f/0f89567aebce545bce6536c55c4ce3709be28d676fc86a5aa7770f61d8889a46.mp4",
    "opini": ML / "22/2209f0a81b5f86e00a5b8e9085a3e975ac374298f621ded091efaa17fe07924a.mp4",
    "energik": ML / "47/472b5211fe9d7d10d8ad64c47a63f6d1362d0fa2f650da4c1ef7d76f257b372e.mp4",
}

registry = EffectRegistry(BASE / "catalog", BASE / "assets").load()
client = GeminiClient(os.environ["GEMINI_API_KEY"], CFG["gemini"])
model_path = BASE / "assets/models/face_detection_yunet_2023mar.onnx"

results = {}
for name, src in VIDEOS.items():
    print(f"\n===== {name}: {src.name[:16]}... =====", flush=True)
    work = BASE / f"work_tahap6_{name}"
    work.mkdir(parents=True, exist_ok=True)
    info = probe(src)

    # transkrip
    r = transcribe(src, work, CFG["transcribe"], lang="id")
    vdir = r["video_dir"]
    words = json.loads((vdir / "words.json").read_text(encoding="utf-8"))
    silences = json.loads((vdir / "silences.json").read_text(encoding="utf-8"))
    print(f"kata: {len(words)}", flush=True)

    # ringkasan wajah
    ft = ensure_face_track(src, vdir, {"face_sample_interval": 0.5},
                           model_path, info)
    samples = ft.get("samples", [])
    with_face = sum(1 for s in samples if s.get("faces"))
    face_summary = (f"{with_face}/{len(samples)} sampel ada wajah"
                    if samples else "tanpa deteksi wajah")
    print("wajah:", face_summary, flush=True)

    # analisis
    raw = analyze_video(src, words, silences, face_summary, registry,
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
    n_strong = sum(
        1 for s in edl["segments"] for e in s["effects"]
        if registry.entries[e["id"]].meta.strong)
    dur = info.duration or 1
    dens = n_strong / (dur / 10)
    print(f"-> teks={ts} grade={gr} intensitas={inten} "
          f"efek_kuat={n_strong} densitas={dens:.2f}/10s", flush=True)
    results[name] = {"text": ts, "grade": gr, "intensity": inten,
                     "density": dens, "edl_path": str(work / "edl.json")}

print("\n===== UJI VARIASI =====")
combos = [(v["text"], v["grade"], v["intensity"]) for v in results.values()]
print("kombinasi:", combos)
assert len(set(combos)) == 3, "GAGAL: ada kombinasi identik!"
by_dens = sorted(results.items(), key=lambda kv: kv[1]["density"])
calmest, hottest = by_dens[0], by_dens[-1]
gap = hottest[1]["density"] - calmest[1]["density"]
print(f"densitas: {calmest[0]}={calmest[1]['density']:.2f} "
      f"{hottest[0]}={hottest[1]['density']:.2f} selisih={gap:.2f}")
assert gap >= 1.0, f"GAGAL: selisih densitas {gap:.2f} < 1.0"
print("UJI VARIASI LULUS")
json.dump(results, open(BASE / "work_tahap6_hasil.json", "w"),
          indent=2, ensure_ascii=False)
