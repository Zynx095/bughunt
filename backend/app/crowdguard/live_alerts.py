"""Live alerts with de-duplication, escalation and cooldown.

A condition is identified by a stable key (e.g. "capacity:zone-b"). While it stays true the same alert
is updated rather than re-raised; it clears after the condition has been false for `clear_after_s`;
and once cleared, the same key cannot raise a fresh alert for `cooldown_s` unless its severity is higher
than before. One-shot events (route changed, camera disconnected) use the same cooldown.
"""
from __future__ import annotations

import itertools
import threading
from collections import deque
from typing import Any, Optional

SEV = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


class AlertManager:
    def __init__(self, cooldown_s: float = 30.0, clear_after_s: float = 4.0, history: int = 300) -> None:
        self.cooldown_s = cooldown_s
        self.clear_after_s = clear_after_s
        self.active: dict[str, dict[str, Any]] = {}
        self.cleared_at: dict[str, tuple[float, int]] = {}
        self.history: deque[dict[str, Any]] = deque(maxlen=history)
        self.suppressed = 0
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def _new(self, key: str, now: float, severity: str, kind: str, location: dict[str, Any], observation: str,
             action: str, metrics: dict[str, Any] | None) -> dict[str, Any]:
        alert = {"id": f"A{next(self._ids):05d}", "key": key, "kind": kind, "severity": severity, "raised_at": now,
                 "updated_at": now, "location": location, "observation": observation, "action": action,
                 "metrics": metrics or {}, "status": "active", "last_true": now}
        self.history.appendleft(alert)
        return alert

    def _cooling(self, key: str, now: float, severity: str) -> bool:
        prev = self.cleared_at.get(key)
        return prev is not None and now - prev[0] < self.cooldown_s and SEV[severity] <= prev[1]

    def observe(self, key: str, condition: bool, now: float, *, severity: str = "medium", kind: str = "", location: Optional[dict[str, Any]] = None,
                observation: str = "", action: str = "", metrics: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        """Report the current truth of a condition. Returns a *newly raised* alert, else None."""
        with self._lock:
            cur = self.active.get(key)
            if condition:
                if cur is None:
                    if self._cooling(key, now, severity):
                        self.suppressed += 1
                        return None
                    alert = self._new(key, now, severity, kind, location or {}, observation, action, metrics)
                    self.active[key] = alert
                    return alert
                cur.update(updated_at=now, last_true=now, observation=observation, metrics=metrics or cur["metrics"])
                if SEV[severity] > SEV[cur["severity"]]:
                    cur["severity"] = severity
                    cur["action"] = action
                    cur["escalated_at"] = now
                return None
            if cur is not None and now - cur["last_true"] >= self.clear_after_s:
                cur.update(status="cleared", cleared_at=now)
                self.cleared_at[key] = (now, SEV[cur["severity"]])
                del self.active[key]
            return None

    def event(self, key: str, now: float, *, severity: str, kind: str, location: Optional[dict[str, Any]] = None,
              observation: str = "", action: str = "", metrics: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        """A one-shot occurrence (recorded in history, not kept active)."""
        with self._lock:
            if self._cooling(key, now, severity):
                self.suppressed += 1
                return None
            alert = self._new(key, now, severity, kind, location or {}, observation, action, metrics)
            alert.update(status="event")
            self.cleared_at[key] = (now, SEV[severity])
            return alert

    def snapshot(self, limit: int = 12) -> list[dict[str, Any]]:
        with self._lock:
            items = sorted(self.active.values(), key=lambda a: (-SEV[a["severity"]], -a["raised_at"]))
            return [{k: v for k, v in a.items() if k != "last_true"} for a in items[:limit]]

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return [{k: v for k, v in a.items() if k != "last_true"} for a in list(self.history)[:limit]]

    def clear_all(self) -> None:
        with self._lock:
            self.active.clear()
