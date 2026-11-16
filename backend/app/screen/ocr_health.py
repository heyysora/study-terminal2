"""Is the text reader actually working, and if not, what exactly is wrong?

Why this exists. RapidOCR does not import its three worker modules by name in the source: it reads the names out of
its own config.yaml at run time and imports them by string. A tool that packages the app into an .exe reads source
code to decide what to include, so it cannot see those names, and it left them out. The packaged app still had
*folders* with those names (their data files were copied), so Python imported each folder as an empty module and the
first thing asked of it failed with "module 'ch_ppocr_v3_det' has no attribute 'TextDetector'".

Nothing in a source checkout can catch that -- the real files are sitting right there. So this check reads the module
names out of the same config the library reads, imports each one the same way the library does, and insists each is a
real module with the class in it. Then it loads the engine and reads a picture of known text. Run inside the packaged
app (scripts/windows-reliability.ps1 does, and CI fails the release if it doesn't pass), it is the only thing that
proves the installed app can read your chart.

Never raises: every step returns pass/fail with the real exception text.
"""
from __future__ import annotations

import importlib
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PASS, FAIL, SKIP = "pass", "fail", "skipped"
# What the test image says. Digits and capitals only: the chart text that matters is a contract code and a price.
SAMPLE_TEXT = "NQZ26 27686"


@dataclass
class Step:
    id: str
    name: str
    status: str
    detail: str = ""
    data: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "status": self.status, "detail": self.detail, **({"data": self.data} if self.data else {})}


def _fail_detail(e: BaseException) -> str:
    return f"{type(e).__name__}: {str(e).strip().splitlines()[0][:200]}" if str(e).strip() else type(e).__name__


def _pkg_version(pkg) -> str:
    """The installed version, or failing that something more useful than "unknown". Inside a packaged .exe there may
    be no metadata to read, and the whole point of reporting a version here is to tell apart the release whose
    modules are loaded by a run-time name from the one that imports them normally -- which the folder layout says
    plainly even when nothing else does."""
    try:
        from importlib.metadata import version as _v
        return _v("rapidocr_onnxruntime")
    except Exception:  # noqa: BLE001
        pass
    v = getattr(pkg, "__version__", None)
    if v:
        return str(v)
    try:
        names = {d.name for d in Path(pkg.__file__).resolve().parent.iterdir() if d.is_dir()}
    except Exception:  # noqa: BLE001
        return "unknown"
    if "ch_ppocr_v3_det" in names:
        return "unknown (1.2/1.3 layout: modules loaded by name at run time)"
    if "ch_ppocr_det" in names:
        return "unknown (1.4 layout: modules imported normally)"
    return "unknown"


def _sample_image():
    """A picture of SAMPLE_TEXT: dark background, light text, the same way a trading chart draws it."""
    import cv2
    import numpy as np
    img = np.full((80, 460, 3), 18, dtype=np.uint8)
    cv2.putText(img, SAMPLE_TEXT, (14, 54), cv2.FONT_HERSHEY_SIMPLEX, 1.25, (236, 238, 242), 2, cv2.LINE_AA)
    return img


def _read_config(pkg) -> tuple[dict, Path | None]:
    """RapidOCR's own config.yaml -- the file it takes its module names and model paths from."""
    root = Path(pkg.__file__).resolve().parent
    path = root / "config.yaml"
    if not path.exists():
        return {}, None
    import yaml
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}, path


def check(deep: bool = True) -> dict:
    """Every stage of the text reader, in the order they have to work. deep=False stops before loading the engine
    (fast enough for a page load); deep=True also loads it and reads a known picture (a second or two)."""
    t0 = time.monotonic()
    steps: list[Step] = []
    versions: dict[str, Any] = {"python": sys.version.split()[0], "frozen": bool(getattr(sys, "frozen", False))}

    # 1. the library imports at all
    try:
        pkg = importlib.import_module("rapidocr_onnxruntime")
        versions["rapidocr_onnxruntime"] = _pkg_version(pkg)
        steps.append(Step("import", "Text reader installed", PASS, f"rapidocr_onnxruntime {versions['rapidocr_onnxruntime']}"))
    except Exception as e:  # noqa: BLE001
        steps.append(Step("import", "Text reader installed", FAIL, _fail_detail(e)))
        return _result(steps, versions, t0, "The text reader isn't installed in this copy of Study Terminal. Reinstall it.")

    for mod in ("onnxruntime", "cv2", "yaml"):
        try:
            m = importlib.import_module(mod)
            versions[mod] = getattr(m, "__version__", "unknown")
        except Exception as e:  # noqa: BLE001
            steps.append(Step(f"dep:{mod}", f"{mod} available", FAIL, _fail_detail(e)))

    # 2. its config, which is where the module names live
    try:
        config, cfg_path = _read_config(pkg)
        if not config:
            steps.append(Step("config", "Reader settings file", FAIL, "config.yaml is missing from the installed text reader"))
            return _result(steps, versions, t0, "Part of the text reader is missing from this install. Reinstall Study Terminal.")
        steps.append(Step("config", "Reader settings file", PASS, str(cfg_path.name)))
    except Exception as e:  # noqa: BLE001
        steps.append(Step("config", "Reader settings file", FAIL, _fail_detail(e)))
        return _result(steps, versions, t0, "The text reader's settings file couldn't be read. Reinstall Study Terminal.")

    # 3. THE BUG: each worker module named in that config, imported the way the library imports it
    root = Path(pkg.__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.append(str(root))                      # exactly what rapidocr does on import
    named = [(sec, (config.get(sec) or {}).get("module_name"), (config.get(sec) or {}).get("class_name"))
             for sec in ("Det", "Rec", "Cls")]
    for sec, mod_name, cls_name in named:
        if not mod_name or not cls_name:
            steps.append(Step(f"module:{sec}", f"{sec} module", SKIP, "not named in the settings file"))
            continue
        label = f"{sec} module ({mod_name}.{cls_name})"
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:  # noqa: BLE001
            steps.append(Step(f"module:{sec}", label, FAIL, f"won't import -- {_fail_detail(e)}"))
            continue
        spec_file = getattr(mod, "__file__", None)
        if not spec_file:
            # An empty folder imported as a namespace package: the exact shape of the 0.18.1 fault.
            steps.append(Step(f"module:{sec}", label, FAIL,
                              "imported as an empty folder with no code in it (the packaged build is missing this module)",
                              {"namespace_package": True, "search_path": list(getattr(mod, "__path__", []) or [])[:3]}))
            continue
        if not hasattr(mod, cls_name):
            steps.append(Step(f"module:{sec}", label, FAIL, f"module loaded but has no {cls_name} (version mismatch)",
                              {"file": Path(spec_file).name, "has": sorted(a for a in vars(mod) if not a.startswith('_'))[:8]}))
            continue
        steps.append(Step(f"module:{sec}", label, PASS, Path(spec_file).name))

    # 4. model files on disk
    for sec, _m, _c in named:
        rel = (config.get(sec) or {}).get("model_path")
        if not rel:
            continue
        p = Path(rel)
        p = p if p.is_absolute() else root / rel
        if p.exists() and p.stat().st_size > 1024:
            steps.append(Step(f"model:{sec}", f"{sec} model file", PASS, f"{p.name} ({p.stat().st_size // 1024} KB)"))
        else:
            steps.append(Step(f"model:{sec}", f"{sec} model file", FAIL, f"missing or empty: {p}"))

    if any(s.status == FAIL for s in steps):
        return _result(steps, versions, t0, _advice(steps))
    if not deep:
        steps.append(Step("engine", "Reader starts", SKIP, "quick check only"))
        return _result(steps, versions, t0, "")

    # 5. the engine actually starts
    try:
        engine = pkg.RapidOCR()
        steps.append(Step("engine", "Reader starts", PASS))
    except Exception as e:  # noqa: BLE001
        log.exception("OCR engine failed to start")
        steps.append(Step("engine", "Reader starts", FAIL, _fail_detail(e)))
        return _result(steps, versions, t0, _advice(steps))

    # 6. and reads known text out of a picture
    try:
        res, _ = engine(_sample_image())
        got = " ".join((t or "").strip() for _b, t, _c in (res or []))
        digits = "".join(c for c in got if c.isdigit())
        ok = "27686" in digits.replace(" ", "")
        steps.append(Step("recognize", "Reads text from a picture", PASS if ok else FAIL,
                          f"read {got!r} from an image saying {SAMPLE_TEXT!r}" if got else "read nothing from a clear test image"))
    except Exception as e:  # noqa: BLE001
        log.exception("OCR recognition test failed")
        steps.append(Step("recognize", "Reads text from a picture", FAIL, _fail_detail(e)))

    return _result(steps, versions, t0, _advice(steps))


def _advice(steps: list[Step]) -> str:
    bad = [s for s in steps if s.status == FAIL]
    if not bad:
        return ""
    if any(s.data.get("namespace_package") for s in bad):
        return ("This copy of Study Terminal was packaged without part of its text reader. Reinstalling the latest version "
                "fixes it -- nothing on your side is wrong, and your settings and history are kept.")
    if any(s.id.startswith("model:") for s in bad):
        return "The text reader's model files are missing from this install. Reinstall Study Terminal."
    if any(s.id.startswith("module:") for s in bad):
        return ("The text reader's parts don't match each other (a version mismatch). Reinstalling the latest version of "
                "Study Terminal fixes it.")
    if any(s.id == "recognize" for s in bad):
        return "The text reader starts but can't read clear test text, so it can't be trusted with your chart. Reinstall Study Terminal."
    return "The text reader isn't working. Reinstalling Study Terminal fixes it; your settings and history are kept."


def _result(steps: list[Step], versions: dict, t0: float, advice: str) -> dict:
    bad = [s for s in steps if s.status == FAIL]
    return {"ok": not bad, "advice": advice, "took_ms": int((time.monotonic() - t0) * 1000),
            "versions": versions, "steps": [s.as_dict() for s in steps],
            "headline": "The text reader is working." if not bad else f"The text reader isn't working: {bad[0].name.lower()} failed.",
            "failed": [s.id for s in bad]}


_cached: dict | None = None


def summary(refresh: bool = False) -> dict:
    """The last result, running the check once if it hasn't run. Cached: loading the engine takes a second or two."""
    global _cached
    if _cached is None or refresh:
        _cached = check(deep=True)
    return _cached


def forget() -> None:
    global _cached
    _cached = None
