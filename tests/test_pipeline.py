"""Uji Tahap 9: pipeline + CLI (dry-run, from-edl, self-test)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.cli import main as cli_main  # noqa: E402
from app.pipeline import Pipeline, PipelineOptions  # noqa: E402
from app.utils import find_ffmpeg, resource_path  # noqa: E402

ROOT = resource_path(".")
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
FIX = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="module")
def src6s(tmp_path_factory):
    out = tmp_path_factory.mktemp("pipe6")
    fp = out / "p6.mp4"
    subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=540x960:rate=30:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset",
         "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(fp)], check=True)
    return fp


def test_pipeline_dry_run_fake_llm(tmp_path, src6s):
    pipe = Pipeline(CFG)
    opt = PipelineOptions(
        input=src6s, dry_run=True,
        fake_llm=FIX / "gemini_bagus.json",
        work_dir=tmp_path / "work")
    res = pipe.run(opt)
    assert res["dry_run"] is True
    assert Path(res["edl"]).is_file()
    assert Path(res["why"]).is_file()
    assert (tmp_path / "work" / "pipeline.log").is_file()
    why = Path(res["why"]).read_text(encoding="utf-8")
    assert "Gaya:" in why


def test_pipeline_from_edl(tmp_path, src6s):
    # dry-run dulu untuk dapat EDL, lalu render dari EDL itu
    pipe = Pipeline(CFG)
    w1 = tmp_path / "w1"
    r1 = pipe.run(PipelineOptions(
        input=src6s, dry_run=True,
        fake_llm=FIX / "gemini_bagus.json", work_dir=w1))
    out = tmp_path / "hasil.mp4"
    r2 = pipe.run(PipelineOptions(
        input=src6s, out=out, from_edl=Path(r1["edl"]),
        work_dir=tmp_path / "w2"))
    assert out.is_file() and out.stat().st_size > 10_000
    assert r2["qa"]["passed"]


def test_cli_self_test():
    assert cli_main(["--self-test"]) == 0


def test_cli_list_catalog(capsys):
    assert cli_main(["--list-catalog"]) == 0
    out = capsys.readouterr().out
    assert "text.pop_in_word" in out
    assert "Preset:" in out


def test_cli_dry_run(tmp_path, src6s, capsys):
    rc = cli_main([str(src6s), "--dry-run", "--fake-llm",
                   str(FIX / "gemini_bagus.json"),
                   "--work-dir", str(tmp_path / "w")])
    assert rc == 0
    assert "dry-run selesai" in capsys.readouterr().out
