"""Uji app/canvas.py — tanpa jaringan, tanpa API key."""
import math

import pytest

from app.canvas import (
    CANVAS_SPECS,
    SAFE_AREAS,
    Canvas,
    resolve_aspect,
)


def test_resolve_aspect_explicit():
    assert resolve_aspect("9:16", 16 / 9) == "9:16"
    assert resolve_aspect("16:9", 9 / 16) == "16:9"
    assert resolve_aspect("1:1", 2.0) == "1:1"
    assert resolve_aspect("4:5", 2.0) == "4:5"
    with pytest.raises(ValueError):
        resolve_aspect("3:2", 1.5)


def test_resolve_aspect_auto_nearest():
    assert resolve_aspect("auto", 9 / 16) == "9:16"
    assert resolve_aspect("auto", 0.5) == "9:16"      # 0.5 dekat 0.5625
    assert resolve_aspect("auto", 16 / 9) == "16:9"
    assert resolve_aspect("auto", 2.0) == "16:9"
    assert resolve_aspect("auto", 1.0) == "1:1"
    assert resolve_aspect("auto", 0.8) == "4:5"
    assert resolve_aspect("auto", 0.75) == "4:5"      # 0.75 dekat 0.8


def test_resolve_aspect_auto_tie_goes_16_9():
    # 4/3 berjarak log sama persis ke 1:1 dan 16:9 -> aturan: 16:9 menang
    r = 4 / 3
    d1 = abs(math.log(r) - math.log(1.0))
    d2 = abs(math.log(r) - math.log(16 / 9))
    assert abs(d1 - d2) < 1e-12
    assert resolve_aspect("auto", r) == "16:9"


def test_canvas_specs_match_plan():
    assert CANVAS_SPECS["9:16"]["width"] == 1080
    assert CANVAS_SPECS["9:16"]["height"] == 1920
    assert CANVAS_SPECS["16:9"]["width"] == 1920
    assert CANVAS_SPECS["1:1"]["width"] == 1080
    assert CANVAS_SPECS["4:5"] == {"width": 1080, "height": 1350,
                                  "orientation": "vertical",
                                  "layout": "vertical"}


def test_safe_areas_match_plan():
    assert SAFE_AREAS["9:16"] == (0.12, 0.22, 0.06)
    assert SAFE_AREAS["16:9"] == (0.05, 0.05, 0.05)
    assert SAFE_AREAS["1:1"] == (0.06, 0.06, 0.06)
    assert SAFE_AREAS["4:5"] == (0.06, 0.06, 0.06)


def test_canvas_helpers_9_16():
    c = Canvas.from_aspect("9:16")
    assert (c.width, c.height) == (1080, 1920)
    assert c.w(0.5) == 540
    assert c.h(0.5) == 960
    assert c.font_px(0.042) == 81          # 0.042 * 1920 = 80.64 -> 81
    x, y, w, h = c.safe_rect()
    assert x == c.w(0.06) and w == 1080 - 2 * x
    assert y == c.h(0.12)
    assert h == 1920 - c.h(0.12) - c.h(0.22)
    # safe rect di dalam kanvas
    assert x >= 0 and y >= 0 and x + w <= 1080 and y + h <= 1920


def test_font_px_uses_height():
    c = Canvas.from_aspect("16:9")
    # font 5.5% tinggi kanvas 1080 = 59.4 -> 59
    assert c.font_px(0.055) == 59


def test_point():
    c = Canvas.from_aspect("1:1")
    assert c.point(0.5, 0.25) == (540, 270)
