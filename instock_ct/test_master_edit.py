"""Tests for master edit save parsing."""

from __future__ import annotations

import unittest

import pandas as pd

from instock_ct.app import _parse_edit_frame


class MasterEditTests(unittest.TestCase):
    def test_allows_negative_on_hand(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "품목코드": "FF16441294",
                    "품명": "마이너스 재고 테스트",
                    "카테고리": "소모품(내시경)",
                    "현재고": -12,
                    "일평균출고": 0.3,
                    "리드타임일": 0,
                    "MOQ": 0,
                    "거래처명": "-",
                    "안전재고일": 7,
                    "유통기한": "",
                    "임박재고": "",
                }
            ]
        )
        skus, errors = _parse_edit_frame(frame)
        self.assertEqual(errors, [])
        self.assertIsNotNone(skus)
        assert skus is not None
        self.assertEqual(skus[0].on_hand, -12.0)
        self.assertEqual(skus[0].lead_time_days, 1)
        self.assertEqual(skus[0].moq, 1)


if __name__ == "__main__":
    unittest.main()
