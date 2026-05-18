"""Safety regression tests — prove all live gates work as specified.

These tests are intentionally exhaustive: they document and enforce the exact
behaviour of every safety gate. Any regression in gate logic will cause a
specific test here to fail, making the breakage obvious.

No real Zerodha API calls are made. No real orders are placed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from trading_engine.common.exceptions import SafetyError
from trading_engine.live_execution.approvals import LiveOrderApprovalGate
from trading_engine.live_execution.models import (
    ApprovalDecision,
    ApprovalMode,
    ApprovalStatus,
)
from trading_engine.live_execution.pilot_config import LivePilotConfig
from trading_engine.live_execution.pilot_executor import LiveOrderPilotExecutor
from trading_engine.live_execution.safety import LiveExecutionSafetyGuard
from trading_engine.strategy.signals import OrderIntent

# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------


def _intent(
    symbol: str = "RELIANCE",
    side: str = "BUY",
    quantity: int = 1,
    order_type: str = "MARKET",
    product: str = "MIS",
    exchange: str = "NSE",
) -> OrderIntent:
    return OrderIntent(
        strategy_id="regression_test",
        symbol=symbol,
        exchange=exchange,
        side=side,
        quantity=quantity,
        order_type=order_type,
        product=product,
    )


def _approved_decision(approval_id: str = "reg-test-001") -> ApprovalDecision:
    return ApprovalDecision(
        approval_id=approval_id,
        status=ApprovalStatus.APPROVED,
        decided_at=datetime.now(tz=UTC),
        decided_by="auto_paper",
    )


def _enabled_config(**overrides: Any) -> LivePilotConfig:
    defaults = dict(
        live_order_execution_enabled=True,
        live_order_pilot_enabled=True,
        max_order_quantity=5,
        allowed_symbols=["RELIANCE"],
        allowed_exchange="NSE",
        allowed_product="MIS",
        allowed_order_types=["MARKET", "LIMIT"],
    )
    defaults.update(overrides)
    return LivePilotConfig(**defaults)  # type: ignore[arg-type]


class _FakeKite:
    def __init__(self, order_id: str = "ZRD_REGRESSION") -> None:
        self._order_id = order_id
        self.calls: list[dict[str, Any]] = []

    def place_order(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(kwargs)
        return {"order_id": self._order_id}


class _RiskDecision:
    def __init__(self, approved: bool) -> None:
        self.approved = approved
        self.reason_code = "APPROVED" if approved else "BLOCKED"
        self.reason_message = "ok" if approved else "blocked by risk"


class _RiskEngine:
    def __init__(self, approve: bool) -> None:
        self._approve = approve

    def check_order_intent(self, intent: Any, snapshot: Any, ts: Any) -> _RiskDecision:
        return _RiskDecision(self._approve)


def _connected_broker(kite: Any = None) -> Any:
    from trading_engine.broker.zerodha.client import ZerodhaBroker

    b = ZerodhaBroker(kite_client=kite or _FakeKite())
    b.connect()
    return b


def _guard() -> LiveExecutionSafetyGuard:
    class _S:
        live_trading_enabled = True

    return LiveExecutionSafetyGuard(_S())


# ---------------------------------------------------------------------------
# SR-01: All live flags default to False
# ---------------------------------------------------------------------------


class TestSR01AllFlagsDefaultFalse:
    """Prove that the Settings class defaults all live flags to False."""

    def test_live_trading_enabled_defaults_false(self):
        from trading_engine.common.config import Settings

        s = Settings(_env_file=".env.test_nonexistent")  # type: ignore[call-arg]
        assert s.live_trading_enabled is False

    def test_live_order_execution_enabled_defaults_false(self):
        from trading_engine.common.config import Settings

        s = Settings(_env_file=".env.test_nonexistent")  # type: ignore[call-arg]
        assert s.live_order_execution_enabled is False

    def test_live_order_pilot_enabled_defaults_false(self):
        from trading_engine.common.config import Settings

        s = Settings(_env_file=".env.test_nonexistent")  # type: ignore[call-arg]
        assert s.live_order_pilot_enabled is False

    def test_live_allowed_symbols_defaults_empty(self):
        from trading_engine.common.config import Settings

        s = Settings(_env_file=".env.test_nonexistent")  # type: ignore[call-arg]
        assert s.live_allowed_symbols == []

    def test_live_max_order_quantity_defaults_one(self):
        from trading_engine.common.config import Settings

        s = Settings(_env_file=".env.test_nonexistent")  # type: ignore[call-arg]
        assert s.live_max_order_quantity == 1


# ---------------------------------------------------------------------------
# SR-02: Empty allowed_symbols blocks all orders
# ---------------------------------------------------------------------------


class TestSR02EmptySymbolsBlocks:
    def test_empty_symbols_raises_safety_error(self):
        guard = _guard()
        config = _enabled_config(allowed_symbols=[])
        with pytest.raises(SafetyError, match="LIVE_ALLOWED_SYMBOLS is empty"):
            guard.assert_pilot_order_allowed(
                order_intent=_intent(),
                config=config,
                approval_decision=_approved_decision(),
                risk_decision=None,
            )

    def test_empty_symbols_blocks_via_executor(self):
        executor = LiveOrderPilotExecutor(
            broker=_connected_broker(_FakeKite()),
            pilot_config=_enabled_config(allowed_symbols=[]),
            approval_gate=LiveOrderApprovalGate(mode=ApprovalMode.AUTO_PAPER),
            safety_guard=_guard(),
        )
        result = executor.execute(_intent())
        assert result.success is False

    def test_empty_symbols_error_message_is_informative(self):
        guard = _guard()
        config = _enabled_config(allowed_symbols=[])
        with pytest.raises(SafetyError) as exc_info:
            guard.assert_pilot_order_allowed(
                order_intent=_intent(),
                config=config,
                approval_decision=_approved_decision(),
                risk_decision=None,
            )
        assert "LIVE_ALLOWED_SYMBOLS" in str(exc_info.value)


# ---------------------------------------------------------------------------
# SR-03: Quantity greater than cap blocks
# ---------------------------------------------------------------------------


class TestSR03QuantityCapEnforced:
    def test_quantity_exceeds_cap_raises(self):
        guard = _guard()
        config = _enabled_config(max_order_quantity=1)
        with pytest.raises(SafetyError, match="quantity"):
            guard.assert_pilot_order_allowed(
                order_intent=_intent(quantity=2),
                config=config,
                approval_decision=_approved_decision(),
                risk_decision=None,
            )

    def test_quantity_equals_cap_passes(self):
        guard = _guard()
        config = _enabled_config(max_order_quantity=2)
        guard.assert_pilot_order_allowed(
            order_intent=_intent(quantity=2),
            config=config,
            approval_decision=_approved_decision(),
            risk_decision=None,
        )  # must not raise

    def test_quantity_exceeds_cap_via_executor(self):
        kite = _FakeKite()
        executor = LiveOrderPilotExecutor(
            broker=_connected_broker(kite),
            pilot_config=_enabled_config(max_order_quantity=1),
            approval_gate=LiveOrderApprovalGate(mode=ApprovalMode.AUTO_PAPER),
            safety_guard=_guard(),
        )
        result = executor.execute(_intent(quantity=5))
        assert result.success is False
        assert len(kite.calls) == 0  # kite must NOT be called


# ---------------------------------------------------------------------------
# SR-04: AUTO_LIVE does not bypass approval
# ---------------------------------------------------------------------------


class TestSR04AutoLiveDoesNotBypass:
    def test_auto_live_raises_safety_error(self):
        gate = LiveOrderApprovalGate(mode=ApprovalMode.AUTO_LIVE)
        with pytest.raises(SafetyError):
            gate.require_approval(_intent())

    def test_auto_live_via_executor_returns_failure(self):
        executor = LiveOrderPilotExecutor(
            broker=_connected_broker(),
            pilot_config=_enabled_config(),
            approval_gate=LiveOrderApprovalGate(mode=ApprovalMode.AUTO_LIVE),
            safety_guard=_guard(),
        )
        result = executor.execute(_intent())
        assert result.success is False
        assert result.approval_status == ApprovalStatus.AUTO_REJECTED

    def test_auto_live_kite_not_called(self):
        kite = _FakeKite()
        executor = LiveOrderPilotExecutor(
            broker=_connected_broker(kite),
            pilot_config=_enabled_config(),
            approval_gate=LiveOrderApprovalGate(mode=ApprovalMode.AUTO_LIVE),
            safety_guard=_guard(),
        )
        executor.execute(_intent())
        assert len(kite.calls) == 0


# ---------------------------------------------------------------------------
# SR-05: place_order is not called when risk rejects
# ---------------------------------------------------------------------------


class TestSR05RiskRejectPreventsPlacement:
    def _executor(self, kite: _FakeKite) -> LiveOrderPilotExecutor:
        return LiveOrderPilotExecutor(
            broker=_connected_broker(kite),
            pilot_config=_enabled_config(),
            approval_gate=LiveOrderApprovalGate(mode=ApprovalMode.AUTO_PAPER),
            safety_guard=_guard(),
            risk_engine=_RiskEngine(approve=False),
        )

    def test_risk_reject_no_kite_call(self):
        kite = _FakeKite()

        class _Snap:
            pass

        self._executor(kite).execute(_intent(), portfolio_snapshot=_Snap())
        assert len(kite.calls) == 0

    def test_risk_reject_returns_auto_rejected(self):
        kite = _FakeKite()

        class _Snap:
            pass

        result = self._executor(kite).execute(_intent(), portfolio_snapshot=_Snap())
        assert result.approval_status == ApprovalStatus.AUTO_REJECTED
        assert result.success is False

    def test_risk_reject_error_mentions_risk(self):
        kite = _FakeKite()

        class _Snap:
            pass

        result = self._executor(kite).execute(_intent(), portfolio_snapshot=_Snap())
        assert result.error is not None
        assert "risk" in result.error.lower() or "BLOCKED" in result.error


# ---------------------------------------------------------------------------
# SR-06: place_order not called when approval is missing
# ---------------------------------------------------------------------------


class TestSR06MissingApprovalPreventsPlacement:
    def test_manual_approval_pending_no_kite_call(self):
        kite = _FakeKite()
        executor = LiveOrderPilotExecutor(
            broker=_connected_broker(kite),
            pilot_config=_enabled_config(),
            approval_gate=LiveOrderApprovalGate(mode=ApprovalMode.MANUAL_APPROVE),
            safety_guard=_guard(),
        )
        result = executor.execute(_intent())
        assert result.success is False
        assert result.approval_status == ApprovalStatus.PENDING
        assert len(kite.calls) == 0

    def test_unapproved_decision_blocks_safety_guard(self):
        guard = _guard()
        pending = ApprovalDecision(
            approval_id="test-pending",
            status=ApprovalStatus.PENDING,
            decided_at=datetime.now(tz=UTC),
        )
        with pytest.raises(SafetyError, match="approval status"):
            guard.assert_pilot_order_allowed(
                order_intent=_intent(),
                config=_enabled_config(),
                approval_decision=pending,
                risk_decision=None,
            )

    def test_rejected_decision_blocks_safety_guard(self):
        guard = _guard()
        rejected = ApprovalDecision(
            approval_id="test-rejected",
            status=ApprovalStatus.REJECTED,
            decided_at=datetime.now(tz=UTC),
        )
        with pytest.raises(SafetyError, match="approval status"):
            guard.assert_pilot_order_allowed(
                order_intent=_intent(),
                config=_enabled_config(),
                approval_decision=rejected,
                risk_decision=None,
            )


# ---------------------------------------------------------------------------
# SR-07: place_order not called when pilot config missing required flags
# ---------------------------------------------------------------------------


class TestSR07DisabledConfigPreventsPlacement:
    def _run_with_config(self, config: LivePilotConfig) -> tuple[Any, list[Any]]:
        kite = _FakeKite()
        executor = LiveOrderPilotExecutor(
            broker=_connected_broker(kite),
            pilot_config=config,
            approval_gate=LiveOrderApprovalGate(mode=ApprovalMode.AUTO_PAPER),
            safety_guard=_guard(),
        )
        result = executor.execute(_intent())
        return result, kite.calls

    def test_execution_disabled_no_kite_call(self):
        result, calls = self._run_with_config(_enabled_config(live_order_execution_enabled=False))
        assert result.success is False
        assert len(calls) == 0

    def test_pilot_disabled_no_kite_call(self):
        result, calls = self._run_with_config(_enabled_config(live_order_pilot_enabled=False))
        assert result.success is False
        assert len(calls) == 0

    def test_both_flags_disabled_no_kite_call(self):
        result, calls = self._run_with_config(
            _enabled_config(
                live_order_execution_enabled=False,
                live_order_pilot_enabled=False,
            )
        )
        assert result.success is False
        assert len(calls) == 0


# ---------------------------------------------------------------------------
# SR-08: CLI pilot cannot run without danger flag
# ---------------------------------------------------------------------------


class TestSR08CLIRequiresDangerFlag:
    def test_missing_danger_flag_returns_2(self, capsys):
        import sys
        from pathlib import Path

        _SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
        if str(_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS_DIR))

        import live_order_pilot as _script

        rc = _script.main(
            ["--symbol", "RELIANCE", "--side", "BUY", "--quantity", "1", "--order-type", "MARKET"]
        )
        assert rc == 2

    def test_missing_flag_prints_error(self, capsys):
        import sys
        from pathlib import Path

        _SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
        if str(_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS_DIR))

        import live_order_pilot as _script

        _script.main(
            ["--symbol", "RELIANCE", "--side", "BUY", "--quantity", "1", "--order-type", "MARKET"]
        )
        captured = capsys.readouterr()
        assert captured.err  # some error must be printed


# ---------------------------------------------------------------------------
# SR-09: CLI pilot requires exact confirmation phrase
# ---------------------------------------------------------------------------


class TestSR09CLIRequiresExactPhrase:
    def _import_script(self) -> Any:
        import sys
        from pathlib import Path

        _SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
        if str(_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS_DIR))

        import live_order_pilot as _script  # noqa: PLC0415

        return _script

    def test_wrong_phrase_returns_4(self, capsys, monkeypatch):
        _script = self._import_script()
        monkeypatch.setenv("LIVE_ORDER_EXECUTION_ENABLED", "true")
        monkeypatch.setenv("LIVE_ORDER_PILOT_ENABLED", "true")
        monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
        # Simulate user typing wrong phrase
        monkeypatch.setattr("builtins.input", lambda _: "wrong phrase")
        rc = _script.main(
            [
                "--symbol",
                "RELIANCE",
                "--side",
                "BUY",
                "--quantity",
                "1",
                "--order-type",
                "MARKET",
                "--i-understand-this-places-real-orders",
            ]
        )
        assert rc == 4

    def test_eof_input_returns_4(self, capsys, monkeypatch):
        _script = self._import_script()
        monkeypatch.setenv("LIVE_ORDER_EXECUTION_ENABLED", "true")
        monkeypatch.setenv("LIVE_ORDER_PILOT_ENABLED", "true")
        monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")

        def _raise_eof(prompt: str) -> str:
            raise EOFError

        monkeypatch.setattr("builtins.input", _raise_eof)
        rc = _script.main(
            [
                "--symbol",
                "RELIANCE",
                "--side",
                "BUY",
                "--quantity",
                "1",
                "--order-type",
                "MARKET",
                "--i-understand-this-places-real-orders",
            ]
        )
        assert rc == 4


# ---------------------------------------------------------------------------
# SR-10: Preflight checker does not print secrets
# ---------------------------------------------------------------------------


class TestSR10PreflightDoesNotPrintSecrets:
    def test_secret_values_not_in_json_output(self):
        from trading_engine.live_execution.preflight import LivePilotPreflightChecker

        class _SecretSettings:
            live_trading_enabled = True
            live_order_execution_enabled = True
            live_order_pilot_enabled = True
            live_max_order_quantity = 1
            live_allowed_symbols = ["RELIANCE"]
            live_allowed_exchange = "NSE"
            live_allowed_product = "MIS"
            live_allowed_order_types = ["MARKET"]

            class zerodha_api_key:
                @staticmethod
                def get_secret_value() -> str:
                    return "ACTUAL_SECRET_KEY_12345"

            class zerodha_api_secret:
                @staticmethod
                def get_secret_value() -> str:
                    return "ACTUAL_SECRET_VALUE_67890"

            class zerodha_access_token:
                @staticmethod
                def get_secret_value() -> str:
                    return "ACTUAL_SECRET_TOKEN_ABCDE"

        checker = LivePilotPreflightChecker(_SecretSettings())
        report = checker.run()
        output = import_json_dumps(report.to_dict())
        assert "ACTUAL_SECRET_KEY_12345" not in output
        assert "ACTUAL_SECRET_VALUE_67890" not in output
        assert "ACTUAL_SECRET_TOKEN_ABCDE" not in output

    def test_summary_does_not_contain_secrets(self):
        from trading_engine.live_execution.preflight import LivePilotPreflightChecker

        class _S:
            live_trading_enabled = False
            live_order_execution_enabled = False
            live_order_pilot_enabled = False
            live_max_order_quantity = 1
            live_allowed_symbols = []
            live_allowed_exchange = "NSE"
            live_allowed_product = "MIS"
            live_allowed_order_types = ["MARKET"]

            class zerodha_api_key:
                @staticmethod
                def get_secret_value() -> str:
                    return "SECRET_IN_SUMMARY_TEST"

            class zerodha_api_secret:
                @staticmethod
                def get_secret_value() -> str:
                    return ""

            class zerodha_access_token:
                @staticmethod
                def get_secret_value() -> str:
                    return ""

        checker = LivePilotPreflightChecker(_S())
        report = checker.run()
        assert "SECRET_IN_SUMMARY_TEST" not in report.summary()


def import_json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj)
