# STATUS — Auto Video Editor

Tabel tahap, status, dan catatan. Diperbarui setiap tahap selesai.

| Tahap | Nama | Status | Catatan |
|---|---|---|---|
| 0 | Cek lingkungan dan bahan | LULUS DENGAN CATATAN | Python 3.12.3 (bukan 3.11); fontconfig tak ada di build ffmpeg (pakai fontsdir eksplisit); quirk `no_proxy`/httpx, pin `av==14.2.0`, YuNet via LFS media URL — semua didokumentasikan di `~/TOOLS.md`. Bahan pemilik: 1 video uji (ceramah, serius, 25 dtk, 1080x1920) sudah dipakai; kurang 2 video + 1 video sulit. |
| 1 | Fondasi (config, utils, probe, canvas) | LULUS | `git init` + kerangka folder; `config.yaml`, `requirements.txt` (pin `av==14.2.0`), `docs/STATUS.md`; `app/utils.py` (logging+redaksi key, resource_path, app_dirs, find_ffmpeg, run_ffmpeg, ff_filter_path), `app/probe.py` (SourceInfo: rotasi via tag/side-data, VFR via sampling durasi paket, SAR, HDR, tanpa-audio), `app/canvas.py` (resolve_aspect auto, safe area, helper persen); `tools/make_samples.py` (7 varian sintetis); `pytest` 20/20 lulus. |
| 2 | Transkrip per kata | LULUS | `app/transcribe.py`: ekstrak audio ke `work/<video>/audio.wav`, faster-whisper (`word_timestamps`, `vad_filter`, `condition_on_previous_text=False`), keluaran `words.json` (indeks `i`), `transcript.txt` (`[12] kata`), `sentences.json` (pisah tanda baca/jeda >0,6 dtk), `silences.json` (silencedetect −35dB/0,25 dtk), `meta.json` (kunci cache = hash isi + model + bahasa). Normalisasi paksa timestamp monoton & tak tumpang tindih. Uji di video ceramah: 48 kata, 3 kalimat, faktor waktu 0,64 (auto-detect), cache hit 0,5 dtk. `pytest` 26/26 lulus. |
| 3 | Registry katalog + kerangka ujung-ke-ujung | LULUS | `app/schema.py` (EffectMeta pydantic + EDL minimal + EffectContext/Output), `app/registry.py` (loader per-file via importlib — compile dari source fresh karena cache .pyc bisa basi; file rusak dilewati tanpa crash; `describe()`, `fingerprint()`, `build()` dgn clamp param), 4 efek pertama (`text.clean_caption`, `camera.punch_in`, `grade.clean_bright`, `reframe.blur_fill`), `app/render.py` kerangka (normalisasi→reframe→grade→efek segmen→ASS pass akhir→audio copy), `app/cli.py` (`--list-catalog`, `--from-edl`). `pytest` 39/39 lulus, render 3 dtk per efek terverifikasi (resolusi/durasi benar). |
| 4 | Mesin render inti, reframe, teks ASS, QA | LULUS | `app/render.py` ditulis ulang: partisi linimasa→chunk (trim+setpts, waktu lokal), `render_manifest.json` (hash sumber+EDL+ffmpeg+fingerprint → resume), gabung via concat demuxer, pass akhir bakar ASS sekali + audio (maks 2x encode; copy bila AAC tanpa SFX), fallback encoder. `app/reframe.py`: `ensure_face_track` (YuNet tiap 0,25 dtk → `face_track.json`; cadangan Haar; deteksi cut via histogram), `smart_crop_curve` (deadzone + peredam eksponensial + batas kecepatan 20%/dtk, tahan 2 dtk bila wajah hilang, 1 subjek utama via IoU-tracking, gabungan ≤85% lebar crop, None→fallback blur_fill), `curve_to_crop_expr` (RDP + ekspresi `t` bersarang — keputusan arsitektur, cadangan pipe OpenCV). Efek `reframe.smart_crop` + `reframe.fit_letterbox` (total 6 efek). `app/subtitles.py`: chunking (tanda baca/jeda>0,4 dtk, batas karakter per orientasi), `resolve_font` via fontTools (gagal jelas), `build_ass` (PlayRes=kanvas, BGR, hindari wajah>20%→pindah atas), `write_srt`. `app/qa.py`: 8 cek (format, audio korelasi≥0,99, wajah ≥95%, getar, teks di safe area, blackframe, densitas) + `qa_report.json` + `contact_sheet.jpg`. Matriks 10 kombinasi: semua QA LULUS (detail di bawah). `pytest` 64/64 lulus (~72 dtk). |
| 5 | Perluasan katalog (12 efek wajib) | LULUS | 15 efek baru (total 21; 20 stable + 1 beta). Teks: `pop_in_word` (kata muncul + emphasis merah), `karaoke_highlight` (`\k` sinkron + jeda), `typewriter` (kursor), `red_keyword` (statis merah) — semua pertahankan struktur 2 baris + uji 4 rasio (safe area, wajah ≤20%). Kamera: `slow_zoom`, `whip_pan`. Grade: `cinematic` (teal/orange + vignette), `warm_pop`. Insert: `b_roll_top` (klip eksternal via extra_inputs), `face_grid` (**beta**, grid 2-3 wajah mengikuti via ekspresi). Layout: `split_compare` (via [VSRC]/needs_source). Overlay: `emoji_burst` (3 stiker PNG orisinal di assets/stickers), `progress_bar`. Transisi: `whip`, `zoom_blur` (in/out di batas segmen). Kontrak filter: placeholder [CUR]/[NEXT]/[INPUTi]/[VSRC]; schema tambah tipe param `list` + status `beta`. Temuan ffmpeg 8.1: `gblur` sigma tak terima ekspresi t; `drawbox` tak kenal `W`; `colorbalance` tanpa opsi `ms/hs`; label tak dikonsumsi = error binding. `pytest` 108/108 lulus (~120 dtk). Fixture: `tests/fixtures/edl_effects.json`. |
| 6 | Gemini → EDL | SEBAGIAN | `app/analyze.py` (LLMClient/GeminiClient/FakeClient, proxy 540p CRF28, upload Files API + hapus setelah analisis, cache EDL, retry JSON), `app/validate.py` (12 aturan: ID stable, clamp param, anggaran efek kuat + min_gap, conflicts, snapping ≤0,3 dtk, emphasis idx vs words.json, closing ≤40 char, reframe cadangan, aturan hook), `prompts/analyze_system.md` (11 aturan + tabel mood + 2 contoh), skema EDL v2 (analysis, emphasis_words, closing, seed; kompatibel v1), `requires_at` di META (5 efek). Uji nyata 3 video: ceramah→(pop_in_word, cinematic, medium), opini berita→(pop_in_word, cinematic, medium), flying fox→(pop_in_word, warm_pop, aggressive, 8 segmen). Uji variasi (a) GAGAL 3x run: dua video serius dapat kombinasi identik (editorial wajar, tapi tak memenuhi syarat plan); (b) selisih densitas fluktuatif 0,42–1,27. Sudah disetel 2x (tabel prompt + good_for katalog + aturan 11) per plan; tidak dipaksa lulus. `pytest` 116/116. |
| 7 | SFX otomatis | BELUM | |
| 8 | Mode dan paket gaya | BELUM | |
| 9 | GUI dan CLI | BELUM | |
| 10 | Paket Windows | BELUM | |

## Efek

| ID efek | Status | Teruji di rasio | Catatan |
|---|---|---|---|
| text.clean_caption | stable | 9:16, 16:9 | v2: chunking via app/subtitles.py; hindari wajah |
| camera.punch_in | stable | 9:16 | zoom 1,2x di t=1 dtk |
| grade.clean_bright | stable | 9:16 | strength 0,8 |
| reframe.blur_fill | stable | 9:16, 16:9, 1:1, 4:5 | matriks 03–07 |
| reframe.smart_crop | stable | 1:1 (wajah asli) | video ceramah 25 dtk → wajah 26/26 utuh, getar lulus |
| reframe.fit_letterbox | stable | — | cadangan, terdaftar & lulus registry |

## Matriks orientasi Tahap 4 (semua QA LULUS)

| # | Sumber → target | Reframe aktual | Waktu | Ukuran | Catatan |
|---|---|---|---|---|---|
| 01 | vertikal → 9:16 | none | 3,7 dtk | 225 KB | — |
| 02 | horizontal → 16:9 | none | 3,3 dtk | 290 KB | — |
| 03 | horizontal → 9:16 | blur_fill (fallback) | 4,8 dtk | 726 KB | smart_crop diminta, tanpa wajah → fallback jujur |
| 04 | horizontal → 9:16 | blur_fill | 1,7 dtk | 726 KB | — |
| 05 | vertikal → 16:9 | blur_fill | 3,4 dtk | 186 KB | — |
| 06 | horizontal → 1:1 | blur_fill (fallback) | 3,2 dtk | 424 KB | tanpa wajah → fallback |
| 07 | horizontal → 4:5 | blur_fill (fallback) | 3,2 dtk | 531 KB | tanpa wajah → fallback |
| 08 | rotated (metadata) → 9:16 | none | 3,2 dtk | 326 KB | orientasi terdeteksi benar via autorotate |
| 09 | VFR → 9:16 | none | 3,3 dtk | 285 KB | output 30fps CFR, korelasi audio 1,0 |
| 10 | ceramah 25 dtk → 1:1 | smart_crop | 28,4 dtk | 10,8 MB | YuNet 101/101 wajah; 26/26 wajah utuh; getar lulus |

`qa_report.json` + `contact_sheet.jpg` tiap kombinasi: `work/matrix/<nama>/` (gitignored; salinan kerja).

## Keputusan yang dicatat

- 2026-10-02 (Tahap 0): model Gemini default = `gemini-2.5-flash` (terverifikasi dukung video). `gemini-3-flash-preview` ada tapi preview.
- 2026-10-02 (Tahap 0): `av` dipin `==14.2.0` (faster-whisper 1.2.1 rusak dengan av>=15).
- 2026-10-02 (Tahap 0): Whisper `small` int8 faktor 0,29 di VM (7,3 dtk untuk 25,3 dtk audio).
- 2026-10-02 (Tahap 4): smart_crop memakai ekspresi `t` bersarang di filter `crop` (kurva global → iris per segmen → RDP eps 0,5% lebar crop). Bukan sendcmd/OpenCV-pipe. Uji getar QA memvalidasi.
- 2026-10-02 (Tahap 4): rotasi metadata ditangani autorotate bawaan ffmpeg (filter melihat frame yang sudah terotasi, konsisten dengan probe); JANGAN tambah transpose manual (double-rotate).
- 2026-10-02 (Tahap 4): chunk memakai `trim=start:end,setpts=PTS-STARTPTS` (bukan -ss) agar `t` selalu lokal-segmen tanpa ambiguitas timestamp.
- 2026-10-02 (Tahap 4): render faktor ~0,96× durasi video (segar, 25 dtk→24 dtk) di VM 2 CPU; face detect YuNet ~4 dtk/25 dtk video; chunk cache → ~0,30×.
- 2026-10-02 (Tahap 4): `sanitize_proxy_env()` dipanggil di `app/transcribe.py` sebelum WhisperModel (no_proxy bracket merusak httpx huggingface_hub; sebelumnya hanya di TOOLS.md).
- 2026-10-02 (Tahap 5): efek yang butuh sumber mentah pakai `needs_source` + placeholder `[VSRC]` (render split [0:v]); efek ber-input file pakai `extra_inputs` + `[INPUTi]`.
- 2026-10-02 (Tahap 5): `qa.py` check_text kini strip tag ASS {\...} sebelum ukur lebar (sebelumnya tag ikut terukur).
