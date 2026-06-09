"""Logical-to-physical motor mapping with JSON persistence.

Logical cadres are 1..4 (what the UI/draft uses).
Physical pin indices are 0..3 (the order in MCU's SERVO_PINS array,
which corresponds to D9, D10, D11, D12 in the firmware).

The mapping says: which physical pin index drives each logical cadre.
Default identity: cadre 1 -> physical 0 (D9), 2 -> 1 (D10), 3 -> 2 (D11),
4 -> 3 (D12).
"""
import json
from pathlib import Path

FRAME_COUNT_MAX = 8
PIN_LABELS = ["D9", "D10", "D11", "D12", "D5", "D6", "D8", "D3"]


class MotorMap:
    def __init__(self, path: Path, frame_count: int = 4):
        self.path = path
        self.frame_count = frame_count
        self.logical_to_physical = list(range(frame_count))
        self._load()

    def set_frame_count(self, n: int):
        n = max(2, min(FRAME_COUNT_MAX, int(n)))
        if n == self.frame_count:
            return
        self.frame_count = n
        # Default to identity for the new size; preserves nothing on resize
        # because permutations of different sizes don't translate cleanly.
        self.logical_to_physical = list(range(n))
        self.save()

    def _load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                m = data.get("logical_to_physical", [])
                if isinstance(m, list) and len(m) == self.frame_count and sorted(m) == list(range(self.frame_count)):
                    self.logical_to_physical = [int(x) for x in m]
            except Exception:
                pass

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"logical_to_physical": self.logical_to_physical}, indent=2))

    def to_physical_frames(self, logical_frames: list[int]) -> list[int]:
        """Translate a logical frames vector into the physical pin order."""
        phys = [0] * self.frame_count
        for logical_idx, raised in enumerate(logical_frames[:self.frame_count]):
            phys_idx = self.logical_to_physical[logical_idx]
            phys[phys_idx] = int(raised)
        return phys

    def set(self, mapping: list[int]) -> bool:
        if len(mapping) != self.frame_count:
            return False
        if sorted(mapping) != list(range(self.frame_count)):
            return False  # must be a permutation
        self.logical_to_physical = [int(x) for x in mapping]
        self.save()
        return True

    def reset(self):
        self.logical_to_physical = list(range(self.frame_count))
        self.save()

    def info(self) -> dict:
        return {
            "frame_count": self.frame_count,
            "logical_to_physical": list(self.logical_to_physical),
            "physical_labels": PIN_LABELS[:self.frame_count],
            "summary": [
                {"logical": i + 1, "physical_index": self.logical_to_physical[i],
                 "physical_label": PIN_LABELS[self.logical_to_physical[i]]}
                for i in range(self.frame_count)
            ],
        }
