# THIRD_PARTY_LICENSES.md

Komponen pihak ketiga yang dipakai Auto Video Editor. **Distribusi di luar
pemakaian pribadi memerlukan pemeriksaan lisensi ini.**

| Komponen | Lisensi | Catatan |
|---|---|---|
| FFmpeg (build gyan.dev essentials, termasuk libx264) | GPL v3 (karena libx264) | Unduh dari https://www.gyan.dev/ffmpeg/builds/ ; sumber build: https://github.com/GyanD/codexffmpeg |
| PySide6 (Qt for Python) | LGPL v3 | https://www.qt.io/ ; aplikasi menaut dinamis (pip) |
| faster-whisper (+ ctranslate2) | MIT | https://github.com/SYSTRAN/faster-whisper |
| Model Whisper (openai/whisper-small) | MIT | Diunduh otomatis saat pertama dipakai, tidak dibundel |
| opencv-python-headless | Apache-2.0 | https://github.com/opencv/opencv-python |
| YuNet face detection (ONNX) | MIT | https://github.com/opencv/opencv_zoo |
| numpy, Pillow, PyYAML, pydantic, fontTools | BSD / MIT / Apache-2.0 | via pip |
| google-genai (Gemini API) | Apache-2.0 | https://github.com/googleapis/python-genai |
| Montserrat (font) | SIL Open Font License 1.1 | `assets/fonts/OFL-Montserrat.txt` |
| SFX (`assets/sfx/*.wav`) | Buatan sendiri (tools/make_sfx.py) | Bebas dipakai |

Catatan: bila Anda mengganti build FFmpeg dengan varian LGPL (tanpa
libx264/x265), kewajiban GPL di atas tidak berlaku — sesuaikan tabel ini.
