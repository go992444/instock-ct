"""Generate sample weekly sales for demo forecast tab."""

from __future__ import annotations

import random
from datetime import date, timedelta

from instock_ct.config import DEFAULT_SKUS
from instock_ct.models import WeeklySales

random.seed(42)


def build_sample_weekly_sales(weeks: int = 12) -> list[WeeklySales]:
    start = date(2026, 6, 9)
    rows: list[WeeklySales] = []
    for sku in DEFAULT_SKUS:
        base_weekly = sku.avg_daily_demand * 7
        for week_index in range(weeks):
            week_start = start + timedelta(weeks=week_index)
            noise = random.uniform(0.85, 1.15)
            trend = 1 + week_index * 0.01
            qty = max(0, round(base_weekly * noise * trend, 1))
            rows.append(
                WeeklySales(
                    sku_id=sku.sku_id,
                    week_start=week_start.isoformat(),
                    qty=qty,
                )
            )
    return rows


def weekly_sales_to_dataframe_rows(sales: list[WeeklySales]) -> list[dict]:
    return [{"sku_id": s.sku_id, "week_start": s.week_start, "qty": s.qty} for s in sales]
