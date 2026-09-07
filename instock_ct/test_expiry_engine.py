"""Tests for Instock CT expiry engine."""

from __future__ import annotations

import unittest
from datetime import date
from dataclasses import replace

from instock_ct.config import DEFAULT_EXPIRY_THRESHOLDS_BY_CATEGORY, DEFAULT_SKUS
from instock_ct.expiry_engine import (
    assess_expiry,
    build_expiry_alerts,
    classify_expiry,
    days_until_expiry,
    get_expiry_thresholds,
    parse_expiry_date,
    summarize_expiry_counts,
)
from instock_ct.models import SkuMaster


class ExpiryEngineTests(unittest.TestCase):
    def test_parse_expiry_date_formats(self) -> None:
        self.assertEqual(parse_expiry_date("2026-09-15"), date(2026, 9, 15))
        self.assertEqual(parse_expiry_date("2026.09.15"), date(2026, 9, 15))
        self.assertEqual(parse_expiry_date("20260915"), date(2026, 9, 15))
        self.assertIsNone(parse_expiry_date(""))
        self.assertIsNone(parse_expiry_date("invalid"))

    def test_classify_expiry_levels(self) -> None:
        self.assertEqual(classify_expiry(-1), "expired")
        self.assertEqual(classify_expiry(10, critical_days=30, warning_days=90), "critical")
        self.assertEqual(classify_expiry(60, critical_days=30, warning_days=90), "warning")
        self.assertEqual(classify_expiry(120, critical_days=30, warning_days=90), "ok")

    def test_assess_expiry_uses_expiring_qty(self) -> None:
        sku = replace(DEFAULT_SKUS[0], nearest_expiry="2026-09-20", expiring_qty=42.0)
        alert = assess_expiry(sku, today=date(2026, 9, 3))
        self.assertIsNotNone(alert)
        assert alert is not None
        self.assertEqual(alert.expiring_qty, 42.0)
        self.assertEqual(alert.days_remaining, 17)

    def test_build_expiry_alerts_sorted(self) -> None:
        skus = [
            SkuMaster(
                "T-1",
                "테스트1",
                "medical_consumable",
                "의료소모품",
                100,
                5,
                7,
                10,
                "테스트",
                nearest_expiry="2026-12-01",
            ),
            SkuMaster(
                "T-2",
                "테스트2",
                "medical_consumable",
                "의료소모품",
                50,
                2,
                7,
                10,
                "테스트",
                nearest_expiry="2026-09-10",
            ),
        ]
        alerts = build_expiry_alerts(skus, today=date(2026, 9, 3))
        self.assertEqual(len(alerts), 2)
        self.assertLess(alerts[0].days_remaining, alerts[1].days_remaining)

    def test_summarize_expiry_counts(self) -> None:
        sku = replace(DEFAULT_SKUS[12], nearest_expiry="2026-09-08")
        alert = assess_expiry(sku, today=date(2026, 9, 3))
        self.assertIsNotNone(alert)
        counts = summarize_expiry_counts([alert])  # type: ignore[list-item]
        self.assertEqual(sum(counts.values()), 1)

    def test_category_specific_thresholds(self) -> None:
        sku = SkuMaster(
            "T-PB",
            "테스트 PB",
            "pb",
            "PB",
            100,
            5,
            7,
            10,
            "테스트",
            nearest_expiry="2026-10-13",
        )
        self.assertEqual(days_until_expiry(sku.nearest_expiry, today=date(2026, 9, 3)), 40)

        alert_default = assess_expiry(sku, today=date(2026, 9, 3))
        self.assertIsNotNone(alert_default)
        assert alert_default is not None
        self.assertEqual(alert_default.risk_level, "critical")
        self.assertEqual(alert_default.critical_threshold_days, 45.0)

        alert_relaxed = assess_expiry(
            sku,
            today=date(2026, 9, 3),
            thresholds_by_category={"pb": (30.0, 90.0)},
        )
        self.assertIsNotNone(alert_relaxed)
        assert alert_relaxed is not None
        self.assertEqual(alert_relaxed.risk_level, "warning")

        herbal_defaults = get_expiry_thresholds("herbal")
        self.assertEqual(herbal_defaults, DEFAULT_EXPIRY_THRESHOLDS_BY_CATEGORY["herbal"])

    def test_build_expiry_alerts_uses_per_category_rules(self) -> None:
        skus = [
            SkuMaster(
                "T-PB",
                "PB 테스트",
                "pb",
                "PB",
                50,
                2,
                7,
                10,
                "테스트",
                nearest_expiry="2026-10-20",
            ),
        ]
        alerts = build_expiry_alerts(
            skus,
            today=date(2026, 9, 3),
            thresholds_by_category={"pb": (30.0, 60.0)},
        )
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].risk_level, "warning")
        self.assertEqual(alerts[0].warning_threshold_days, 60.0)


if __name__ == "__main__":
    unittest.main()
