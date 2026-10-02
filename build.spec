# build.spec — PyInstaller untuk Auto Video Editor (Tahap 10).
# Mode satu folder (bukan satu file). Menghasilkan dua exe:
#   AutoVideoEditor.exe    (GUI, tanpa konsol)
#   AutoVideoEditorCLI.exe (konsol, untuk --self-test dan CLI)
# Dijalankan via build_windows.bat di Windows, atau langsung:
#   pyinstaller build.spec --noconfirm
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)

# -- data ------------------------------------------------------------------
datas = [
    (str(ROOT / "catalog"), "catalog"),
    (str(ROOT / "presets"), "presets"),
    (str(ROOT / "prompts"), "prompts"),
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "config.yaml"), "."),
]
# ffmpeg.exe (Windows) bila sudah diunduh ke bin/
ffexe = ROOT / "bin" / "ffmpeg.exe"
if ffexe.is_file():
    datas.append((str(ffexe), "bin"))

# -- hidden imports (efek dimuat dinamis via importlib) ----------------------
hidden = [
    "numpy", "cv2", "PIL", "PIL.Image", "fontTools", "yaml",
    "pydantic", "dotenv",
]
for pkg in ("numpy", "cv2", "PIL", "fontTools", "yaml"):
    try:
        hidden += collect_submodules(pkg)
    except Exception:
        pass

a_gui = Analysis(
    [str(ROOT / "app" / "gui.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    excludes=["pytest", "tkinter"],
    noarchive=False,
)
a_cli = Analysis(
    [str(ROOT / "app" / "cli.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    excludes=["pytest", "tkinter", "PySide6"],
    noarchive=False,
)

pyz_gui = PYZ(a_gui.pure)
pyz_cli = PYZ(a_cli.pure)

exe_gui = EXE(
    pyz_gui, a_gui.scripts, [],
    exclude_binaries=True,
    name="AutoVideoEditor",
    console=False,  # GUI tanpa konsol
)
exe_cli = EXE(
    pyz_cli, a_cli.scripts, [],
    exclude_binaries=True,
    name="AutoVideoEditorCLI",
    console=True,
)
coll = COLLECT(
    exe_gui, exe_cli,
    a_gui.binaries, a_gui.datas,
    a_cli.binaries, a_cli.datas,
    strip=False,
    name="AutoVideoEditor",
)
