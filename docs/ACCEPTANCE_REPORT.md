# Real-PC acceptance report — 0.19.2

Written 2026-11-16. Four categories of evidence, kept apart on purpose, because they prove different things and
only the last two are about the machine that matters.

---

## 1. CI results (GitHub's Windows runners)

| Check | Result |
|---|---|
| Build (Windows, Python 3.12) | PASS |
| Unit and integration tests, Python 3.11 | **689 pass**, 0 fail |
| Unit and integration tests, Python 3.13 | pass |
| Lint (ruff E9,F,B) | clean |
| Windows reliability suite | **57 checks, 0 failed** |
| Installer builds, installs, upgrades over the previous version, uninstalls | PASS |

What this proves: the code is internally consistent and the installer is well-formed.
What it does not prove: anything about a real chart. Every one of these passed throughout the period when no
installed copy of Study Terminal could read a single character off a screen.

## 2. Packaged application results (inside the built .exe)

These run against the freshly built installer, not the source tree, and the release is blocked if they fail.

| Check | Result (0.19.2) |
|---|---|
| `--ocr-check`: text reader starts and reads known text from a dark image | **PASS**, 2.2 s, `frozen=True`, rapidocr 1.4.4 |
| `--deps-check`: ten subsystems each doing real work | **PASS**, 4.9 s, `frozen=True` |

The ten: app modules, image handling, maths and tables, model fitting, database, market calendars, time zones, model
runtime, screen-text reader, crypto price client (read-only). Each does a small real operation — fits a model, opens
a database, builds a calendar, decodes an image — rather than importing a name.

What this proves: the parts are present and functional in the artefact that gets installed. This is the gate whose
absence let 0.18.1 ship broken.
What it does not prove: that the reader can read *your* chart, which depends on your layout, theme, zoom and region.

## 3. Actual Windows PC results

**NOT TESTED.** No access to the user's machine.

The test exists and is ready to run: `StudyTerminal.exe --acceptance`, or `scripts\acceptance-test.ps1` for the
guided scenarios as well. Twelve stages, a timestamped report, and the picture it actually read saved alongside.

Run here against a live engine with no Windows and no chart, to prove it fails honestly rather than optimistically:

```
PASS 5 · FAIL 0 · BLOCKED 6 · INFO 1
verdict: Study Terminal has NOT been shown to read your real chart on this PC.
```

That is the correct result for a machine that cannot do it, and it is what the test must produce rather than a
cheerful summary of the parts that happened to work.

## 4. Actual TopstepX chart results

**NOT TESTED by me.** The user reported on 2026-11-16 that 0.18.3 reads their real TopstepX chart, which is the
first time any build has. That is their observation, not a measurement I made, and it is recorded as such.

What the acceptance test will establish that the report cannot:

- that the market, timeframe and price all come off the pixels, not just one of them;
- that the price read off the pixels agrees with the price TopstepX writes into its own tab name — two independent
  routes to one number, and the strongest check available without a paid feed;
- that the reading carries a timestamp and is recent;
- how long each stage takes on that hardware, including window capture, which cannot be measured anywhere else.

## 5. Remaining blockers

| Blocker | Needs | Why it cannot be worked around |
|---|---|---|
| Real-PC acceptance run | The user to run one command | No access to their machine, Edge session or TopstepX account |
| Windows capture timing | The same run | Windows Graphics Capture only exists on Windows; every other stage is already measured |
| Guided scenarios (resize, tab switch, timeframe change, network loss, restart) | The user at the keyboard | Each needs a human to change something on screen and look at the result |
| **Any claim that a strategy makes money** | Out-of-sample evidence | NQ/MNQ inconclusive, ES/MES losing. Unchanged by any of this work, and the only thing that would change what the app is for |

## What changed since the acceptance test was requested

| | Before | After |
|---|---|---|
| Full chart read | 2,208 ms p50 | **638 ms p50** |
| Price tick noticed | 63 ms (unchanged) | 63 ms |
| Stop hit announced | at the next full read (up to ~2 s) | on the next price read (~0.5 s) |
| Entry alert after the price has gone | sent | **not sent**, recorded as missed |
| Where the time goes | not measured | Health > Speed, per stage, p50/p95/worst |

## The sentence that matters

Study Terminal has been shown to work in CI and inside its own installer. It has **not** been shown by me to read
a real TopstepX chart on a real PC. One command settles that, and until it is run, the honest status of the chart
pipeline on the user's machine is *unproven*, regardless of how many other checks are green.
