"""Uji Tahap 8: paket gaya + 3 mode (offline; tanpa Gemini)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.presets import (apply_fixed, check_preset_compliance,  # noqa: E402
                         list_presets, load_preset, preset_allowed_ids)
from app.registry import EffectRegistry  # noqa: E402
from app.utils import resource_path  # noqa: E402

ROOT = resource_path(".")
REG = EffectRegistry(ROOT / "catalog", ROOT / "assets").load()


def test_lima_paket_ada():
    names = list_presets()
    for n in ("authority_disruptor", "clean_podcast", "hype_viral",
              "calm_story", "edu_explainer"):
        assert n in names, n


def test_paket_valid():
    for n in list_presets():
        p = load_preset(n)
        assert p["name"] == n
        assert len(p["allowed"]) >= 3, n
        assert p.get("default_intensity") in ("calm", "medium", "aggressive")


def test_paket_hilang_fallback_none():
    assert load_preset("tak_ada_paket_ini") is None


def test_allowed_hanya_stable_dan_reframe_selalu():
    p = load_preset("clean_podcast")
    ids = preset_allowed_ids(p, REG)
    assert "text.clean_caption" in ids
    assert "reframe.smart_crop" in ids  # reframe tak dibatasi
    assert "insert.face_grid" not in ids  # beta -> diabaikan
    assert "text.pop_in_word" not in ids  # tak ada di allowed


def test_apply_fixed_mengunci_gaya():
    p = load_preset("authority_disruptor")
    edl = {"global": {"text_style": {"id": "text.typewriter", "params": {}},
                      "grade": {"id": "grade.warm_pop", "params": {}}}}
    out = apply_fixed(edl, p)
    assert out["global"]["text_style"]["id"] == "text.pop_in_word"
    assert out["global"]["grade"]["id"] == "grade.cinematic"


def test_compliance_bersih():
    p = load_preset("clean_podcast")
    edl = {"global": {"text_style": {"id": "text.clean_caption"},
                      "grade": {"id": "grade.clean_bright"}},
           "segments": [{"start": 0.0,
                         "effects": [{"id": "text.clean_caption"},
                                     {"id": "reframe.smart_crop"}]}]}
    assert check_preset_compliance(edl, p, REG) == []


def test_compliance_menemukan_pelanggaran():
    p = load_preset("clean_podcast")
    edl = {"global": {"text_style": {"id": "text.clean_caption"},
                      "grade": {"id": "grade.clean_bright"}},
           "segments": [{"start": 0.0,
                         "effects": [{"id": "text.pop_in_word"}]}]}
    bad = check_preset_compliance(edl, p, REG)
    assert any("text.pop_in_word" in b for b in bad)


def test_describe_menyaring_allowed_denied():
    p = load_preset("hype_viral")
    ids = preset_allowed_ids(p, REG)
    txt = REG.describe("9:16", allowed=ids)
    assert "text.pop_in_word" in txt
    assert "text.typewriter" not in txt
    txt2 = REG.describe("9:16", denied=["text.pop_in_word"])
    assert "text.pop_in_word" not in txt2
    assert "camera.punch_in" in txt2
