# Issue register

Every defect found, its root cause, the repair, and the evidence it is actually fixed. Newest first. An issue is only
marked FIXED when something that fails before the change passes after it.

Status words: **FIXED** (repaired and verified here) · **OPEN** (confirmed, not yet repaired) · **BLOCKED** (needs
something I don't have access to) · **WONTFIX** (deliberate, with the reason).

---

## Cycle 1 — 2026-11-16 (0.18.2)

### ST-001 · CRITICAL · Screen-text reader missing from every packaged build

**Component** packaging (installer/StudyTerminal.spec), app/screen/vision.py
**Reported as** `AttributeError: module 'ch_ppocr_v3_det' has no attribute 'TextDetector'` at vision.py:50; chart
permanently UNREADABLE with "I can't read your chart right now."

**Reproduce** Install any build up to and including 0.18.1, open a TopstepX chart, start monitoring. Reproduced here
without Windows by rebuilding the packaged layout: a folder named `ch_ppocr_v3_det` containing only `config.yaml`,
with its parent on `sys.path`.

**Root cause** RapidOCR 1.2.3 (what `rapidocr_onnxruntime>=1.2` resolved to) does not import its detector, recogniser
and classifier in source. It reads their module names out of its own `config.yaml` at run time and calls
`importlib.import_module(name)`, relying on having appended its own directory to `sys.path`. PyInstaller decides what
to include by reading source, so a name built at run time is invisible to it and the three modules were never
bundled. The spec did call `collect_data_files("rapidocr_onnxruntime")`, which copied the packages' **data** files and
so created folders with exactly those names containing no Python. Python imported each as a namespace package — the
import *succeeded*, returning an empty module — and the first attribute asked of it raised AttributeError.

**Why no test caught it** A source checkout has the real `.py` files on disk, so the dynamic import resolves normally.
Every unit test and every CI run passed while the installed application could not read a single character. This class
of defect is structurally invisible to tests that run against the source tree.

**Fix**
1. `backend/requirements.txt` — pinned per interpreter: `==1.4.4` below Python 3.13, `==1.2.3` on 3.13 and above.
   1.4.x imports those modules normally (relative imports, no `sys.path` manipulation, no `module_name` in config),
   which removes the mechanism rather than working around it — but it is only published for Python below 3.13, and
   on 3.13 the newest installable release is the affected one. A single hard pin would have made the file
   uninstallable on one interpreter or the other; see ST-008 for why the build was on 3.13 at all.
2. `installer/StudyTerminal.spec` — `collect_submodules("rapidocr_onnxruntime")` added to hidden imports (so the
   packaging tool analyses each worker module and pulls in pyclipper, shapely and yaml), and `collect_data_files(...,
   include_py_files=True)` so the on-disk copy carries real code if a future version brings the trick back.
3. `app/screen/vision.py` — engine start wrapped: a failure now raises `OcrUnavailable` carrying the cause and the
   repair, instead of an unhandled AttributeError.

**Verification** The exact failure was reproduced from a hand-built broken bundle and the new check reports it with
the right advice (`tests/test_ocr_health.py::test_an_empty_folder_masquerading_as_a_module_is_caught`). The real
reader passes end to end on both rapidocr 1.2.3 (Python 3.13) and 1.4.4 (Python 3.11).
**Status** FIXED — *in the source and in CI. Real-PC confirmation outstanding until the 0.18.2 installer is run.*

### ST-002 · CRITICAL · No release gate could see inside the packaged app

**Component** CI, scripts/windows-reliability.ps1
**Root cause** Nothing in the pipeline ever asked the built `.exe` to do any real work. The Windows checks installed
it, started it, loaded its page and uninstalled it — none of which touches OCR, model fitting, calendars or the
database. ST-001 was therefore undetectable by design.

**Fix** `StudyTerminal.exe --ocr-check` and `StudyTerminal.exe --deps-check` run inside the packaged app:
ten subsystems, each doing a small piece of real work (fit a model, open a database, build a market calendar, decode
an image, construct an exchange client, read known text from a picture). `scripts/windows-reliability.ps1` runs both
against the freshly built installer as checks 12 and 13, and the `publish` job needs `reliability`, so a release
cannot ship with any of them failing.
**Status** FIXED

### ST-003 · HIGH · A backend crash broke the page instead of reporting itself

**Component** frontend/src/lib.ts, backend/app/main.py
**Reported as** `Unexpected token ',', "Internal S"... is not valid JSON` under the chart-setup buttons.
**Root cause** Two faults, one on each side. The browser helper read the response body and called `JSON.parse` on it
*before* checking the status code, so any non-JSON error body became a parse error that hid the real problem. And the
backend had no handler for unhandled exceptions, so FastAPI answered with the plain words `Internal Server Error`.
Same trigger as ST-001: the chart-setup Test read called the dead reader.

**Fix** The helper now checks the status first, copes with empty, plain-text and HTML bodies, separates offline,
timeout, server, refused and unreadable-answer cases, and has a 10-minute backstop timeout (above the ~4 minutes a
real research run takes). The backend answers every unhandled exception with JSON naming the fault and the file and
line it came from — no paths, no values — with the full traceback in the log.
**Verification** `tests/test_error_envelope.py` (4 tests), including a deliberately crashing endpoint and a dead
reader reached through a real request.
**Status** FIXED

### ST-004 · HIGH · "I can't read your chart" was the answer to every different problem

**Component** app/plain.py, app/screen/visual_monitor.py
**Root cause** A broken text reader, a covered window and an unreadable chart all produced the same sentence, so the
advice ("make sure nothing is covering the chart") was wrong and unfixable in the one case that mattered.
**Fix** A reader failure is now its own state with its own words, pointing at the Health page button that runs the
check and prints the repair. Distinct states: reader unavailable · capture failed · window not found · window
minimised · wrong tab · covered · layout changed · frozen · stale · readable.
**Status** FIXED

### ST-005 · MEDIUM · Unpinned OCR dependency across a renaming change

**Component** backend/requirements.txt
**Root cause** `rapidocr_onnxruntime>=1.2` spanned a layout change (`ch_ppocr_v3_det` → `ch_ppocr_det`), so two builds
from the same commit could differ in which modules exist.
**Fix** Pinned, with the reason and the condition for changing it written next to the pin.
**Status** FIXED

### ST-006 · LOW · The on-PC Windows check passed while OCR was broken

**Component** desktop/verify_windows.py
**Root cause** It checked `__import__("rapidocr_onnxruntime")`, which succeeds whether or not the reader works.
**Fix** It now runs the full reader check — engine start plus a real recognition — and reports every step.
**Status** FIXED

### ST-007 · LOW · Wrong test count published in the 0.18.1 notes

**Component** docs/TEST_RESULTS.md
**Root cause** My error: the notes said 657 tests; the suite at that commit held 629.
**Fix** Corrected in place, with the correction marked rather than quietly overwritten. Counts are now taken from
`pytest --collect-only` rather than written from memory.
**Status** FIXED

### ST-008 · HIGH · The build used a different Python from the one it asked for

**Component** scripts/setup.ps1, .github/workflows/build-windows.yml
**Found by** the new pin failing to install in CI — the first thing this cycle's changes caught.
**Root cause** The workflow sets up Python 3.12, but `setup.ps1` builds the virtual environment from the first
interpreter it finds and its list started with `py -3.13`. GitHub's Windows image ships 3.13, so every release was
built on 3.13 while the workflow said 3.12. That is what selected the affected OCR version: 1.4.x is not published
for 3.13, so pip quietly resolved down to 1.2.3 — the one with the run-time-name import trick — and nothing said so.
A silent interpreter substitution changes which wheels an entire release is built from.

**Fix** `setup.ps1` tries 3.12 first, so the build uses the interpreter the workflow asks for and the OCR version
where the problem cannot arise. 3.13 remains supported for running from source: the packaging fix and the self-test
cover the affected version.
**Status** FIXED

## Cycle 2 — 2026-11-16 (latency)

### ST-009 · HIGH · A whole module existed only on my disk and had never been committed

**Component** backend/app/screen/token_cache.py
**Found by** running `git status` while starting the latency work.
**Root cause** The part that avoids re-reading unchanged chart text — written, tested, and the thing the speed of a
full chart read depends on — was never added to the repository. Every release, 0.18.3 included, was built without
it, so the installed app re-read every word on the chart on every pass. Its own test file was uncommitted too, so
nothing failed and nothing said a word.
**Fix** Committed, with its tests, after re-verifying it from scratch and measuring what it is worth.
**Verification** 663 tests pass on Python 3.11 and 3.13, including the cache's own 14.
**Status** FIXED. The general lesson is the same one as ST-002: nothing in the pipeline compares what is in the
working tree against what is in the build.

### ST-010 · HIGH · The text detector was being handed shapes that made it slow

**Component** backend/app/screen/vision.py
**Root cause** The detector resizes whatever it is given. A wide, short strip gets scaled UP; a big picture gets
scaled DOWN. So reading the chart's header band alone measured **2,146 ms** against **1,163 ms** for the entire
chart that band was cut from — reading less took nearly twice as long.
**Fix** Pad a long thin strip out towards square (2:1) before reading it, on the bottom and right only so no
coordinate changes meaning. Header band 2,146 → 664 ms, price-scale strip 994 → 658 ms, identical words out.
**Status** FIXED

### ST-011 · HIGH · The chart's label was re-read on every tick for an answer that never changed

**Component** backend/app/screen/token_cache.py
**Root cause** TopstepX prints the live open/high/low/close into the same line as the chart's name, so the pixels of
that band change on every tick. The cache treated that as "the label changed" and re-read it — about a second each
time at a real 1920-wide capture — to be told the same market and timeframe as a second earlier.
**Fix** The band is re-read when the contract in the window title changes (TopstepX updates that on every tick, so a
market change is noticed immediately), when the layout changes shape, or on an 8-second timer that bounds how long a
timeframe change can go unnoticed. Pixels remain the trigger when no usable title exists, so nothing regresses for a
window that does not name its contract.
**Verification** Three new tests: the timer bound, a contract change noticed at once, a price-only title change
ignored. Measured at the user's capture size: full chart read **2,208 → 638 ms at p50** (3.5x).
**Status** FIXED

### ST-012 · MEDIUM · The priming read never recorded which contract it had read

**Component** backend/app/screen/token_cache.py
**Found by** a test written for ST-011 failing.
**Root cause** The first read of a chart stored no window title, so the "has the contract changed?" comparison had
nothing to compare against and could never fire — the signal ST-011 relies on would have been dead in the real app
while passing every test that did not look for it.
**Fix** The priming read stores it. Covered by the contract-change test.
**Status** FIXED

---

## Known limits of this cycle

- **Real-PC validation is outstanding.** Everything above is verified in this environment and in CI on GitHub's
  Windows runners. I have no access to the user's PC, their Edge session or their TopstepX account, so "the installed
  0.18.2 reads your chart" is not yet evidence, only expectation. The first run of the new installer is what settles it.
- **No strategy claim.** None of this says anything about whether a strategy makes money. Software passing tests and a
  strategy being profitable are unrelated, and the out-of-sample results remain inconclusive for NQ/MNQ and losing for
  ES/MES.
- **FOMO (fomo.family) and pump.fun remain UNSUPPORTED**, unchanged: no developer API, and the terms forbid scraping.
  Nothing is connected and nothing claims to be.
