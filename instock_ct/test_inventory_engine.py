"""Tests for Instock CT inventory engine."""

from __future__ import annotations

import unittest
from dataclasses import replace

from instock_ct.config import DEFAULT_SKUS, DEFAULT_TURNOVER_THRESHOLDS_BY_CATEGORY
from instock_ct.inventory_engine import (
    annual_turnover,
    assess_stockout_risk,
    build_reorder_plan,
    filter_slow_movers,
    forecast_from_weekly_sales,
    get_turnover_threshold,
    recommended_reorder_qty,
    simulate_promo_impact,
    summarize_risk_counts,
)
from instock_ct.models import WeeklySales
from instock_ct.sample_sales import build_sample_weekly_sales


class InstockEngineTests(unittest.TestCase):
    def test_reorder_respects_moq(self) -> None:
        sku = DEFAULT_SKUS[0]
        qty = recommended_reorder_qty(sku)
        if qty > 0:
            self.assertEqual(qty % sku.moq, 0)

    def test_low_stock_is_critical(self) -> None:
        low = DEFAULT_SKUS[12]  # MC-013 low on_hand
        risk = assess_stockout_risk(low)
        self.assertIn(risk.risk_level, ("critical", "warning"))

    def test_promo_reduces_dos(self) -> None:
        sku = DEFAULT_SKUS[0]
        impact = simulate_promo_impact(sku, promo_uplift_pct=50)
        self.assertLess(impact.promo_dos, impact.baseline_dos)

    def test_forecast_from_sample_sales(self) -> None:
        sales = build_sample_weekly_sales()
        results = forecast_from_weekly_sales(sales)
        self.assertGreater(len(results), 10)
        self.assertGreater(results[0].forecast_next_week, 0)

    def test_risk_summary_counts(self) -> None:
        risks = [assess_stockout_risk(s) for s in DEFAULT_SKUS]
        counts = summarize_risk_counts(risks)
        self.assertEqual(sum(counts.values()), len(DEFAULT_SKUS))

    def test_reorder_plan_note_when_no_order(self) -> None:
        sku = DEFAULT_SKUS[0]
        high_stock = replace(sku, on_hand=99999)
        plan = build_reorder_plan(high_stock)
        self.assertEqual(plan.recommended_qty, 0)

    def test_annual_turnover_from_dos(self) -> None:
        sku = DEFAULT_SKUS[0]
        turnover = annual_turnover(sku.on_hand, sku.avg_daily_demand)
        self.assertIsNotNone(turnover)
        assert turnover is not None
        expected = 365.0 / (sku.on_hand / sku.avg_daily_demand)
        self.assertAlmostEqual(turnover, expected, places=2)

    def test_stockout_risk_includes_turnover(self) -> None:
        risk = assess_stockout_risk(DEFAULT_SKUS[0])
        self.assertIsNotNone(risk.annual_turnover)

    def test_filter_slow_movers(self) -> None:
        risks = [assess_stockout_risk(s) for s in DEFAULT_SKUS]
        slow = filter_slow_movers(risks, threshold=20.0)
        for row in slow:
            self.assertIsNotNone(row.annual_turnover)
            assert row.annual_turnover is not None
            self.assertLess(row.annual_turnover, 20.0)

    def test_filter_slow_movers_by_category(self) -> None:
        risks = [assess_stockout_risk(s) for s in DEFAULT_SKUS]
        strict = {"medical_consumable": 20.0, "pb": 20.0, "herbal": 20.0, "general": 20.0, "medical_equipment": 20.0}
        slow = filter_slow_movers(risks, thresholds_by_category=strict)
        for row in slow:
            cutoff = get_turnover_threshold(row.category, strict)
            assert row.annual_turnover is not None
            self.assertLess(row.annual_turnover, cutoff)

        herbal_default = get_turnover_threshold("herbal")
        self.assertEqual(
            herbal_default,
            DEFAULT_TURNOVER_THRESHOLDS_BY_CATEGORY["herbal"],
        )


if __name__ == "__main__":
    unittest.main()
