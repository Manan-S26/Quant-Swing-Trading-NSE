"""Tests for domain ID generation helpers."""

from __future__ import annotations

from trading_engine.domain.identifiers import (
    generate_fill_id,
    generate_internal_order_id,
    generate_risk_decision_id,
    generate_signal_id,
)


class TestInternalOrderId:
    def test_has_ord_prefix(self) -> None:
        assert generate_internal_order_id().startswith("ord_")

    def test_is_string(self) -> None:
        assert isinstance(generate_internal_order_id(), str)

    def test_unique_across_calls(self) -> None:
        ids = {generate_internal_order_id() for _ in range(100)}
        assert len(ids) == 100


class TestSignalId:
    def test_has_sig_prefix(self) -> None:
        assert generate_signal_id().startswith("sig_")

    def test_is_string(self) -> None:
        assert isinstance(generate_signal_id(), str)

    def test_unique_across_calls(self) -> None:
        ids = {generate_signal_id() for _ in range(100)}
        assert len(ids) == 100


class TestRiskDecisionId:
    def test_has_risk_prefix(self) -> None:
        assert generate_risk_decision_id().startswith("risk_")

    def test_is_string(self) -> None:
        assert isinstance(generate_risk_decision_id(), str)

    def test_unique_across_calls(self) -> None:
        ids = {generate_risk_decision_id() for _ in range(100)}
        assert len(ids) == 100


class TestFillId:
    def test_has_fill_prefix(self) -> None:
        assert generate_fill_id().startswith("fill_")

    def test_is_string(self) -> None:
        assert isinstance(generate_fill_id(), str)

    def test_unique_across_calls(self) -> None:
        ids = {generate_fill_id() for _ in range(100)}
        assert len(ids) == 100


class TestCrossGeneratorUniqueness:
    def test_different_generators_produce_different_prefixes(self) -> None:
        order_id = generate_internal_order_id()
        signal_id = generate_signal_id()
        risk_id = generate_risk_decision_id()
        fill_id = generate_fill_id()
        assert order_id[:4] == "ord_"
        assert signal_id[:4] == "sig_"
        assert risk_id[:5] == "risk_"
        assert fill_id[:5] == "fill_"

    def test_ids_from_different_generators_do_not_collide(self) -> None:
        all_ids = (
            {generate_internal_order_id() for _ in range(50)}
            | {generate_signal_id() for _ in range(50)}
            | {generate_risk_decision_id() for _ in range(50)}
            | {generate_fill_id() for _ in range(50)}
        )
        # All 200 IDs should be unique (prefix ensures no cross-type collision)
        assert len(all_ids) == 200
