# PyInstaller build spec for the Windows desktop app.  Built by scripts\build-installer.ps1 (run from the repo root).
from pathlib import Path
# One-folder build: faster start-up than one-file, and Inno Setup compresses it anyway.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is provided by PyInstaller
BACKEND = ROOT / "backend"

datas = [
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(ROOT / "extension"), "extension"),
    (str(BACKEND / "app" / "news" / "bls_schedule.json"), "app/news"),
]
for pkg in ("rapidocr_onnxruntime", "exchange_calendars", "tzdata", "yfinance", "certifi", "win11toast"):
    datas += collect_data_files(pkg)

hidden = collect_submodules("app") + [
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.websockets_impl", "uvicorn.lifespan.on",
    "webview.platforms.edgechromium", "pystray._win32", "win11toast", "winsound",
    "sklearn.ensemble", "sklearn.linear_model", "sklearn.inspection", "sklearn.impute",
    "onnxruntime", "exchange_calendars.exchange_calendar_xnys",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "desktop" / "launcher.py")],
    pathex=[str(BACKEND)],
    datas=datas,
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
