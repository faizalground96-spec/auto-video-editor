"""Uji QA: cek individual dengan video sintetis."""
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.canvas import Canvas  # noqa: E402
from app.probe import probe  # noqa: E402
from app.qa import (QACtx, check_blackframes, check_density, check_format,  # noqa: E402
                    make_contact_sheet)
from app.utils import find_ffmpeg, resource_path  # noqa: E402

ROOT = resource_path(".")
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def vid1920(tmp_path_factory):
    out = tmp_path_factory.mktemp("qa") / "v.mp4"
    subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=30:duration=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset",
         "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(out)], check=True)
    return out


def _qctx(**kw):
    base = dict(output=None, source=None, source_info=None,
                canvas=Canvas.from_aspect("9:16"), config=CFG,
                edl=SimpleNamespace(
                    global_=SimpleNamespace(intensity="medium"),
                    segments=[]),
                registry=None, face_track=None, smart_crop_curve=None,
                ass_path=None, sfx_cues=[])
    base.update(kw)
    return QACtx(**base)


def test_check_format_lulus(vid1920):
    q = _qctx(output=vid1920, source=vid1920, source_info=probe(vid1920))
    r = check_format(q)
    assert r["status"] == "pass", r


def test_check_format_gagal_resolusi(vid1920, tmp_path):
    q = _qctx(output=vid1920, source=vid1920, source_info=probe(vid1920),
              canvas=Canvas.from_aspect("16:9"))
    r = check_format(q)
    assert r["status"] == "fail" and "resolusi" in r["detail"]


def test_check_blackframes_hitam_di_sumber_lulus(tmp_path):
    ff = str(find_ffmpeg())
    mk = lambda name, filt: subprocess.run(
        [ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "testsrc=size=320x240:rate=30:duration=2", "-vf", filt,
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         str(tmp_path / name)], check=True)
    # 0,5 dtk hitam di awal, ada di sumber DAN output -> lulus
    black0 = "drawbox=x=0:y=0:w=iw:h=ih:c=black:t=fill:enable='lt(t,0.5)'"
    mk("src.mp4", black0)
    mk("out.mp4", black0)
    q = _qctx(output=tmp_path / "out.mp4", source=tmp_path / "src.mp4")
    assert check_blackframes(q)["status"] == "pass"
    # hitam hanya di output -> gagal
    mk("out2.mp4", black0 + ",drawbox=x=0:y=0:w=iw:h=ih:c=black:t=fill:"
                       "enable='between(t,1.0,1.6)'")
    q2 = _qctx(output=tmp_path / "out2.mp4", source=tmp_path / "src.mp4")
    r = check_blackframes(q2)
    assert r["status"] == "fail", r


class _StrongReg:
    def get(self, eid):
        return SimpleNamespace(meta=SimpleNamespace(strong=True))


class _CalmReg:
    def get(self, eid):
        return SimpleNamespace(meta=SimpleNamespace(strong=False))


def _edl_strong(n):
    segs = [SimpleNamespace(
        start=0.0, end=10.0,
        effects=[SimpleNamespace(id="x", at=float(i), params={})
                 for i in range(n)])]
    return SimpleNamespace(global_=SimpleNamespace(intensity="medium"),
                           segments=segs)


def test_check_density(vid1920):
    q = _qctx(output=vid1920, source=vid1920, source_info=probe(vid1920),
              registry=_CalmReg(), edl=_edl_strong(9))
    assert check_density(q)["status"] == "pass"  # tak ada efek kuat
    q2 = _qctx(output=vid1920, source=vid1920, source_info=probe(vid1920),
               registry=_StrongReg(), edl=_edl_strong(9))
    r = check_density(q2)
    assert r["status"] == "fail" and r["metrics"]["worst"] == 9, r
    q3 = _qctx(output=vid1920, source=vid1920, source_info=probe(vid1920),
               registry=_StrongReg(), edl=_edl_strong(2))
    assert check_density(q3)["status"] == "pass"


def test_make_contact_sheet(vid1920, tmp_path):
    dest = tmp_path / "sheet.jpg"
    make_contact_sheet(vid1920, dest)
    assert dest.is_file() and dest.stat().st_size > 5_000
