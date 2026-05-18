"""Tests for live_execution.safety — LiveExecutionSafetyGuard."""

from __future__ import annotations

import pytest

from trading_engine.common.exceptions import SafetyError
from trading_engine.live_execution.safety import LiveExecutionSafetyGuard
from trading_engine.risk.kill_switch import KillSwitch


class _Settings:
    def __init__(self, live_trading_enabled: bool = False):
        self.live_trading_enabled = live_trading_enabled


# ---------------------------------------------------------------------------
# assert_order_placement_blocked_for_now — always raises in this milestone
# ---------------------------------------------------------------------------


class TestOrderPlacementBlocked:
    def test_always_raises_safety_error(self):
        guard = LiveExecutionSafetyGuard(_Settings())
        with pytest.raises(SafetyError):
            guard.assert_order_placement_blocked_for_now()

    def test_raises_even_when_live_trading_enabled(self):
        guard = LiveExecutionSafetyGuard(_Settings(live_trading_enabled=True))
        with pytest.raises(SafetyError):
            guard.assert_order_placement_blocked_for_now()

    def test_raises_regardless_of_kill_switch(self):
        ks = KillSwitch()
        guard = LiveExecutionSafetyGuard(_Settings(live_trading_enabled=True), kill_switch=ks)
        with pytest.raises(SafetyError):
            guard.assert_order_placement_blocked_for_now()

    def test_error_message_mentions_not_implemented(self):
        guard = LiveExecutionSafetyGuard(_Settings())
        with pytest.raises(SafetyError, match="not implemented"):
            guard.assert_order_placement_blocked_for_now()


# ---------------------------------------------------------------------------
# assert_live_execution_allowed — prerequisite check
# ---------------------------------------------------------------------------


class TestLiveExecutionAllowed:
    def test_raises_when_live_trading_disabled(self):
        guard = LiveExecutionSafetyGuard(_Settings(live_trading_enabled=False))
        with pytest.raises(SafetyError, match="LIVE_TRADING_ENABLED"):
            guard.assert_live_execution_allowed()

    def test_passes_when_live_trading_enabled_and_no_kill_switch(self):
        guard = LiveExecutionSafetyGuard(_Settings(live_trading_enabled=True))
        guard.assert_live_execution_allowed()  # must not raise

    def test_raises_when_kill_switch_active(self):
        ks = KillSwitch()
        ks.activate("daily loss limit hit")
        guard = LiveExecutionSafetyGuard(_Settings(live_trading_enabled=True), kill_switch=ks)
        with pytest.raises(SafetyError, match="Kill switch"):
            guard.assert_live_execution_allowed()

    def test_passes_with_inactive_kill_switch(self):
        ks = KillSwitch()
        guard = LiveExecutionSafetyGuard(_Settings(live_trading_enabled=True), kill_switch=ks)
        guard.assert_live_execution_allowed()  # must not raise

    def test_raises_after_kill_switch_activated(self):
        ks = KillSwitch()
        guard = LiveExecutionSafetyGuard(_Settings(live_trading_enabled=True), kill_switch=ks)
        guard.assert_live_execution_allowed()  # fine initially
        ks.activate("manual stop")
        with pytest.raises(SafetyError):
            guard.assert_live_execution_allowed()

    def test_passes_after_kill_switch_deactivated(self):
        ks = KillSwitch()
        ks.activate("test")
        guard = LiveExecutionSafetyGuard(_Settings(live_trading_enabled=True), kill_switch=ks)
        ks.deactivate()
        guard.assert_live_execution_allowed()  # must not raise


# ---------------------------------------------------------------------------
# No settings attribute fallback
# ---------------------------------------------------------------------------


class TestNoSettingsAttribute:
    def test_missing_attribute_treated_as_disabled(self):
        guard = LiveExecutionSafetyGuard(object())  # plain object, no live_trading_enabled
        with pytest.raises(SafetyError):
            guard.assert_live_execution_allowed()
