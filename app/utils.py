"""utils.py — logging (dengan redaksi API key), path, dan pembungkus FFmpeg."""
from __future__ import annotations

import logging
import logging.handlers
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Redaksi rahasia di log
# ---------------------------------------------------------------------------
_API_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{30,}")


def redact(text: str) -> str:
    """Samarkan pola API key Google (AIza...) dari teks apa pun."""
    return _API_KEY_RE.sub("[REDACTED_API_KEY]", text)


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            try:
                record.args = tuple(
                    redact(a) if isinstance(a, str) else a for a in record.args
                )
            except TypeError:
                pass
        return True


def setup_logging(log_dir: Path, level: int = logging.INFO) -> logging.Logger:
    """Logging ke logs/app.log (rotasi) + console, selalu dengan redaksi key."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("autovideoeditor")
    logger.setLevel(level)
    logger.addFilter(_RedactFilter())
    if not logger.handlers:
        fh = logging.handlers.RotatingFileHandler(
            log_dir / "app.log", maxBytes=2_000_000, backupCount=3,
            encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        fh.addFilter(_RedactFilter())
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        ch.addFilter(_RedactFilter())
        logger.addHandler(fh)
        logger.addHandler(ch)
    return logger


log = logging.getLogger("autovideoeditor")


# ---------------------------------------------------------------------------
# Quirk VPS: sanitasi no_proxy agar httpx tidak crash
# ---------------------------------------------------------------------------
def sanitize_proxy_env() -> None:
    """Buang entri IPv6 bracket ([::1]) dari no_proxy/NO_PROXY.

    Tanpa ini, SEMUA library berbasis httpx (google-genai, huggingface_hub)
    gagal dengan `InvalidURL: Invalid port: ':1]'`.
    Proxy egress sendiri tetap dipakai.
    """
    for var in ("no_proxy", "NO_PROXY"):
        val = os.environ.get(var, "")
        if "[" in val:
            cleaned = ",".join(p for p in val.split(",") if "[" not in p)
            os.environ[var] = cleaned
            log.debug("sanitize_proxy_env: %s dibersihkan", var)


# ---------------------------------------------------------------------------
# Path: dev vs frozen (PyInstaller)
# ---------------------------------------------------------------------------
def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def resource_path(rel: str | Path) -> Path:
    """Path ke file read-only bawaan aplikasi (catalog/, assets/, ...).

    Mode frozen: di dalam bundel PyInstaller (sys._MEIPASS).
    Mode dev: relatif terhadap root proyek (folder di atas app/).
    """
    rel = Path(rel)
    if is_frozen():
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent
    return base / rel


def app_dirs() -> dict[str, Path]:
    """Folder yang bisa ditulis: work/, output/, logs/, .env.

    Aturan: data TIDAK BOLEH di dalam bundel aplikasi.
    - Mode frozen: folder `data/` portabel di samping exe bila bisa ditulis,
      cadangan %LOCALAPPDATA%/AutoVideoEditor (Windows) atau
      ~/.local/share/autovideoeditor (Linux).
    - Mode dev: folder di root proyek.
    """
    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        portable = exe_dir / "data"
        try:
            portable.mkdir(parents=True, exist_ok=True)
            test = portable / ".writetest"
            test.touch()
            test.unlink()
            base = portable
        except OSError:
            if os.name == "nt":
                base = Path(os.environ.get("LOCALAPPDATA", str(exe_dir)))
                base = base / "AutoVideoEditor"
            else:
                base = Path.home() / ".local" / "share" / "autovideoeditor"
            base.mkdir(parents=True, exist_ok=True)
    else:
        base = Path(__file__).resolve().parent.parent
    return {
        "base": base,
        "work": base / "work",
        "output": base / "output",
        "logs": base / "logs",
    }


# ---------------------------------------------------------------------------
# FFmpeg
# ---------------------------------------------------------------------------
def find_ffmpeg() -> Path:
    """Cari ffmpeg: bin/ffmpeg(.exe) dulu (bundel Windows), lalu PATH."""
    candidates = []
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        # PyInstaller one-folder: datas ada di _internal/ (sys._MEIPASS),
        # tapi cek juga di samping exe untuk jaga-jaga.
        candidates.append(Path(sys._MEIPASS) / "bin" / name)  # type: ignore[attr-defined]
        candidates.append(exe_dir / "bin" / name)
    else:
        exe_dir = Path(__file__).resolve().parent.parent
        candidates.append(exe_dir / "bin" / name)
    which = shutil.which("ffmpeg")
    if which:
        candidates.append(Path(which))
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(
        "ffmpeg tidak ditemukan di bin/ maupun PATH. "
        "Lihat README (bagian masalah umum)."
    )


def ff_filter_path(path: str | Path) -> str:
    """Escape path agar aman dipakai di dalam argumen filter FFmpeg.

    Contoh: C:\\x\\y.ass -> C\\:/x/y.ass ; spasi dan ':' di-escape.
    Alternatif yang lebih aman: jalankan FFmpeg dengan cwd=folder kerja
    dan pakai path relatif (lihat write_filter_script).
    """
    p = str(path).replace("\\", "/")
    # escape ':' (kecuali pola drive 'X:/' -> 'X\\:/'), "'", dan spasi opsional
    p = p.replace(":", "\\:")
    p = p.replace("'", "\\'")
    return p


def write_filter_script(filtergraph: str, work_dir: Path,
                        name: str = "filter.txt") -> Path:
    """Tulis filtergraph panjang ke file (untuk -filter_complex_script).

    Windows membatasi panjang baris perintah (~8191 karakter), jadi
    filtergraph panjang tidak boleh lewat argumen langsung.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    fp = work_dir / name
    fp.write_text(filtergraph, encoding="utf-8")
    return fp


def run_ffmpeg(
    args: list[str],
    on_progress: Optional[Callable[[float], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    cwd: Optional[Path] = None,
    timeout: Optional[float] = None,
    ffmpeg_bin: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    """Jalankan FFmpeg dengan -progress pipe:1.

    - on_progress(seconds): dipanggil berkala dengan out_time_ms/1e6.
    - cancel_event: bila diset, proses dibunuh bersih lalu raise CancelledError.
    - stderr ditangkap dan ditulis ke log (dengan redaksi).
    """
    binary = str(ffmpeg_bin or find_ffmpeg())
    cmd = [binary, "-hide_banner", "-nostats", "-progress", "pipe:1",
           "-y"] + args
    log.debug("run_ffmpeg: %s", redact(" ".join(cmd)))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(cwd) if cwd else None, text=True, bufsize=1,
    )
    out_time = 0.0
    stderr_tail: list[str] = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                raise CancelledError("FFmpeg dibatalkan pengguna")
            line = line.strip()
            if line.startswith("out_time_ms="):
                try:
                    out_time = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    pass
                if on_progress:
                    on_progress(out_time)
            elif line == "progress=end":
                break
        _, stderr = proc.communicate(timeout=timeout)
        stderr_tail = (stderr or "").splitlines()[-30:]
    except CancelledError:
        raise
    except Exception:
        proc.kill()
        _, stderr = proc.communicate()
        stderr_tail = (stderr or "").splitlines()[-30:]
        raise
    if proc.returncode != 0:
        log.error("ffmpeg gagal (rc=%s):\n%s",
                  proc.returncode, redact("\n".join(stderr_tail)))
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, output=None,
            stderr="\n".join(stderr_tail))
    return subprocess.CompletedProcess(cmd, proc.returncode)


class CancelledError(Exception):
    """Dilempar saat pengguna membatalkan proses FFmpeg."""
