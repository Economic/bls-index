"""Fake notifier that records alerts and can be told to fail."""

from __future__ import annotations

from bls_index.notifier import Alert, NotificationError


class FakeNotifier:
    def __init__(self) -> None:
        self.delivered: list[Alert] = []
        self.attempted: list[Alert] = []
        self.fail_next = 0
        self.fail_always = False

    def send(self, alert: Alert) -> None:
        self.attempted.append(alert)
        if self.fail_always or self.fail_next > 0:
            self.fail_next = max(0, self.fail_next - 1)
            raise NotificationError(f"injected notifier failure for {alert.condition}")
        self.delivered.append(alert)
