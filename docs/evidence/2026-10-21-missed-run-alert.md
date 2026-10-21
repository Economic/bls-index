# Missed-run alert on the live check (2026-10-21)

Plan launch step 2: the alert that warns when scheduled runs stop. The maintainer ran
the test on the live healthchecks.io check, after the first release.

## Why the earlier test sent no email

During the Phase 2 tests, shortening the check's period to 1 minute turned it down, but
no email arrived ([evidence](2026-10-21-phase2-test-releases.md)). That is intended
behavior. Healthchecks.io's `update_timeout` view (`hc/front/views.py`) handles a
schedule change that puts an up check past its deadline. It marks the check down at
once and records the flip as already processed, so no alert is sent. Its comment says:

> We don't want to send notifications when changing schedule interactively in the web
> UI.

So the test has to let a deadline pass on its own, as it does when runs stop.

## The test

1. The period and grace time were set to 1 minute each. The check turned down at once,
   with no email, as above.
2. A success ping, sent by hand, turned the check up, with its deadline 2 minutes away.
3. The deadline passed, the check went down, and the alert email arrived.
4. The period and grace time were set back to 1 day each, and a final ping by hand
   turned the check up.

## Result

The missed-run alert works on the live check. The monitor's remaining untested path is
the workflow's own `/fail` branch, which has not run on GitHub. Its ping and email were
confirmed by hand.
