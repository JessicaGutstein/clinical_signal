"""A person's decision on each possible cause: confirmed, rejected, or not sure.

The rules and the AI only suggest. Nothing is treated as the cause of a hotspot
until a person confirms it here, and only a confirmed cause is passed on to part
three ("Who can act").

Decisions are kept in one small file, data/cause_reviews.json, so they survive a
restart. Each is stored against the data date, the hotspot, and the kind of
cause, with who decided and when. A decision made on one day's data is not
carried over to another day's.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

import config

REVIEWS_FILE = "cause_reviews.json"
DECISIONS = ("confirmed", "rejected", "unsure")
MAX_NOTE, MAX_NAME = 500, 60


class Reviews:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or config.DATA_DIR / REVIEWS_FILE)
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._data = {}  # an unreadable file is treated as no decisions, never as a crash

    @staticmethod
    def _key(as_of, alert_id: str, topic: str) -> str:
        return f"{as_of}|{alert_id}|{topic}"

    def get(self, as_of, alert_id: str, topic: str) -> dict | None:
        return self._data.get(self._key(as_of, alert_id, topic))

    def set(self, as_of, alert_id: str, topic: str, decision: str | None, reviewer: str = "", note: str = "") -> dict | None:
        """Record a decision, or clear it when `decision` is None."""
        key = self._key(as_of, alert_id, topic)
        with self._lock:
            if decision is None:
                self._data.pop(key, None)
            else:
                if decision not in DECISIONS:
                    raise ValueError("Unknown decision.")
                self._data[key] = {
                    "decision": decision,
                    "reviewer": (reviewer or "").strip()[:MAX_NAME] or "Unnamed reviewer",
                    "note": (note or "").strip()[:MAX_NOTE],
                    "at": datetime.now().isoformat(timespec="seconds"),
                }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            return self._data.get(key)

    def attach(self, as_of, alert_id: str, result: dict) -> dict:
        """Add each cause's decision to a result from causes.find, without changing the cached copy."""
        out = dict(result)
        out["causes"] = [dict(c, review=self.get(as_of, alert_id, c["topic"])) for c in result["causes"]]
        out["confirmed"] = [c["label"] for c in out["causes"] if (c["review"] or {}).get("decision") == "confirmed"]
        return out
