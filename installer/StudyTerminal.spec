# PyInstaller build spec for the Windows desktop app.  Built by scripts\build-installer.ps1 (run from the repo root).
from pathlib import Path
# One-folder build: faster start-up than one-file, and Inno Setup compresses it anyway.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is provided by PyInstaller
BACKEND = ROOT / "backend"

datas = [
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(ROOT / "extension"), "extension"),
    (str(BACKEND / "app" / "news" / "bls_schedule.json"), "app/news"),
    (str(BACKEND / "app" / "futures" / "prop_presets.json"), "app/futures"),
    (str(BACKEND / "app" / "futures" / "bundled_research.json"), "app/futures"),
]
for pkg in ("exchange_calendars", "tzdata", "yfinance", "certifi", "win11toast"):
    datas += collect_data_files(pkg)
# The OCR package, with its .py files as well as its models and config. Two reasons, both learned the hard way in
# 0.18.1: (1) older releases import their three worker modules by a name read out of config.yaml at run time, which
# this tool cannot see, and copying only the DATA left folders named ch_ppocr_v3_det etc. with no code in them -- they
# then imported as empty namespace packages and OCR failed with "has no attribute 'TextDetector'"; (2) shipping the
# real source next to the data means that dynamic import finds actual code even if a future version brings the trick
# back. requirements.txt pins a version that imports normally, and this is the belt to that pair of braces.
datas += collect_data_files("rapidocr_onnxruntime", include_py_files=True)

hidden = collect_submodules("app") + [
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.websockets_impl", "uvicorn.lifespan.on",
    "webview.platforms.edgechromium", "pystray._win32", "win11toast", "winsound",
    "sklearn.ensemble", "sklearn.linear_model", "sklearn.inspection", "sklearn.impute",
    "onnxruntime", "exchange_calendars.exchange_calendar_xnys", "windows_capture",
    # Everything inside the OCR package, so the packaging tool analyses each worker module and pulls in what they
    # import (pyclipper, shapely, yaml) instead of silently leaving the reader half-built.
    *collect_submodules("rapidocr_onnxruntime"),
    "pyclipper", "shapely", "shapely.geometry", "yaml",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "desktop" / "launcher.py")],
    pathex=[str(BACKEND)],
    datas=datas,
    binaries=collect_dynamic_libs("windows_capture"),   # Windows Graphics Capture native library (empty when not installed)
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="StudyTerminal", console=False,
    icon=str(ROOT / "desktop" / "assets" / "study-terminal.ico"),
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="StudyTerminal")  # noqa: F821
