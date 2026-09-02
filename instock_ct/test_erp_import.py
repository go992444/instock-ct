"""Tests for ERP CSV import."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from instock_ct.erp_import import is_korean_sales_frame, parse_native_sales_frame, parse_sales_csv, parse_sku_csv

SAMPLES = Path(__file__).resolve().parent / "samples"


class ErpImportTests(unittest.TestCase):
    def test_parse_korean_inventory_export(self) -> None:
        frame = pd.read_csv(SAMPLES / "erp_inventory_export.sample.csv")
        skus, report = parse_sku_csv(frame, preset="erp_korean")
        self.assertTrue(report.ok)
        self.assertEqual(len(skus), 5)
        self.assertEqual(skus[0].sku_id, "MC-001")
        self.assertEqual(skus[0].category, "medical_consumable")

    def test_parse_korean_weekly_shipment(self) -> None:
        frame = pd.read_csv(SAMPLES / "erp_weekly_shipment.sample.csv")
        sales, report = parse_sales_csv(frame, preset="erp_korean")
        self.assertTrue(report.ok)
        self.assertEqual(len(sales), 8)
        self.assertEqual(sales[0].sku_id, "MC-001")

    def test_parse_native_sales_skips_bad_qty(self) -> None:
        frame = pd.DataFrame(
            [
                {"sku_id": "MC-001", "week_start": "2026-01-06", "qty": 100},
                {"sku_id": "MC-002", "week_start": "2026-01-06", "qty": "7.6,7.4"},
                {"sku_id": "MC-003", "week_start": "2026-01-06", "qty": "55"},
            ]
        )
        sales, report = parse_native_sales_frame(frame)
        self.assertTrue(report.ok)
        self.assertEqual(len(sales), 2)
        self.assertEqual(len(report.warnings), 1)

    def test_detect_korean_sales_columns(self) -> None:
        frame = pd.read_csv(SAMPLES / "erp_weekly_shipment.sample.csv")
        self.assertTrue(is_korean_sales_frame(frame))


if __name__ == "__main__":
    unittest.main()
