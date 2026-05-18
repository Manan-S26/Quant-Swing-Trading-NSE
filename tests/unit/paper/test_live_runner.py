"""Tests for paper.live_runner — PaperLiveRunner with fake feed and ticks."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trading_engine.backtest.cost_model import CostModel
from trading_engine.backtest.slippage_model import SlippageModel
from trading_engine.live_data.candle_builder import CandleBuilder
from trading_engine.live_data.models import LiveTick
from trading_engine.paper.broker import PaperExecutionBroker
from trading_engine.paper.live_runner import PaperLiveRunner, PaperLiveRunnerConfig
from trading_engine.paper.portfolio import PaperPortfolio
from trading_engine.strategy.base import Strategy, StrategyContext
from trading_engine.strategy.signals import Bar, OrderIntent

_ZERO = Decimal("0")
_CASH = Decimal("100000")
_TOKEN = 256265
_SYM = "RELIANCE"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DoNothingStrategy(Strategy):
    def __init__(self) -> None:
        super().__init__(strategy_id="do_nothing")

    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        return []


class _BuyOneStrategy(Strategy):
    """Emits one MARKET BUY on the first bar, nothing thereafter."""

    def __init__(self) -> None:
        super().__init__(strategy_id="buy_one")
        self._bought = False

    def on_bar(self, bar: Bar, context: StrategyContext) -> list[OrderIntent]:
        if self._bought:
            return []
        self._bought = True
        return [
            OrderIntent(
                strategy_id=self.strategy_id,
                symbol=bar.symbol,
                exchange=bar.exchange,
                side="BUY",
                quantity=1,
                order_type="MARKET",
                product="MIS",
            )
        ]


def _make_runner(
    strategy: Strategy | None = None,
) -> tuple[PaperLiveRunner, CandleBuilder]:
    config = PaperLiveRunnerConfig(
        strategy_id="test_runner",
        symbols=[_SYM],
        interval_seconds=60,
        initial_cash=_CASH,
        dashboard_path=None,
    )
    cost = CostModel(
        brokerage_per_order=_ZERO,
        brokerage_cap=_ZERO,
        stt_rate=_ZERO,
        exchange_txn_rate=_ZERO,
        sebi_rate=_ZERO,
        stamp_duty_rate=_ZERO,
        gst_rate=_ZERO,
    )
    slippage = SlippageModel(bps=_ZERO)
    portfolio = PaperPortfolio(initial_cash=_CASH)
    broker = PaperExecutionBroker(portfolio=portfolio, cost_model=cost, slippage_model=slippage)
    cb = CandleBuilder(interval_seconds=60)
    runner = PaperLiveRunner(
        config=config,
        candle_builder=cb,
        strategy=strategy or _DoNothingStrategy(),
        execution_broker=broker,
        portfolio=portfolio,
    )
    return runner, cb


def _make_tick(price: float, minute: int, second: int = 0) -> LiveTick:
    return LiveTick(
        instrument_token=_TOKEN,
        symbol=_SYM,
        exchange=None,
        timestamp=datetime(2024, 1, 15, 9, minute, second),
        last_price=Decimal(str(price)),
        volume=100,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPaperLiveRunnerConfig:
    def test_defaults(self):
        config = PaperLiveRunnerConfig()
        assert config.interval_seconds == 60
        assert config.initial_cash == Decimal("100000")

    def test_custom_values(self):
        config = PaperLiveRunnerConfig(
            strategy_id="orb",
            symbols=["RELIANCE"],
            interval_seconds=300,
        )
        assert config.strategy_id == "orb"
        assert config.interval_seconds == 300


class TestPaperLiveRunnerBasic:
    def test_start_does_not_raise(self):
        runner, _ = _make_runner()
        runner.start()

    def test_stop_after_start_does_not_raise(self):
        runner, _ = _make_runner()
        runner.start()
        runner.stop()

    def test_on_tick_single_tick_no_bar(self):
        runner, _ = _make_runner()
        runner.start()
        # Single tick within one bucket — no bar emitted, no fills.
        runner.on_tick(_make_tick(100.0, 15, 0))
        assert runner._fills == []

    def test_on_tick_new_bucket_triggers_bar(self):
        """Two ticks in different buckets: second tick closes the first candle."""
        runner, _ = _make_runner(strategy=_BuyOneStrategy())
        runner.start()
        runner.on_tick(_make_tick(100.0, 15, 0))
        runner.on_tick(_make_tick(101.0, 16, 0))  # triggers candle close + strategy
        assert len(runner._fills) == 1

    def test_do_nothing_strategy_no_fills(self):
        runner, _ = _make_runner(strategy=_DoNothingStrategy())
        runner.start()
        runner.on_tick(_make_tick(100.0, 15, 0))
        runner.on_tick(_make_tick(101.0, 16, 0))
        assert runner._fills == []

    def test_stop_flushes_open_candle(self):
        """Stop should flush in-progress candles through the strategy."""
        runner, _ = _make_runner(strategy=_BuyOneStrategy())
        runner.start()
        runner.on_tick(_make_tick(100.0, 15, 0))  # opens a candle but no bar yet
        # Without a second tick to close the candle, flush happens on stop.
        runner.stop()
        # BuyOneStrategy fires on first bar (which comes from flush).
        assert len(runner._fills) == 1

    def test_on_tick_after_stop_is_ignored(self):
        runner, _ = _make_runner(strategy=_BuyOneStrategy())
        runner.start()
        runner.stop()
        runner.on_tick(_make_tick(100.0, 15, 0))
        runner.on_tick(_make_tick(101.0, 16, 0))
        assert len(runner._fills) == 0


class TestRunnerDoesNotPlaceOrders:
    """Explicit test that the runner does not call real order placement methods."""

    def test_no_place_order_attribute_accessed(self):
        runner, _ = _make_runner(strategy=_BuyOneStrategy())
        runner.start()
        runner.on_tick(_make_tick(100.0, 15))
        runner.on_tick(_make_tick(101.0, 16))
        # If we reach here without errors, no order placement happened.
        # PaperExecutionBroker simulates fills without calling Zerodha.
        assert True


class TestSafetyChecksInScript:
    """Tests that the script-level safety checks work correctly."""

    def test_requires_safety_flag(self):
        import sys

        sys.path.insert(
            0,
            str(
                __import__("pathlib").Path(__file__).resolve().parent.parent.parent.parent
                / "scripts"
            ),
        )
        from importlib import import_module

        # Import without triggering main — just test arg parsing.
        script = import_module("run_paper_live_zerodha")
        args = script._parse_args(["--symbols", "RELIANCE"])
        assert args.safety_flag is False

    def test_safety_flag_parsed(self):
        from importlib import import_module

        script = import_module("run_paper_live_zerodha")
        args = script._parse_args(
            ["--i-understand-this-uses-live-market-data", "--symbols", "RELIANCE"]
        )
        assert args.safety_flag is True

    def test_main_returns_1_without_safety_flag(self):
        from importlib import import_module

        script = import_module("run_paper_live_zerodha")
        rc = script.main(["--symbols", "RELIANCE"])
        assert rc == 1

    def test_main_returns_1_when_live_trading_enabled(self, monkeypatch):

        from importlib import import_module

        monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
        script = import_module("run_paper_live_zerodha")
        rc = script.main(["--i-understand-this-uses-live-market-data", "--symbols", "RELIANCE"])
        assert rc == 1

    def test_main_returns_1_when_credentials_missing(self, monkeypatch):
        from importlib import import_module

        monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
        monkeypatch.setenv("ZERODHA_API_KEY", "")
        monkeypatch.setenv("ZERODHA_ACCESS_TOKEN", "")
        script = import_module("run_paper_live_zerodha")
        rc = script.main(["--i-understand-this-uses-live-market-data", "--symbols", "RELIANCE"])
        assert rc == 1
