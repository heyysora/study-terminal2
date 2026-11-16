"""The screen-text reader, and the trap that broke it in 0.18.1.

RapidOCR 1.2.x/1.3.x load their three worker modules by a name read out of config.yaml at run time. PyInstaller reads
source to decide what to include, so it never saw those names and left the modules out of the .exe -- while copying
the packages' DATA files, which created folders with exactly those names and no code in them. Python imported each
folder as an empty namespace package, so the import SUCCEEDED and the first attribute asked of it failed:

    AttributeError: module 'ch_ppocr_v3_det' has no attribute 'TextDetector'

Every one of these tests passes in a source checkout whether or not the bug is present -- that is the whole point and
the reason it shipped. What they pin down is that the CHECK catches it, so the packaged .exe can be asked the question
(launcher --ocr-check, run against the built app by scripts/windows-reliability.ps1, gating the release in CI).
"""
from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from app.screen import ocr_health, vision


def test_the_reader_works_here():
    """The real thing, in this environment: engine starts and reads known text out of a picture."""
    r = ocr_health.check(deep=True)
    assert r["ok"], [s for s in r["steps"] if s["status"] == "fail"]
    assert r["headline"] == "The text reader is working."
    assert r["versions"]["rapidocr_onnxruntime"] not in (None, "", "unknown")
    assert [s for s in r["steps"] if s["id"] == "recognize" and s["status"] == "pass"], "it must prove it on a picture"


def test_a_quick_check_skips_the_slow_part():
    r = ocr_health.check(deep=False)
    assert r["ok"]
    assert [s for s in r["steps"] if s["id"] == "engine" and s["status"] == "skipped"]


def test_an_empty_folder_masquerading_as_a_module_is_caught(tmp_path, monkeypatch):
    """THE 0.18.1 BUG. A folder with no code in it imports fine and answers every question with AttributeError.
    The check must call that a failure and say the build is missing a part, not blame the user's chart."""
    det = tmp_path / "ch_ppocr_fake_det"
    det.mkdir()
    (det / "config.yaml").write_text("x: 1", encoding="utf-8")        # data only, exactly what collect_data_files copies
    monkeypatch.syspath_prepend(str(tmp_path))

    fake = types.ModuleType("rapidocr_fake")
    fake.__file__ = str(tmp_path / "__init__.py")
    (tmp_path / "config.yaml").write_text(
        "Det:\n  module_name: ch_ppocr_fake_det\n  class_name: TextDetector\n  model_path: models/x.onnx\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", fake)

    r = ocr_health.check(deep=True)
    assert not r["ok"]
    bad = [s for s in r["steps"] if s["id"] == "module:Det"]
    assert bad and bad[0]["status"] == "fail"
    assert "no code in it" in bad[0]["detail"]
    assert bad[0]["data"]["namespace_package"] is True
    assert "packaged without part of its text reader" in r["advice"]
    assert "Reinstall" in r["advice"] or "reinstall" in r["advice"]


def test_a_module_that_loads_but_lacks_the_class_is_caught(tmp_path, monkeypatch):
    """The other shape of the same family: the right folder, the wrong version, so the class isn't there."""
    (tmp_path / "ch_ppocr_wrongver").mkdir()
    (tmp_path / "ch_ppocr_wrongver" / "__init__.py").write_text("class SomethingElse: pass\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    fake = types.ModuleType("rapidocr_fake2")
    fake.__file__ = str(tmp_path / "__init__.py")
    (tmp_path / "config.yaml").write_text(
        "Det:\n  module_name: ch_ppocr_wrongver\n  class_name: TextDetector\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", fake)

    r = ocr_health.check(deep=True)
    assert not r["ok"]
    bad = [s for s in r["steps"] if s["id"] == "module:Det"][0]
    assert bad["status"] == "fail" and "no TextDetector" in bad["detail"]
    assert "version mismatch" in bad["detail"] or "don't match" in r["advice"]


def test_a_missing_model_file_is_caught(tmp_path, monkeypatch):
    fake = types.ModuleType("rapidocr_fake3")
    fake.__file__ = str(tmp_path / "__init__.py")
    (tmp_path / "config.yaml").write_text("Det:\n  model_path: models/not_there.onnx\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", fake)
    r = ocr_health.check(deep=True)
    assert not r["ok"]
    assert [s for s in r["steps"] if s["id"] == "model:Det" and s["status"] == "fail"]
    assert "model files are missing" in r["advice"]


def test_the_library_not_being_installed_at_all_is_caught(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_rapidocr(name, *a, **k):
        if name == "rapidocr_onnxruntime":
            raise ImportError("No module named 'rapidocr_onnxruntime'")
        return real(name, *a, **k)
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)
    monkeypatch.setattr(builtins, "__import__", no_rapidocr)
    r = ocr_health.check(deep=True)
    assert not r["ok"] and r["steps"][0]["id"] == "import"
    assert "isn't installed" in r["advice"]


def test_the_check_never_raises(monkeypatch):
    """It runs when things are broken, so it has to survive anything."""
    broken = types.ModuleType("broken")
    broken.__file__ = "/nonexistent/path/__init__.py"
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", broken)
    r = ocr_health.check(deep=True)
    assert isinstance(r, dict) and "ok" in r and isinstance(r["steps"], list)


# ---------------------------------------------------------------- how a broken reader is reported

def test_a_broken_reader_is_its_own_error_not_a_chart_problem(monkeypatch):
    """"Make sure nothing is covering the chart" is useless advice when the reader itself is dead. The failure gets
    its own exception type carrying the repair, so the monitor and the page can say what is actually wrong."""
    monkeypatch.setattr(vision, "_OCR", None)
    monkeypatch.setattr(vision, "_OCR_FAILED", None)

    def explode():
        raise AttributeError("module 'ch_ppocr_v3_det' has no attribute 'TextDetector'")
    monkeypatch.setattr(vision, "_start_engine", lambda: explode())
    with pytest.raises(AttributeError):
        vision.ocr(np.zeros((40, 120, 3), dtype=np.uint8))

    monkeypatch.setattr(vision, "_OCR", None)
    monkeypatch.setattr(vision, "_start_engine", lambda: (_ for _ in ()).throw(vision.OcrUnavailable("AttributeError: boom", "Reinstall it.")))
    with pytest.raises(vision.OcrUnavailable) as ei:
        vision.ocr(np.zeros((40, 120, 3), dtype=np.uint8))
    assert ei.value.detail == "AttributeError: boom" and ei.value.advice == "Reinstall it."


def test_a_dead_reader_is_not_restarted_on_every_capture(monkeypatch):
    """The capture loop asks several times a second and starting the engine loads model files off disk. A broken
    reader must fail fast from memory instead of thrashing the PC."""
    monkeypatch.setattr(vision, "_OCR", None)
    monkeypatch.setattr(vision, "_OCR_FAILED", None)
    tries = {"n": 0}

    def boom():
        tries["n"] += 1
        raise RuntimeError("no engine")
    monkeypatch.setattr("rapidocr_onnxruntime.RapidOCR", boom, raising=False)
    import rapidocr_onnxruntime
    monkeypatch.setattr(rapidocr_onnxruntime, "RapidOCR", boom)
    for _ in range(5):
        with pytest.raises(vision.OcrUnavailable):
            vision._start_engine()
    assert tries["n"] == 1, f"tried to start the engine {tries['n']} times; a remembered failure should be reused"

    monkeypatch.setattr(vision, "RETRY_ENGINE_AFTER", -1)     # time passes
    with pytest.raises(vision.OcrUnavailable):
        vision._start_engine()
    assert tries["n"] == 2, "after the retry window it must try again, so a reinstall is noticed"
    monkeypatch.setattr(vision, "_OCR_FAILED", None)


def test_the_plain_words_for_a_broken_reader_do_not_blame_the_chart():
    from app import plain
    said = plain.plain_reason("OCR unavailable: AttributeError: module 'ch_ppocr_v3_det' has no attribute 'TextDetector'. Reinstall it.")
    blob = " ".join(str(v) for v in said.values())
    assert "covering the chart" not in blob, "a dead text reader is not a chart that something is sitting on top of"
    assert "reads text off your screen" in blob
    assert "Health" in blob and "text reader" in blob, "it must point at the button that explains the fix"


def test_the_sample_image_is_actually_readable():
    """If the test picture were unreadable the check would cry wolf on a working reader."""
    img = ocr_health._sample_image()
    assert img.shape[0] > 20 and img.shape[2] == 3
    assert img.mean() < 60, "dark like a trading chart, which is the case the reader has to handle"
    toks = vision.ocr(img)
    assert "27686" in "".join(t.text for t in toks).replace(",", "").replace(" ", "")


# ---------------------------------------------------------------- the whole build, not just the reader

def test_every_subsystem_does_real_work_here():
    """Each check must actually exercise its subsystem. If one of these ever becomes an import-and-hope, the packaged
    build can break again without anyone noticing -- which is exactly how 0.18.1 shipped."""
    from app import diagnostics
    r = diagnostics.subsystems()
    assert r["ok"], [c for c in r["checks"] if c["status"] == "fail"]
    ids = {c["id"] for c in r["checks"]}
    assert {"ocr", "cv2", "sklearn", "database", "calendars", "onnx", "exchanges", "timezones"} <= ids
    assert all(c["detail"] for c in r["checks"]), "every check reports what it found"


def test_a_broken_subsystem_is_reported_not_raised(monkeypatch):
    from app import diagnostics

    def boom():
        raise ImportError("No module named 'ch_ppocr_v3_det'")
    monkeypatch.setattr(diagnostics, "CHECKS", [("x", "Something", boom)])
    r = diagnostics.subsystems()
    assert r["ok"] is False and r["failed"] == ["x"]
    assert "ImportError" in r["checks"][0]["detail"]
    assert "don't work in this build" in r["headline"]
