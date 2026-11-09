"""Writes the SYNTHETIC recorded screenshots used by tests/test_visual_monitor.py (with ground truth). Run from backend/:
    python -m tests.fixtures.visual.make_fixtures
They are generated charts, not TopstepX screenshots."""
import json
from pathlib import Path

import cv2

from tests.visual_chart import render, walk

OUT = Path(__file__).parent
CASES = {
    "mnq_5m_basic": dict(),
    "mnq_5m_lines_on_top": dict(lines_on_top=True, candles=walk(seed=7)),
    "es_5m_no_tag": dict(symbol="ESZ6", tag=False, step=2.0, candles=walk(start=6800.0, sd=1.5, seed=3)),
    "mnq_1m_zoomed_out": dict(tf_text="1m", spacing=4, bw=2, candles=walk(n=260, seed=5, sd=3.0)),
}

if __name__ == "__main__":
    for name, kw in CASES.items():
        img, truth = render(**kw)
        cv2.imwrite(str(OUT / f"{name}.png"), img)
        (OUT / f"{name}.json").write_text(json.dumps(truth, default=float), encoding="utf-8")
        print(name, img.shape)
