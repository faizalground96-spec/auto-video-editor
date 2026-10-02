"""Uji app/probe.py dan app/utils.py — tanpa jaringan, tanpa API key."""
import logging
from pathlib import Path

import pytest

from app.probe import _rotation_of, probe
from app.utils import ff_filter_path, redact, setup_logging

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.make_samples import make  # noqa: E402


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    out = tmp_path_factory.mktemp("samples")
    return {
        "vertical": make(out, "vertical", "540x960"),
        "horizontal": make(out, "horizontal", "960x540"),
        "square": make(out, "square", "640x640"),
        "rotated": make(out, "rotated", "960x540", rotate=90),
        "vfr": make(out, "vfr", "640x360", vfr=True),
        "noaudio": make(out, "noaudio", "540x960", audio=False),
        "unicodé spasi": make(out, "unicodé spasi", "640x360"),
    }


def test_orientation_vertical(samples):
    i = probe(samples["vertical"])
    assert (i.width, i.height) == (540, 960)
    assert i.orientation == "vertical"
    assert i.has_audio and not i.is_vfr


def test_orientation_horizontal(samples):
    i = probe(samples["horizontal"])
    assert i.orientation == "horizontal"
    assert i.aspect_ratio() == pytest.approx(16 / 9)


def test_orientation_square(samples):
    i = probe(samples["square"])
    assert i.orientation == "square"


def test_rotation_metadata_detected(samples):
    # 960x540 + matriks rotasi 90° (gaya ponsel) -> tampil 540x960 vertikal
    i = probe(samples["rotated"])
    assert i.rotation in (90, 270), f"rot={i.rotation}"
    assert (i.width, i.height) == (540, 960)
    assert i.orientation == "vertical"


def test_vfr_detected(samples):
    assert probe(samples["vfr"]).is_vfr is True
    assert probe(samples["vertical"]).is_vfr is False


def test_no_audio_ok(samples):
    i = probe(samples["noaudio"])
    assert i.has_audio is False
    assert i.duration > 0


def test_space_and_unicode_path(samples):
    i = probe(samples["unicodé spasi"])
    assert i.duration > 0


def test_rotation_of_unit():
    assert _rotation_of({"tags": {"rotate": "90"}}) == 90
    assert _rotation_of({"tags": {"rotate": "270"}}) == 270
    assert _rotation_of({"side_data_list": [{"rotation": -90}]}) == 270
    assert _rotation_of({"side_data_list": [{"rotation": 180.0}]}) == 180
    assert _rotation_of({}) == 0
    assert _rotation_of({"tags": {"rotate": "0"}}) == 0


def test_probe_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        probe(tmp_path / "tidak-ada.mp4")


def test_redact_api_key():
    fake = "AIzaSy" + "X" * 33
    assert fake not in redact(f"key={fake}")
    assert "[REDACTED_API_KEY]" in redact(f"key={fake}")
    assert redact("tidak ada key") == "tidak ada key"


def test_log_redaction(tmp_path):
    logdir = tmp_path / "logs"
    logger = setup_logging(logdir)
    fake = "AIzaSy" + "Y" * 33
    logger.info("mencoba key %s di sini", fake)
    for h in logger.handlers:
        h.flush()
    content = (logdir / "app.log").read_text(encoding="utf-8")
    assert fake not in content
    assert "[REDACTED_API_KEY]" in content


def test_ff_filter_path_windows_style():
    # C:\x\y.ass -> C\:/x/y.ass  (drive colon di-escape, backslash jadi slash)
    assert ff_filter_path("C:\\x\\y.ass") == "C\\:/x/y.ass"
    assert ff_filter_path("/tmp/a b/c.ass") == "/tmp/a b/c.ass"
