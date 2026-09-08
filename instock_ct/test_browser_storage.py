"""Tests for browser localStorage snapshot serialization."""

from __future__ import annotations

import unittest

from instock_ct.browser_storage import parse_snapshot, snapshot_to_json
from instock_ct.models import SkuMaster, WeeklySales


class BrowserStorageTests(unittest.TestCase):
    def test_snapshot_roundtrip(self) -> None:
        skus = [
            SkuMaster(
                sku_id="ENP00001",
                name="테스트",
                category="general",
                category_label="소모품(내시경)",
                on_hand=-5,
                avg_daily_demand=1.4,
                lead_time_days=7,
                moq=1,
                vendor="-",
                safety_stock_days=7,
            )
        ]
        sales = [WeeklySales("ENP00001", "기간합계(30일)", 9.8)]
        raw = snapshot_to_json(skus, sales)
        restored_skus, restored_sales = parse_snapshot(raw)
        self.assertEqual(len(restored_skus), 1)
        self.assertEqual(restored_skus[0].sku_id, "ENP00001")
        self.assertEqual(restored_skus[0].on_hand, -5.0)
        self.assertIsNotNone(restored_sales)
        assert restored_sales is not None
        self.assertEqual(restored_sales[0].qty, 9.8)


if __name__ == "__main__":
    unittest.main()
