"""Uji subtitles: chunking, font, ASS, SRT, hindari wajah."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.canvas import Canvas  # noqa: E402
from app.subtitles import (build_ass, chunk_captions,  # noqa: E402
                           pick_caption_side, resolve_font, write_srt)
from app.utils import resource_path  # noqa: E402

ROOT = resource_path(".")
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
FONTS = ROOT / "assets" / "fonts"


def _words(text, gap=0.0):
    ws, t = [], 0.0
    for w in text.split():
        ws.append({"i": len(ws), "word": w, "start": t, "end": t + 0.3,
                   "prob": 0.99})
        t += 0.35 + gap
    return ws


def test_chunk_pisah_di_titik_dan_jeda():
    words = _words("Halo dunia. Apa kabar", gap=0.0)
    words[3]["start"] = words[2]["end"] + 0.5  # jeda > 0,4 dtk
    words[3]["end"] = words[3]["start"] + 0.3
    evs = chunk_captions(words, Canvas.from_aspect("9:16"), CFG)
    # baris: "Halo dunia." | "Apa" | "kabar" -> event: 2 baris + 1 baris
    assert len(evs) == 2
    assert evs[0]["lines"] == ["Halo dunia.", "Apa"]
    assert evs[1]["lines"] == ["kabar"]


def test_chunk_hormati_batas_karakter():
    words = _words(" ".join(["kata"] * 30))
    cv = Canvas.from_aspect("9:16")
    evs = chunk_captions(words, cv, CFG)
    mx = CFG["caption"]["max_chars_per_line"][cv.orientation]
    for e in evs:
        for ln in e["lines"]:
            assert len(ln) <= mx + 8  # toleransi frasa pendek
    assert all(len(e["lines"]) <= 2 for e in evs)


def test_resolve_font_montserrat():
    p = resolve_font(FONTS, "Montserrat")
    assert p.is_file() and p.suffix == ".ttf"


def test_resolve_font_hilang_gagal_jelas():
    with pytest.raises(FileNotFoundError, match="tidak ditemukan"):
        resolve_font(FONTS, "FontYangTidakAda123")


def test_build_ass_struktur():
    evs = [{"start": 0.0, "end": 1.0, "text": "Halo\\Ndunia",
            "style": "Caption"}]
    ass = build_ass(evs, Canvas.from_aspect("9:16"), CFG, FONTS)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Style: Caption,Montserrat," in ass
    assert "Dialogue: 0,0:00:00.00,0:00:01.00,Caption," in ass
    assert "Halo\\Ndunia" in ass


def test_build_ass_hindari_wajah():
    evs = [{"start": 0.0, "end": 1.0, "text": "Halo dunia",
            "style": "Caption"}]
    canvas = Canvas.from_aspect("9:16")
    # wajah besar di area caption bawah -> harus pindah ke atas
    face = [(400, 1150, 280, 350)]
    ass = build_ass(evs, canvas, CFG, FONTS,
                    face_boxes_at=lambda t: face)
    assert ",CaptionTop," in ass
    # tanpa wajah -> tetap di bawah
    ass2 = build_ass(evs, canvas, CFG, FONTS,
                     face_boxes_at=lambda t: [])
    assert ",Caption," in ass2 and ",CaptionTop," not in ass2


def test_write_srt_format(tmp_path):
    evs = [{"start": 1.5, "end": 3.25, "text": "Halo\\Ndunia",
            "style": "Caption"}]
    p = write_srt(evs, tmp_path / "x.srt")
    txt = p.read_text(encoding="utf-8")
    assert "00:00:01,500 --> 00:00:03,250" in txt
    assert "Halo\ndunia" in txt


def test_pick_caption_side_tanpa_wajah_di_bawah():
    canvas = Canvas.from_aspect("9:16")
    assert pick_caption_side(["halo"], FONTS / "Montserrat.ttf", 64,
                             canvas, [], 0.64) is False
