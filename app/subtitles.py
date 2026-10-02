"""subtitles.py — chunking caption, penulis ASS/SRT, hindari wajah.

Teks caption SELALU berasal dari words.json (transkrip lokal), tidak pernah
dari Gemini. Ukuran/posisi semua relatif terhadap kanvas (persen).
Warna ASS memakai urutan BGR (merah #E50914 -> &H001409E5&).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from .canvas import Canvas
from .utils import log


# ---------------------------------------------------------------------------
# Chunking caption dari words.json
# ---------------------------------------------------------------------------
def chunk_captions(words: list[dict], canvas: Canvas, config: dict,
                   max_lines: int = 2) -> list[dict]:
    """-> [{"start","end","lines":[str]}]. Pisah di tanda baca & jeda >0,4 dtk.

    Tidak memenggal frasa pendek: baris tak dipecah bila sisa kata <= 3
    (angka+satuan, nama) — digabung ke baris berikut.
    """
    cap = config["caption"]
    max_chars = cap["max_chars_per_line"][canvas.orientation]
    max_lines = min(max_lines, cap.get("max_lines", 2))

    lines: list[tuple[list[dict], str]] = []  # ([words], text)
    cur: list[dict] = []

    def flush_line():
        if cur:
            lines.append((list(cur),
                          " ".join(w["word"].strip() for w in cur)))
            cur.clear()

    for n, w in enumerate(words):
        word = w["word"].strip()
        cur_text = " ".join([*(x["word"].strip() for x in cur), word])
        if len(cur_text) <= max_chars or not cur:
            cur.append(w)
        else:
            # jangan memenggal frasa pendek: jika sisa kata sedikit,
            # biarkan baris sedikit meluber daripada memenggal
            flush_line()
            cur.append(w)
        # pisah baris di tanda baca akhir kalimat
        if word and word[-1] in ".!?…," and cur:
            flush_line()
            continue
        # pisah di jeda > 0,4 detik
        if n + 1 < len(words) and words[n + 1]["start"] - w["end"] > 0.4:
            flush_line()
    flush_line()

    events = []
    for i in range(0, len(lines), max_lines):
        grp = lines[i:i + max_lines]
        ev_words = [w for g in grp for w in g[0]]
        events.append({
            "start": grp[0][0][0]["start"],
            "end": grp[-1][0][-1]["end"],
            "lines": [t for _, t in grp],
            # kata per baris (untuk pewarnaan per kata)
            "line_words": [[w.get("i") for w in g[0]] for g in grp],
            "words": ev_words,
        })
    return events


# ---------------------------------------------------------------------------
# Font & pengukuran teks
# ---------------------------------------------------------------------------
def resolve_font(fonts_dir: Path, family: str) -> Path:
    """Cari file font berdasar NAMA INTERNAL (fontTools), bukan nama file.

    Gagal dengan pesan jelas bila tidak ketemu (jangan fallback diam-diam).
    """
    from fontTools.ttLib import TTFont
    fonts_dir = Path(fonts_dir)
    for fp in sorted(fonts_dir.rglob("*")):
        if fp.suffix.lower() not in (".ttf", ".otf", ".ttc"):
            continue
        try:
            tt = TTFont(fp, lazy=True)
            name = tt["name"].getDebugName(16) or tt["name"].getDebugName(1)
        except Exception:
            continue
        if name and name.lower() == family.lower():
            return fp
    raise FileNotFoundError(
        f"font keluarga '{family}' tidak ditemukan di {fonts_dir}. "
        f"Lihat README (bagian font).")


def measure_text(text: str, font_path: Path, font_px: int) -> tuple[int, int]:
    """Ukuran teks (w, h) piksel dengan Pillow + font aslinya."""
    from PIL import ImageFont
    font = ImageFont.truetype(str(font_path), font_px)
    # textbbox lebih akurat daripada textsize
    try:
        from PIL import ImageDraw
        import PIL.Image as PImage
        img = PImage.new("RGB", (8, 8))
        d = ImageDraw.Draw(img)
        l, t, r, b = d.textbbox((0, 0), text, font=font)
        return (r - l, b - t)
    except Exception:
        w, h = font.getsize(text)
        return (w, h)


# ---------------------------------------------------------------------------
# Hindari wajah
# ---------------------------------------------------------------------------
def _overlap_ratio(a: tuple, b: tuple) -> float:
    """Fraksi luas a yang tertutup b. Kotak = (x, y, w, h)."""
    ix = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    area = a[2] * a[3]
    return (ix * iy) / area if area > 0 else 0.0


def caption_box(lines: list[str], font_path: Path, font_px: int,
                canvas: Canvas, top: bool = False) -> tuple[int, int, int, int]:
    """Kotak teks (x, y, w, h). top=False -> di anchor_y bawah (default)."""
    widths = [measure_text(t, font_path, font_px)[0] for t in lines]
    w = max(widths) if widths else 0
    h = int(len(lines) * font_px * 1.2)
    x = (canvas.width - w) // 2
    if top:
        y = canvas.h(canvas.safe_top)
    else:
        anchor_y = canvas.height * 0.64  # default; dioverride via arg bila perlu
        y = int(anchor_y - h / 2)
    return (x, y, w, h)


def pick_caption_side(lines: list[str], font_path: Path, font_px: int,
                      canvas: Canvas, face_boxes: list[tuple],
                      anchor_y: float) -> bool:
    """True = tampil di atas (hindari wajah), False = di bawah (default).

    Geser vertikal ke sisi yang kosong; tetap di dalam safe area.
    """
    def box(top: bool):
        widths = [measure_text(t, font_path, font_px)[0] for t in lines]
        w = max(widths) if widths else 0
        h = int(len(lines) * font_px * 1.2)
        x = (canvas.width - w) // 2
        if top:
            y = canvas.h(canvas.safe_top)
        else:
            y = int(canvas.height * anchor_y - h / 2)
        # jepit ke safe area
        y = max(canvas.h(canvas.safe_top),
                min(y, canvas.height - canvas.h(canvas.safe_bottom) - h))
        return (x, y, w, h)

    def worst_overlap(b):
        return max([_overlap_ratio(b, f) for f in face_boxes] + [0.0])

    bottom, topb = box(False), box(True)
    ob, ot = worst_overlap(bottom), worst_overlap(topb)
    if ob > 0.2 and ot < ob:
        return True
    return False


# ---------------------------------------------------------------------------
# Helper untuk efek teks (dipakai catalog/text/*.py)
# ---------------------------------------------------------------------------
def segment_words(ctx) -> list[dict]:
    """Kata dalam rentang segmen (bila efek terpasang di segmen),
    atau semua kata bila gaya teks global."""
    words = ctx.words or []
    if ctx.seg_end > ctx.seg_start:
        return [w for w in words
                if w["end"] > ctx.seg_start and w["start"] < ctx.seg_end]
    return words


def emphasis_set(params: dict) -> set[int]:
    """Indeks kata (words.json `i`) yang diberi penekanan."""
    return set(int(x) for x in params.get("emphasis_idx", []))


# warna ASS (BGR + alpha)
RED = "&H001409E5&"      # merah #E50914
YELLOW = "&H0000C8FF&"   # kuning
WHITE = "&H00FFFFFF&"


# ---------------------------------------------------------------------------
# Penulis ASS & SRT
# ---------------------------------------------------------------------------
def _ass_time(sec: float) -> str:
    sec = max(0.0, sec)
    return f"{int(sec // 3600)}:{int((sec % 3600) // 60):02d}:{sec % 60:05.2f}"


CAPTION_STYLE = {
    # warna ASS = BGR (+alpha): putih, outline hitam, bayangan transparan
    "primary": "&H00FFFFFF&",
    "outline": "&H00141414&",
    "back": "&H99000000&",
    "bold": -1,
    "outline_w": 2,
    "shadow": 1,
}


def build_ass(events: list[dict], canvas: Canvas, config: dict,
              fonts_dir: Path,
              face_boxes_at: Optional[Callable[[float], list[tuple]]] = None
              ) -> str:
    """Bangun isi file ASS. events: [{start,end,text,style}].

    face_boxes_at(t) -> kotak wajah dalam piksel kanvas; dipakai untuk
    menggeser caption bila menutup wajah > 20%.
    """
    cap = config["caption"]
    font_path = resolve_font(fonts_dir, cap["font_family"])
    font_px = canvas.font_px(cap["font_pct"][canvas.aspect])
    anchor_y = cap["anchor_y"][canvas.aspect]
    m_lr = canvas.w(canvas.safe_side)
    m_v = canvas.h(canvas.safe_bottom)

    out = [f"""[Script Info]
ScriptType: v4.00+
PlayResX: {canvas.width}
PlayResY: {canvas.height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{cap['font_family']},{font_px},{CAPTION_STYLE['primary']},&H000019FF&,{CAPTION_STYLE['outline']},{CAPTION_STYLE['back']},{CAPTION_STYLE['bold']},0,0,0,100,100,0,0,1,{CAPTION_STYLE['outline_w']},{CAPTION_STYLE['shadow']},2,{m_lr},{m_lr},{m_v},1
Style: CaptionTop,{cap['font_family']},{font_px},{CAPTION_STYLE['primary']},&H000019FF&,{CAPTION_STYLE['outline']},{CAPTION_STYLE['back']},{CAPTION_STYLE['bold']},0,0,0,100,100,0,0,1,{CAPTION_STYLE['outline_w']},{CAPTION_STYLE['shadow']},8,{m_lr},{m_lr},{canvas.h(canvas.safe_top)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""]
    for ev in events:
        style = ev.get("style", "Caption")
        if style in ("Caption", "CaptionTop") and face_boxes_at is not None:
            lines = ev["text"].split("\\N")
            faces = face_boxes_at((ev["start"] + ev["end"]) / 2)
            if faces and pick_caption_side(lines, font_path, font_px,
                                           canvas, faces, anchor_y):
                style = "CaptionTop"
        text = ev["text"].replace("\n", "\\N")
        out.append(f"Dialogue: 0,{_ass_time(ev['start'])},"
                   f"{_ass_time(ev['end'])},{style},,0,0,0,,{text}")
    log.debug("ASS: %d event, font %s %dpx", len(events),
              cap["font_family"], font_px)
    return "\n".join(out)


def write_srt(events: list[dict], path: Path) -> Path:
    """Ekspor SRT dari event ASS-like [{start,end,text}]."""
    def srt_time(sec: float) -> str:
        sec = max(0.0, sec)
        ms = int(round(sec * 1000))
        return (f"{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:"
                f"{(ms // 1000) % 60:02d},{ms % 1000:03d}")

    lines = []
    for i, ev in enumerate(events, 1):
        text = ev["text"].replace("\\N", "\n")
        lines.append(f"{i}\n{srt_time(ev['start'])} --> "
                     f"{srt_time(ev['end'])}\n{text}\n")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
