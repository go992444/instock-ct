"""Browser localStorage snapshot for Instock CT session data."""

from __future__ import annotations

import json
from typing import Any

from instock_ct.models import SkuMaster, WeeklySales

BROWSER_STORAGE_KEY = "instock_ct_snapshot_v1"
SNAPSHOT_VERSION = 1


def sku_to_dict(sku: SkuMaster) -> dict[str, Any]:
    return {
        "sku_id": sku.sku_id,
        "name": sku.name,
        "category": sku.category,
        "category_label": sku.category_label,
        "on_hand": sku.on_hand,
        "avg_daily_demand": sku.avg_daily_demand,
        "lead_time_days": sku.lead_time_days,
        "moq": sku.moq,
        "vendor": sku.vendor,
        "safety_stock_days": sku.safety_stock_days,
        "nearest_expiry": sku.nearest_expiry,
        "expiring_qty": sku.expiring_qty,
    }


def sku_from_dict(data: dict[str, Any]) -> SkuMaster:
    return SkuMaster(
        sku_id=str(data["sku_id"]),
        name=str(data.get("name", data["sku_id"])),
        category=str(data.get("category", "general")),
        category_label=str(data.get("category_label", "일반 소모품")),
        on_hand=float(data.get("on_hand", 0)),
        avg_daily_demand=float(data.get("avg_daily_demand", 0)),
        lead_time_days=int(data.get("lead_time_days", 7)),
        moq=int(data.get("moq", 1)),
        vendor=str(data.get("vendor", "-")),
        safety_stock_days=float(data.get("safety_stock_days", 7)),
        nearest_expiry=data.get("nearest_expiry"),
        expiring_qty=data.get("expiring_qty"),
    )


def weekly_sale_to_dict(row: WeeklySales) -> dict[str, Any]:
    return {
        "sku_id": row.sku_id,
        "week_start": row.week_start,
        "qty": row.qty,
    }


def weekly_sale_from_dict(data: dict[str, Any]) -> WeeklySales:
    return WeeklySales(
        sku_id=str(data["sku_id"]),
        week_start=str(data.get("week_start", "")),
        qty=float(data.get("qty", 0)),
    )


def build_snapshot(
    skus: list[SkuMaster],
    imported_sales: list[WeeklySales] | None,
) -> dict[str, Any]:
    return {
        "version": SNAPSHOT_VERSION,
        "skus": [sku_to_dict(sku) for sku in skus],
        "imported_sales": [weekly_sale_to_dict(row) for row in (imported_sales or [])],
    }


def parse_snapshot(raw: str) -> tuple[list[SkuMaster], list[WeeklySales] | None]:
    payload = json.loads(raw)
    if payload.get("version") != SNAPSHOT_VERSION:
        raise ValueError("unsupported snapshot version")
    skus = [sku_from_dict(item) for item in payload.get("skus", [])]
    if not skus:
        raise ValueError("empty sku list")
    sales_raw = payload.get("imported_sales") or []
    imported_sales = [weekly_sale_from_dict(item) for item in sales_raw] if sales_raw else None
    return skus, imported_sales


def snapshot_to_json(
    skus: list[SkuMaster],
    imported_sales: list[WeeklySales] | None,
) -> str:
    return json.dumps(build_snapshot(skus, imported_sales), ensure_ascii=False)
