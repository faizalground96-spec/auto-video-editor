# Auto Video Editor

Aplikasi desktop yang mengubah video apa pun menjadi video vertikal/horizontal
siap posting — otomatis. Alur: **transkrip (Whisper lokal)** → **analisis
Gemini** (topik, mood, tempo) → **rencana edit (EDL)** → **render FFmpeg**
→ **QA otomatis**.

## Cara build (Windows)

1. Pasang Python 3.11 atau 3.12 dari python.org (centang "Add to PATH").
   Jangan pakai 3.13+ — beberapa library belum mendukung.
2. Buka `cmd` di folder proyek, jalankan:
   ```
   build_windows.bat
   ```
   Skrip akan: cek Python → buat venv → `pip install -r requirements.txt`
   → unduh `ffmpeg.exe` ke `bin\` (bila belum ada) → `pyinstaller build.spec`
   → jalankan `--self-test` pada hasil build.
3. Hasil: `dist\AutoVideoEditor\` berisi:
   - `AutoVideoEditor.exe` — GUI (tanpa konsol)
   - `AutoVideoEditorCLI.exe` — CLI (dengan konsol)
4. Bila unduhan ffmpeg gagal: unduh manual dari
   https://www.gyan.dev/ffmpeg/builds/ dan letakkan `ffmpeg.exe` di `bin\`.

Semua keluaran build dicatat di `build.log`.

## Memasukkan API key

- **GUI**: isi kolom "API key" (disimpan di folder data aplikasi,
  `%APPDATA%\AutoVideoEditor\gemini_key.txt`, mode privat).
- **CLI**: set environment variable `GEMINI_API_KEY`.
- Jangan pernah commit API key ke git.

## Cara pakai

**GUI** — buka `AutoVideoEditor.exe`: seret video → atur opsi (mode, paket
gaya, rasio, intensitas) → **Analisis** (lihat rencana edit) → **Generate**.

**CLI**:
```bat
AutoVideoEditorCLI.exe input.mp4 --mode auto
AutoVideoEditorCLI.exe input.mp4 --preset clean_podcast
AutoVideoEditorCLI.exe input.mp4 --mode auto --disable text.pop_in_word,camera.punch_in
AutoVideoEditorCLI.exe input.mp4 --aspect 9:16 --intensity calm --user-notes "lebih kalem"
AutoVideoEditorCLI.exe input.mp4 --dry-run        :: hanya analisis -> edl.json
AutoVideoEditorCLI.exe input.mp4 --from-edl edl.json
AutoVideoEditorCLI.exe --self-test                :: cek lingkungan
AutoVideoEditorCLI.exe --list-catalog
```

## Arti hasil QA

Setelah render, QA otomatis memeriksa: format, **audio** (korelasi ≥0,99
atau cek SFX), wajah ≥95% utuh (smart_crop), teks di safe area, tidak ada
black frame, dan anggaran densitas efek. `QA: LULUS` berarti semua cek
penting lewat; `GAGAL` disertai nama cek dan detailnya (lihat
`qa_report.json` di folder work).

## Paket gaya (presets)

Lima paket di `presets/`: `authority_disruptor`, `clean_podcast`,
`hype_viral`, `calm_story`, `edu_explainer`. Tiga mode: **auto** (Gemini
bebas), **preset** (efek dibatasi paket), **auto+kunci** (`--disable`
mematikan efek tertentu).

## Cara menambah efek baru

1. Buat file `catalog/<kategori>/<nama>.py` berisi `META` (dict: id, status,
   category, description, aspects, params, strong, sfx, dsb) dan class
   `Effect` dengan method `build(ctx, at, params)`.
2. Contoh lengkap: lihat `catalog/camera/punch_in.py`.
3. Jalankan `AutoVideoEditorCLI.exe --list-catalog` untuk verifikasi.

## Ganti model Gemini

Ubah `config.yaml` bagian `gemini:` (nama model, dsb). Tanpa build ulang —
file ikut terbundel dan dibaca saat runtime.

## Privasi

Video diunggah ke Gemini **hanya untuk analisis** (proxy 540p) dan **dihapus
dari server Gemini** segera setelah analisis selesai. Transkrip dibuat lokal
(Whisper). API key tersimpan lokal saja.

## Masalah umum

- **Antivirus/SmartScreen memblokir exe**: hasil PyInstaller kadang
  ditandai false-positive. Klik "Run anyway" / tambahkan pengecualian.
- **ffmpeg tidak ketemu**: pastikan `bin\ffmpeg.exe` ada di folder aplikasi,
  atau ffmpeg ada di PATH.
- **Model Whisper gagal diunduh**: cek koneksi; model (~460MB) diunduh sekali
  ke folder data aplikasi. Di Windows, abaikan peringatan symlink Hugging Face.
- **Kuota Gemini habis (429)**: tunggu beberapa menit; coba `--dry-run`
  dulu untuk memastikan EDL bagus.
- **Video HDR terlihat pucat**: konversi tone-mapping otomatis terbatas;
  hasil mungkin lebih datar dari aslinya.
- **Hasil lembut**: sumber beresolusi rendah — QA memberi peringatan ini.

## Distribusi

Lihat `THIRD_PARTY_LICENSES.md`. Distribusi di luar pemakaian pribadi
memerlukan pemeriksaan lisensi di sana (terutama FFmpeg/GPL dan PySide6/LGPL).
