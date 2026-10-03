"""Uji app/registry.py — tanpa jaringan, tanpa API key."""
from pathlib import Path

import pytest

from app.registry import EffectRegistry
from app.schema import EffectContext, EffectOutput
from app.utils import resource_path

CATALOG = resource_path("catalog")
ASSETS = resource_path("assets")

DUMMY_EFFECT = '''
from app.schema import EffectContext, EffectOutput
META = {{
    "id": "{eid}",
    "category": "{cat}",
    "status": "{status}",
    "version": 1,
    "description": "efek dummy untuk uji",
    "good_for": [], "avoid_for": [],
    "params": {{"x": {{"type": "float", "min": 0.0, "max": 1.0,
                       "default": 0.5}}}},
    "aspects": {aspects},
    "requires": {{"assets": [], "face": False}},
}}
def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    return EffectOutput(video_filters=["null"])
'''


def _write_dummy(d: Path, eid: str, cat: str, status="stable",
                 aspects='["9:16", "16:9", "1:1", "4:5"]') -> Path:
    sub = d / cat
    sub.mkdir(parents=True, exist_ok=True)
    fp = sub / f"{eid.split('.', 1)[1]}.py"
    fp.write_text(DUMMY_EFFECT.format(eid=eid, cat=cat, status=status,
                                      aspects=aspects))
    return fp


def test_load_21_effects():
    reg = EffectRegistry(CATALOG, ASSETS).load()
    assert reg.errors == []
    ids = reg.all_ids()
    # 21 asli + 3 baru: poster_keyword, bg_color, cta_button
    assert len(ids) == 24
    assert "text.poster_keyword" in ids
    assert "text.pop_in_word" in ids
    assert "insert.face_grid" in ids  # beta


def test_broken_file_does_not_crash(tmp_path):
    _write_dummy(tmp_path, "text.ok_dummy", "text")
    (tmp_path / "text" / "rusak.py").write_text("ini bukan python valid {{{")
    reg = EffectRegistry(tmp_path, ASSETS).load()
    assert "text.ok_dummy" in reg.all_ids()
    assert len(reg.errors) == 1
    assert reg.errors[0][0].name == "rusak.py"


def test_new_effect_detected_without_core_change(tmp_path):
    reg = EffectRegistry(tmp_path, ASSETS).load()
    assert reg.all_ids() == []
    _write_dummy(tmp_path, "overlay.dummy_baru", "overlay")
    reg2 = EffectRegistry(tmp_path, ASSETS).load()
    assert reg2.all_ids() == ["overlay.dummy_baru"]


def test_missing_meta_skipped(tmp_path):
    (tmp_path / "text").mkdir(parents=True)
    (tmp_path / "text" / "tanpa_meta.py").write_text("X = 1\n")
    reg = EffectRegistry(tmp_path, ASSETS).load()
    assert reg.all_ids() == []
    assert len(reg.errors) == 1


def test_describe_filters(tmp_path):
    _write_dummy(tmp_path, "text.a", "text", status="stable")
    _write_dummy(tmp_path, "text.b", "text", status="disabled")
    _write_dummy(tmp_path, "text.c", "text", aspects='["16:9"]')
    reg = EffectRegistry(tmp_path, ASSETS).load()
    desc = reg.describe("9:16")
    assert "text.a" in desc
    assert "text.b" not in desc      # disabled tidak ditawarkan
    assert "text.c" not in desc      # tak dukung 9:16
    desc16 = reg.describe("16:9")
    assert "text.c" in desc16
    # allowed / denied
    assert "text.a" not in reg.describe("9:16", allowed=["text.c"])
    assert "text.a" not in reg.describe("9:16", denied=["text.a"])


def test_fingerprint_stable_and_sensitive(tmp_path):
    fp = _write_dummy(tmp_path, "text.a", "text")
    r1 = EffectRegistry(tmp_path, ASSETS).load().fingerprint()
    r2 = EffectRegistry(tmp_path, ASSETS).load().fingerprint()
    assert r1 == r2
    fp.write_text(fp.read_text().replace("0.5", "0.7"))  # ubah default
    r3 = EffectRegistry(tmp_path, ASSETS).load().fingerprint()
    assert r3 != r1


def test_build_clamps_params(tmp_path):
    _write_dummy(tmp_path, "text.a", "text")
    reg = EffectRegistry(tmp_path, ASSETS).load()
    seen: dict = {}

    orig = reg.entries["text.a"].module.build

    def spy(ctx, at, params):
        seen.update(params)
        return orig(ctx, at, params)

    reg.entries["text.a"].module.build = spy
    import app.canvas as canvas_mod
    ctx = EffectContext(canvas=canvas_mod.Canvas.from_aspect("9:16"),
                        source=None, words=[], work_dir=tmp_path,
                        assets_dir=ASSETS, config={}, face_track=None)
    reg.build("text.a", ctx, None,
              {"x": 99.0, "tak_dikenal": 1})   # 99 -> jepit ke 1.0
    assert seen["x"] == pytest.approx(1.0)
    assert "tak_dikenal" not in seen
    reg.build("text.a", ctx, None, {})          # default dipakai
    assert seen["x"] == pytest.approx(0.5)


def test_offerable_reasons(tmp_path):
    _write_dummy(tmp_path, "text.a", "text", aspects='["16:9"]')
    reg = EffectRegistry(tmp_path, ASSETS).load()
    ok, why = reg.offerable("text.a", "9:16")
    assert ok is False and why == "tak mendukung 9:16"
    ok, why = reg.offerable("text.a", "16:9")
    assert ok is True and why == "ok"
