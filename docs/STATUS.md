# STATUS — Auto Video Editor

Tabel tahap, status, dan catatan. Diperbarui setiap tahap selesai.

| Tahap | Nama | Status | Catatan |
|---|---|---|---|
| 0 | Cek lingkungan dan bahan | LULUS DENGAN CATATAN | Python 3.12.3 (bukan 3.11); fontconfig tak ada di build ffmpeg (pakai fontsdir eksplisit); quirk `no_proxy`/httpx, pin `av==14.2.0`, YuNet via LFS media URL — semua didokumentasikan di `~/TOOLS.md`. Bahan pemilik: 1 video uji (ceramah, serius, 25 dtk, 1080x1920) sudah dipakai; kurang 2 video + 1 video sulit. |
| 1 | Fondasi (config, utils, probe, canvas) | LULUS | `git init` + kerangka folder; `config.yaml`, `requirements.txt` (pin `av==14.2.0`), `docs/STATUS.md`; `app/utils.py` (logging+redaksi key, resource_path, app_dirs, find_ffmpeg, run_ffmpeg, ff_filter_path), `app/probe.py` (SourceInfo: rotasi via tag/side-data, VFR via sampling durasi paket, SAR, HDR, tanpa-audio), `app/canvas.py` (resolve_aspect auto, safe area, helper persen); `tools/make_samples.py` (7 varian sintetis); `pytest` 20/20 lulus. |
| 2 | Transkrip per kata | BELUM | |
| 3 | Registry katalog + kerangka ujung-ke-ujung | BELUM | |
| 4 | Mesin render inti, reframe, teks ASS, QA | BELUM | |
| 5 | Perluasan katalog (12 efek wajib) | BELUM | |
| 6 | Gemini → EDL | BELUM | |
| 7 | SFX otomatis | BELUM | |
| 8 | Mode dan paket gaya | BELUM | |
| 9 | GUI dan CLI | BELUM | |
| 10 | Paket Windows | BELUM | |

## Efek

| ID efek | Status | Teruji di rasio | Catatan |
|---|---|---|---|
| *(belum ada)* | | | |

## Keputusan yang dicatat

- 2026-10-02 (Tahap 0): model Gemini default = `gemini-2.5-flash` (terverifikasi dukung video). `gemini-3-flash-preview` ada tapi preview.
- 2026-10-02 (Tahap 0): `av` dipin `==14.2.0` (faster-whisper 1.2.1 rusak dengan av>=15).
- 2026-10-02 (Tahap 0): Whisper `small` int8 faktor 0,29 di VM (7,3 dtk untuk 25,3 dtk audio).
