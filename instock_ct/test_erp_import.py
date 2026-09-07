"""Tests for ERP CSV import."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from instock_ct.erp_import import (
    is_korean_sales_frame,
    parse_native_sales_frame,
    parse_sales_csv,
    parse_sales_upload,
    parse_sku_csv,
    parse_younglimwon_aggregated_sales,
    parse_younglimwon_inventory,
    read_uploaded_csv,
)

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

    def test_parse_younglimwon_inventory(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "품목번호": "A-001",
                    "품명": "테스트A",
                    "출고계": 30,
                    "재고수량": 100,
                    "품목분류2": "소모품",
                },
                {
                    "품목번호": "B-002",
                    "품명": "테스트B",
                    "출고계": 5,
                    "재고수량": 50,
                    "품목분류2": "소모품",
                },
                {"품목번호": "TOTAL", "품명": None, "출고계": 35, "재고수량": 150},
            ]
        )
        skus, report = parse_younglimwon_inventory(frame, min_outbound=10, period_days=30)
        self.assertTrue(report.ok)
        self.assertEqual(len(skus), 1)
        self.assertEqual(skus[0].sku_id, "A-001")
        self.assertAlmostEqual(skus[0].avg_daily_demand, 1.0)
        self.assertEqual(skus[0].on_hand, 100.0)

    def test_parse_minimal_columns(self) -> None:
        frame = pd.DataFrame(
            [{"품목코드": "A-001", "품명": "테스트", "현재재고": 50}],
        )
        skus, report = parse_sku_csv(frame, preset="erp_korean")
        self.assertTrue(report.ok)
        self.assertEqual(len(skus), 1)
        self.assertEqual(skus[0].on_hand, 50.0)
        self.assertEqual(skus[0].avg_daily_demand, 0.0)
        self.assertEqual(skus[0].lead_time_days, 7)

    def test_parse_younglimwon_aggregated_sales(self) -> None:
        frame = pd.DataFrame(
            [
                {"품목번호": "A-001", "출고계": 30, "재고수량": 100},
                {"품목번호": "B-002", "출고계": 5, "재고수량": 50},
            ]
        )
        sales, report = parse_younglimwon_aggregated_sales(
            frame, min_outbound=10, period_days=30
        )
        self.assertTrue(report.ok)
        self.assertEqual(len(sales), 1)
        self.assertEqual(sales[0].sku_id, "A-001")
        self.assertAlmostEqual(sales[0].qty, 7.0)

    def test_parse_sales_upload_redirects_inventory(self) -> None:
        frame = pd.read_csv(SAMPLES / "erp_inventory_export.sample.csv")
        sales, report = parse_sales_upload(frame, preset="erp_korean")
        self.assertFalse(report.ok)
        self.assertEqual(len(sales), 0)
        self.assertIn("재고", report.messages[0])

    def test_read_uploaded_csv_cp949(self) -> None:
        from io import BytesIO

        class FakeUpload:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def getvalue(self) -> bytes:
                return self._data

            def seek(self, _pos: int) -> None:
                return None

        text = "품목코드,주간시작일,출고수량\nA-001,2026-01-06,10\n"
        upload = FakeUpload(text.encode("cp949"))
        frame = read_uploaded_csv(upload)
        self.assertEqual(list(frame.columns), ["품목코드", "주간시작일", "출고수량"])


if __name__ == "__main__":
    unittest.main()
