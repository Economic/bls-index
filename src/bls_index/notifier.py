"""Maintainer alerts, delivered independently of the published manifest.

The production destination is an operator decision made after delivery and failure
tests (see the implementation plan). Every implementation raises ``NotificationError``
when delivery is not confirmed; a log entry alone is not an alert.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bls_index.events import EventLog


@dataclass(frozen=True)
class Alert:
    condition: str  # stable machine-readable condition, e.g. "manifest_write_unknown"
    summary: str
    details: str = ""


class NotificationError(Exception):
    pass


class Notifier(Protocol):
    def send(self, alert: Alert) -> None: ...


def send_alert(notifier: Notifier, alert: Alert, events: EventLog) -> bool:
    """Send ``alert``; record the outcome. Return False when delivery was not confirmed.

    Callers must treat ``False`` as its own failure (for example, by failing the workflow
    run so the CI platform's independent notification fires).
    """
    try:
        notifier.send(alert)
    except NotificationError as exc:
        events.record("notify.failed", condition=alert.condition, error=str(exc))
        return False
    events.record("notify.sent", condition=alert.condition)
    return True
