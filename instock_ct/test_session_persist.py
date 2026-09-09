"""Tests for server-side session snapshot files."""

from __future__ import annotations

import unittest
import uuid

from instock_ct.models import SkuMaster
from instock_ct.session_persist import (
    GLOBAL_SNAPSHOT_PATH,
    PERSIST_DIR,
    delete_server_snapshot,
    is_demo_skus,
    load_server_snapshot,
    save_server_snapshot,
)
from instock_ct.config import DEFAULT_SKUS


class SessionPersistTests(unittest.TestCase):
    def setUp(self) -> None:
        from instock_ct.session_persist import _resolve_persist_dir

        self.persist_dir = _resolve_persist_dir()
        self.persist_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        from instock_ct.session_persist import GLOBAL_SNAPSHOT_PATH

        for path in self.persist_dir.glob("*.json"):
            path.unlink(missing_ok=True)
        if GLOBAL_SNAPSHOT_PATH.is_file():
            GLOBAL_SNAPSHOT_PATH.unlink(missing_ok=True)

    def test_server_snapshot_roundtrip(self) -> None:
        client_id = str(uuid.uuid4())
        skus = [
            SkuMaster(
                sku_id="ENP00001",
                name="테스트",
                category="general",
                category_label="소모품",
                on_hand=-3,
                avg_daily_demand=2.0,
                lead_time_days=7,
                moq=1,
                vendor="-",
                safety_stock_days=7,
            )
        ]
        save_server_snapshot(client_id, skus, None)
        restored = load_server_snapshot(client_id)
        self.assertIsNotNone(restored)
        assert restored is not None
        restored_skus, _ = restored
        self.assertEqual(restored_skus[0].sku_id, "ENP00001")
        self.assertEqual(restored_skus[0].on_hand, -3.0)

        delete_server_snapshot(client_id)
        self.assertIsNone(load_server_snapshot(client_id))

    def test_demo_skus_detection(self) -> None:
        self.assertTrue(is_demo_skus(list(DEFAULT_SKUS)))
        custom = [
            SkuMaster(
                sku_id="ENP00001",
                name="테스트",
                category="general",
                category_label="소모품",
                on_hand=1,
                avg_daily_demand=2.0,
                lead_time_days=7,
                moq=1,
                vendor="-",
                safety_stock_days=7,
            )
        ]
        self.assertFalse(is_demo_skus(custom))

    def test_global_snapshot_fallback(self) -> None:
        client_id = str(uuid.uuid4())
        skus = [
            SkuMaster(
                sku_id="ENP00099",
                name="글로벌",
                category="general",
                category_label="소모품",
                on_hand=5,
                avg_daily_demand=1.0,
                lead_time_days=7,
                moq=1,
                vendor="-",
                safety_stock_days=7,
            )
        ]
        save_server_snapshot(client_id, skus, None)
        self.assertTrue(GLOBAL_SNAPSHOT_PATH.is_file())
        other_id = str(uuid.uuid4())
        restored = load_server_snapshot(other_id)
        self.assertIsNotNone(restored)
        assert restored is not None
        restored_skus, _ = restored
        self.assertEqual(restored_skus[0].sku_id, "ENP00099")


if __name__ == "__main__":
    unittest.main()
