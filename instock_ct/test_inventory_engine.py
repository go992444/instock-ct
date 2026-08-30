"""Tests for Instock CT inventory engine."""

from __future__ import annotations

import unittest
from dataclasses import replace

from instock_ct.config import DEFAULT_SKUS
from instock_ct.inventory_engine import (
    assess_stockout_risk,
    build_reorder_plan,
    forecast_from_weekly_sales,
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


if __name__ == "__main__":
    unittest.main()
