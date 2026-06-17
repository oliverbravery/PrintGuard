"""Shared fixtures: tests may shrink the watchdog's timing constants
(poll intervals, grace periods) to run fast; restore them afterwards so
test order can never matter.
"""

import pytest

from printguard.engine import watchdog

_TIMING_DEFAULTS = {
    name: getattr(watchdog, name)
    for name in (
        "DEVICE_POLL_S",
        "NOTIFY_COOLDOWN_S",
        "WATCH_TICK_S",
        "OFFLINE_GRACE_S",
        "STALL_GRACE_S",
        "ACT_ATTEMPTS",
        "ACT_RETRY_S",
    )
}


@pytest.fixture(autouse=True)
def restore_timing_constants():
    yield
    for name, value in _TIMING_DEFAULTS.items():
        setattr(watchdog, name, value)
