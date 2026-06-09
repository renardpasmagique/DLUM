"""Persisted runtime settings for DLUM (tassage delay, servo calibration)."""
import json
from pathlib import Path

FRAME_COUNT_MAX = 8
FRAME_COUNT_DEFAULT = 4

DEFAULTS = {
    "tassage_delay_ms": 2500,   # delay between picks (all_down, then new lift)
    "lift_hold_ms": 2500,       # minimum time frames stay up before next pick
    "frame_count": FRAME_COUNT_DEFAULT,
    "down_angles": [30] * FRAME_COUNT_MAX,
    "up_angles":   [130] * FRAME_COUNT_MAX,
    "led_display_mode": "pattern",  # "pattern" = drawdown, "counter" = pick N/total
    "use_color_changes": False,     # pause + LED announce when weft color changes
}


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path
        self.data = dict(DEFAULTS)
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text())
                if isinstance(d, dict):
                    for k, v in d.items():
                        if k in DEFAULTS:
                            self.data[k] = v
            except Exception:
                pass

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        if key not in DEFAULTS:
            return False
        self.data[key] = value
        self.save()
        return True

    def info(self) -> dict:
        return dict(self.data)
