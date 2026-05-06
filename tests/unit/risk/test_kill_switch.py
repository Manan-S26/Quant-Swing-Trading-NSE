"""Tests for KillSwitch."""

from __future__ import annotations

import pytest

from trading_engine.risk.kill_switch import KillSwitch


def test_initially_inactive():
    ks = KillSwitch()
    assert not ks.is_active()
    assert ks.reason is None
    assert ks.activated_at is None


def test_activate_sets_active():
    ks = KillSwitch()
    ks.activate("daily loss limit hit")
    assert ks.is_active()
    assert ks.reason == "daily loss limit hit"
    assert ks.activated_at is not None


def test_deactivate_resets_state():
    ks = KillSwitch()
    ks.activate("test")
    ks.deactivate()
    assert not ks.is_active()
    assert ks.reason is None
    assert ks.activated_at is None


def test_activate_empty_reason_raises():
    ks = KillSwitch()
    with pytest.raises(ValueError):
        ks.activate("")


def test_activate_whitespace_only_reason_raises():
    ks = KillSwitch()
    with pytest.raises(ValueError):
        ks.activate("   ")


def test_activate_twice_overwrites_reason():
    ks = KillSwitch()
    ks.activate("first reason")
    ks.activate("second reason")
    assert ks.is_active()
    assert ks.reason == "second reason"


def test_deactivate_then_reactivate():
    ks = KillSwitch()
    ks.activate("reason one")
    ks.deactivate()
    assert not ks.is_active()
    ks.activate("reason two")
    assert ks.is_active()
    assert ks.reason == "reason two"
