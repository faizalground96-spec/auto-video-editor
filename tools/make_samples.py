"""make_samples.py — membuat video uji sintetis kecil untuk pytest.

Kombinasi: vertikal, horizontal, persegi, metadata rotasi, VFR, tanpa audio.
Dipakai agar uji tidak bergantung pada video milik pemilik.
Ukuran kecil & durasi 3 detik supaya pytest cepat.

Contoh:
    python3 tools/make_samples.py --out tests/fixtures/samples
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.utils import find_ffmpeg  # noqa: E402

DUR = 3  # detik


def _run(args: list[str]) -> None:
    ffmpeg = str(find_ffmpeg())
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"] + args
    print("+", " ".join(cmd[-6:]))
    subprocess.run(cmd, check=True)


def _patch_tkhd_rotation(mp4: Path, angle: int = 90) -> None:
    """Tulis display matrix rotasi ke box tkhd (gaya video ponsel modern).

    FFmpeg 8.1 tidak lagi menulis tag 'rotate' ke MP4 (-metadata rotate
    diabaikan; -display_rotation berperilaku sebagai opsi input), jadi
    matriks display ditulis manual ke tkhd. Hasilnya setara dengan yang
    ditulis iPhone/Android untuk video portrait.
    """
    import struct
    data = bytearray(mp4.read_bytes())

    def boxes(buf, start, end):
        i = start
        while i + 8 <= end:
            size = struct.unpack(">I", buf[i:i + 4])[0]
            typ = bytes(buf[i + 4:i + 8])
            hdr = 8
            if size == 1:
                size = struct.unpack(">Q", buf[i + 8:i + 16])[0]
                hdr = 16
            elif size == 0:
                size = end - i
            yield typ, i, i + size, i + hdr
            if size <= 0:
                break
            i += size

    def s32(x: int) -> int:  # unsigned -> signed 32-bit untuk struct '>i'
        return x - 0x100000000 if x > 0x7FFFFFFF else x

    # Matriks fixed-point 16.16 (elemen terakhir 2.30), gaya iPhone.
    if angle == 90:
        m = [0, 0x00010000, 0, 0xFFFF0000, 0, 0, 0, 0, 0x40000000]
    elif angle == 270:
        m = [0, 0xFFFF0000, 0, 0x00010000, 0, 0, 0, 0, 0x40000000]
    elif angle == 180:
        m = [0xFFFF0000, 0, 0, 0, 0xFFFF0000, 0, 0, 0, 0x40000000]
    else:
        raise ValueError(f"sudut tak didukung: {angle}")
    mat = struct.pack(">9i", *[s32(x) for x in m])

    patched = 0
    for typ, _bs, be, content in boxes(data, 0, len(data)):
        if typ != b"moov":
            continue
        for t2, _s2, e2, c2 in boxes(data, content, be):
            if t2 != b"trak":
                continue
            for t3, _s3, _e3, c3 in boxes(data, c2, e2):
                if t3 != b"tkhd":
                    continue
                ver = data[c3]
                assert ver == 0, f"tkhd version {ver} tak didukung"
                off = c3 + 40  # matriks mulai 40 byte setelah awal isi tkhd
                data[off:off + 36] = mat
                patched += 1
    assert patched >= 1, "tidak ada box tkhd ditemukan"
    mp4.write_bytes(bytes(data))
    print(f"  tkhd dipatch ({patched} track), rotasi {angle} derajat")


def make(out: Path, name: str, size: str, extra_vf: str = "",
         audio: bool = True, rotate: int = 0, vfr: bool = False) -> Path:
    """Buat satu video sintetis (testsrc + nada sinus)."""
    fp = out / f"{name}.mp4"
    vf = f"testsrc=size={size}:rate=30:duration={DUR}"
    if extra_vf:
        vf += f",{extra_vf}"
    args = ["-f", "lavfi", "-i", vf]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={DUR}"]
        args += ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-shortest"]
    else:
        args += ["-map", "0:v", "-an"]
    if vfr:
        # Geser timestamp tak beraturan (satuan detik -> /TB) => VFR asli.
        # Tanpa /TB, offset 0.02 diartikan satuan timebase (~mikrodetik)
        # sehingga file tetap CFR — bug yang sempat terjadi.
        args += ["-vf", "setpts='N/30/TB+mod(N,7)*0.02/TB'",
                 "-vsync", "vfr"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             str(fp)]
    _run(args)
    if rotate:
        _patch_tkhd_rotation(fp, rotate)
    return fp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tests/fixtures/samples")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    made = []
    made.append(make(out, "vertical", "540x960"))
    made.append(make(out, "horizontal", "960x540"))
    made.append(make(out, "square", "640x640"))
    made.append(make(out, "rotated", "960x540", rotate=90))  # tampil vertikal
    made.append(make(out, "vfr", "640x360", vfr=True))
    made.append(make(out, "noaudio", "540x960", audio=False))
    made.append(make(out, "spasi dan unicode — tes", "640x360"))

    print(f"\n{len(made)} video dibuat di {out}:")
    for m in made:
        print(" ", m.name)


if __name__ == "__main__":
    main()
