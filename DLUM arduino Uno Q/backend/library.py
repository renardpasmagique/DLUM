"""Pattern library : persisted user-saved drafts on the carte.

Each entry is a JSON file under <library_dir>/<id>.json with the same
schema the drafting UI exports : threading, liftplan, warp/weft colors,
ends, picks, plus name/description metadata.
"""
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", (name or "").strip().lower())
    return s.strip("-") or "untitled"


class PatternLibrary:
    def __init__(self, library_dir: Path):
        self.dir = library_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict[str, Any]]:
        out = []
        for p in sorted(self.dir.glob("*.json")):
            try:
                d = json.loads(p.read_text())
                out.append({
                    "id": p.stem,
                    "name": d.get("name", p.stem),
                    "description": d.get("description", ""),
                    "ends": d.get("ends", 0),
                    "picks": d.get("picks", 0),
                    "created_at": d.get("created_at"),
                })
            except Exception:
                continue
        out.sort(key=lambda x: (x.get("created_at") or 0), reverse=True)
        return out

    def get(self, entry_id: str) -> dict | None:
        p = self.dir / f"{entry_id}.json"
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text())
            d["id"] = entry_id
            return d
        except Exception:
            return None

    def save(self, payload: dict) -> dict:
        name = (payload.get("name") or "").strip() or "Sans titre"
        slug = _slugify(name)
        # disambiguate to avoid collisions with another entry of the same name
        existing_ids = {p.stem for p in self.dir.glob("*.json")}
        entry_id = slug
        if entry_id in existing_ids:
            entry_id = f"{slug}-{uuid.uuid4().hex[:6]}"
        record = {
            "name": name,
            "description": payload.get("description", ""),
            "threading": payload.get("threading", []),
            "liftplan": payload.get("liftplan", []),
            "warpColors": payload.get("warpColors", []),
            "weftColors": payload.get("weftColors", []),
            "ends": payload.get("ends", 0),
            "picks": payload.get("picks", 0),
            "created_at": int(time.time()),
        }
        (self.dir / f"{entry_id}.json").write_text(json.dumps(record, indent=2))
        return {"id": entry_id, **record}

    def delete(self, entry_id: str) -> bool:
        p = self.dir / f"{entry_id}.json"
        if p.exists():
            p.unlink()
            return True
        return False
