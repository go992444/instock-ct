"""Tests for server-side session snapshot files."""

from __future__ import annotations

import unittest
import uuid

from instock_ct.models import SkuMaster
from instock_ct.session_persist import (
    PERSIST_DIR,
    delete_server_snapshot,
    load_server_snapshot,
    save_server_snapshot,
)


class SessionPersistTests(unittest.TestCase):
    def setUp(self) -> None:
        PERSIST_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        for path in PERSIST_DIR.glob("*.json"):
            path.unlink(missing_ok=True)

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


if __name__ == "__main__":
    unittest.main()
