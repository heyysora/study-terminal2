"""Saved chart configurations for the Visual Market Monitor. One profile per chart layout: different windows, sizes, colors and
scales are never assumed to be the same. Stored as JSON in the data folder (no images)."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOTS = ("NQ", "MNQ", "ES", "MES")
TIMEFRAMES = ("1Min", "2Min", "3Min", "5Min", "15Min", "30Min", "1Hour", "4Hour", "1Day")


@dataclass
class ChartProfile:
    id: str = ""
    name: str = "TopstepX chart"
    # which window: matched by title text (and process name, if given); hwnd is only a hint for this session
    window_title_contains: str = "TopstepX"
    window_process: str | None = None
    window_hwnd: int | None = None
    window_size: list[int] | None = None          # [w, h] when the region was set; a different size = layout change
    # capture region inside the window, in window pixels
    region: list[int] = field(default_factory=lambda: [0, 0, 0, 0])   # x, y, w, h (w/h 0 = whole window)
    # instrument / timeframe: "auto" reads them from the screen; otherwise fixed
    root: str = "auto"                              # auto | NQ | MNQ | ES | MES
    timeframe: str = "auto"                         # auto | 1Min | 5Min | ...
    # price axis: "auto" fits the axis labels; "manual" uses two clicked points [[y, price], [y, price]] (region coordinates)
    axis_mode: str = "auto"
    axis_points: list[list[float]] = field(default_factory=list)
    axis_x: int | None = None                       # x (region coords) where the price axis starts; None = find it
    axis_size: list[int] | None = None              # region size [w, h] when calibrated manually; a different size invalidates it
    capture_method: str = "auto"                    # auto | wgc | printwindow | screen (see screen/capture_sources.py)
    plot_bottom: float = 0.80                       # fraction of region height where the candle pane ends (volume pane below)
    # colors as [r, g, b]; None = detect automatically (candles) or not used (lines)
    up_color: list[int] | None = None
    down_color: list[int] | None = None
    vwap_color: list[int] | None = None
    ema_colors: dict = field(default_factory=dict)  # {"9": [r,g,b], "20": ..., "50": ..., "200": ...}
    color_tolerance: int = 40
    # timing
    capture_seconds: float = 2.0
    stale_seconds: float = 20.0                     # no good reading for this long -> STALE
    frozen_seconds: float = 90.0                    # no visible change for this long during the session -> frozen
    active: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ChartProfile":
        names = set(cls.__dataclass_fields__)
        p = cls(**{k: v for k, v in (d or {}).items() if k in names})
        p.validate()
        return p

    def validate(self) -> None:
        if self.root != "auto" and self.root not in ROOTS:
            raise ValueError(f"Instrument must be auto or one of {', '.join(ROOTS)}.")
        if self.timeframe != "auto" and self.timeframe not in TIMEFRAMES:
            raise ValueError("Unknown timeframe.")
        if self.capture_method not in ("auto", "wgc", "printwindow", "screen"):
            raise ValueError("capture_method must be auto, wgc, printwindow or screen.")
        if self.axis_mode not in ("auto", "manual"):
            raise ValueError("axis_mode must be auto or manual.")
        if self.axis_mode == "manual":
            if len(self.axis_points) != 2 or abs(self.axis_points[0][0] - self.axis_points[1][0]) < 20:
                raise ValueError("Manual axis calibration needs two points at least 20 pixels apart.")
            if self.axis_points[0][1] == self.axis_points[1][1]:
                raise ValueError("The two calibration prices must differ.")
        if len(self.region) != 4 or any(int(v) < 0 for v in self.region):
            raise ValueError("Region must be [x, y, width, height] with non-negative values.")
        if not 0.3 <= float(self.plot_bottom) <= 1.0:
            raise ValueError("plot_bottom must be between 0.3 and 1.0.")
        for c in [self.up_color, self.down_color, self.vwap_color, *self.ema_colors.values()]:
            if c is not None and (len(c) != 3 or any(not 0 <= int(v) <= 255 for v in c)):
                raise ValueError("Colors are [r, g, b] with values 0-255.")
        if not 0.5 <= float(self.capture_seconds) <= 60:
            raise ValueError("Capture interval must be 0.5-60 seconds.")

    def matches(self, title: str | None, process: str | None) -> bool:
        if not title:
            return False
        ok = self.window_title_contains.lower() in title.lower() if self.window_title_contains else True
        if ok and self.window_process:
            ok = (process or "").lower() == self.window_process.lower()
        return ok


class ProfileStore:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "visual_profiles.json"

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def all(self) -> list[ChartProfile]:
        out = []
        for d in self._load().values():
            try:
                out.append(ChartProfile.from_dict(d))
            except (ValueError, TypeError):
                continue
        return out

    def get(self, pid: str) -> ChartProfile | None:
        d = self._load().get(pid)
        return ChartProfile.from_dict(d) if d else None

    def save(self, p: ChartProfile) -> ChartProfile:
        p.validate()
        if not p.id:
            p.id = uuid.uuid4().hex[:10]
        if not re.fullmatch(r"[0-9a-zA-Z_-]{1,40}", p.id):
            raise ValueError("Bad profile id.")
        data = self._load()
        data[p.id] = p.to_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        return p

    def delete(self, pid: str) -> bool:
        data = self._load()
        if pid not in data:
            return False
        del data[pid]
        self.path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        return True
