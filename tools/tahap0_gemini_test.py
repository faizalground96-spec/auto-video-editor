"""Tahap 0.4: uji Gemini sungguhan (teks, list model, upload video via Files API, hapus).
Key dibaca dari .env, TIDAK PERNAH dicetak."""
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from dotenv import load_dotenv

load_dotenv(os.path.join(BASE, ".env"))
from google import genai  # noqa: E402

API_KEY = os.environ.get("GEMINI_API_KEY", "")
assert API_KEY, "GEMINI_API_KEY kosong"

# Quirk VPS: httpx gagal parse entri IPv6 bracket ([::1]) di no_proxy.
# Bersihkan sebelum client dibuat; proxy egress tetap dipakai.
for _var in ("no_proxy", "NO_PROXY"):
    _v = os.environ.get(_var, "")
    os.environ[_var] = ",".join(p for p in _v.split(",") if "[" not in p)


def redact(s: str) -> str:
    # jangan pernah membocorkan key ke output
    return s.replace(API_KEY, "[REDACTED]") if API_KEY else s


client = genai.Client(api_key=API_KEY)

# 1. Panggilan teks pendek
t0 = time.time()
r = client.models.generate_content(model="gemini-2.5-flash", contents="Balas hanya: OK")
print("1) text call:", redact(r.text.strip()), f"({time.time()-t0:.1f}s)")

# 2. Daftar model, pilih Flash terbaru yang mendukung video
t0 = time.time()
cands = []
for m in client.models.list():
    name = m.name or ""
    if "flash" in name.lower():
        cands.append(name)
print(f"2) model flash ditemukan ({time.time()-t0:.1f}s):")
for c in sorted(set(cands)):
    print("   -", c)
video_model = "gemini-2.5-flash"
for pref in ["gemini-2.5-flash", "gemini-2.0-flash"]:
    hit = [c for c in cands if pref in c]
    if hit:
        video_model = hit[0].split("/")[-1]
        break
print("   -> dipakai untuk video:", video_model)

# 3. Upload video user via Files API
video_path = os.path.expanduser(
    "~/workspace/user/media_library/video/0f/"
    "0f89567aebce545bce6536c55c4ce3709be28d676fc86a5aa7770f61d8889a46.mp4"
)
t0 = time.time()
f = client.files.upload(file=video_path)
print(f"3) upload: name={f.name} size={f.size_bytes} ({time.time()-t0:.1f}s)")
t0 = time.time()
while f.state.name != "ACTIVE":
    time.sleep(2)
    f = client.files.get(name=f.name)
    if time.time() - t0 > 180:
        raise TimeoutError("file tidak ACTIVE dalam 180s, state=" + f.state.name)
print(f"   ACTIVE setelah {time.time()-t0:.1f}s")

# 4. Minta analisis JSON singkat
prompt = (
    "Tonton video ini. Balas HANYA dengan JSON valid, tanpa teks lain: "
    '{"topic": "satu kalimat", "genre": "edukasi/opini/vlog/dakwah/dll", '
    '"mood": "tenang/serius/antusias/dll", "energy": "low/medium/high", '
    '"speech_pace": "lambat/sedang/cepat", "language": "bahasa yang dipakai", '
    '"summary_id": "ringkasan 2 kalimat Bahasa Indonesia"}'
)
t0 = time.time()
r = client.models.generate_content(
    model=video_model,
    contents=[f, prompt],
    config={"response_mime_type": "application/json"},
)
dt = time.time() - t0
print(f"4) analisis ({dt:.1f}s):")
try:
    print(json.dumps(json.loads(r.text), indent=2, ensure_ascii=False))
except Exception:
    print(redact(r.text[:500]))

# 5. Hapus file dari Gemini (privasi, sesuai plan)
t0 = time.time()
client.files.delete(name=f.name)
print(f"5) file dihapus dari Gemini ({time.time()-t0:.1f}s)")
try:
    client.files.get(name=f.name)
    print("   PERINGATAN: file masih ada!")
except Exception as e:
    print("   OK, file sudah tidak ada:", redact(str(e))[:80])

print("\nTAHAP 0.4 SELESAI: LULUS")
