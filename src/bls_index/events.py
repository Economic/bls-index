"""Ordered event log shared by every workflow component.

Downloads, validation, object operations, notifications and manifest writes each record
an event. Tests assert on the order; workflow runs export it as a JSON Lines report.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from bls_index.clock import Clock, isoformat_utc, require_utc


@dataclass(frozen=True)
class Event:
    seq: int
    at: datetime
    kind: str
    data: Mapping[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {"seq": self.seq, "at": isoformat_utc(self.at), "kind": self.kind, **self.data}


class EventLog:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._events: list[Event] = []
        self._lock = threading.Lock()

    def record(self, kind: str, **data: Any) -> Event:
        with self._lock:
            event = Event(len(self._events), require_utc(self._clock.now()), kind, dict(data))
            self._events.append(event)
        return event

    @property
    def events(self) -> list[Event]:
        with self._lock:
            return list(self._events)

    def of_kind(self, *kinds: str) -> list[Event]:
        return [e for e in self.events if e.kind in kinds]

    def write_jsonl(self, path: Path) -> None:
        write_jsonl(self.events, path)


def write_jsonl(events: Iterable[Event], path: Path) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event.to_json(), sort_keys=True, default=str) + "\n")
