"""Tests for browser localStorage snapshot serialization."""

from __future__ import annotations

import unittest

from instock_ct.browser_storage import parse_snapshot, snapshot_to_json
from instock_ct.models import ExpiryLot, SkuMaster, WeeklySales


class BrowserStorageTests(unittest.TestCase):
    def test_snapshot_roundtrip_with_expiry_lots(self) -> None:
        skus = [
            SkuMaster(
                sku_id="ENP00001",
                name="테스트",
                category="endoscopy",
                category_label="소mo품(내시경)",
                on_hand=-5,
                avg_daily_demand=1.4,
                lead_time_days=7,
                moq=1,
                vendor="-",
                safety_stock_days=7,
                expiry_lots=[
                    ExpiryLot(sku_id="ENP00001", expiry_date="2026-12-01", qty=12.0),
                ],
            )
        ]
        sales = [WeeklySales("ENP00001", "기간합계(30일)", 9.8)]
        lots = [ExpiryLot(sku_id="ENP00001", expiry_date="2026-12-01", qty=12.0)]
        raw = snapshot_to_json(skus, sales, lots)
        restored_skus, restored_sales, restored_lots, restored_totals = parse_snapshot(raw)
        self.assertEqual(len(restored_skus), 1)
        self.assertEqual(restored_skus[0].sku_id, "ENP00001")
        self.assertEqual(restored_skus[0].on_hand, -5.0)
        self.assertEqual(len(restored_skus[0].expiry_lots), 1)
        self.assertIsNotNone(restored_sales)
        assert restored_sales is not None
        self.assertEqual(restored_sales[0].qty, 9.8)
        self.assertIsNotNone(restored_lots)
        assert restored_lots is not None
        self.assertEqual(restored_lots[0].qty, 12.0)
        self.assertIsNone(restored_totals)

    def test_snapshot_roundtrip_with_younglimwon_totals(self) -> None:
        skus = [
            SkuMaster(
                sku_id="ENP00001",
                name="테스트",
                category="endoscopy",
                category_label="소mo품(내시경)",
                on_hand=10,
                avg_daily_demand=1.0,
                lead_time_days=7,
                moq=1,
                vendor="-",
            )
        ]
        totals = {"ENP00001": 30.0}
        raw = snapshot_to_json(skus, None, None, ylw_outbound_totals=totals)
        restored_skus, _, _, restored_totals = parse_snapshot(raw)
        self.assertEqual(len(restored_skus), 1)
        self.assertEqual(restored_totals, totals)


if __name__ == "__main__":
    unittest.main()
