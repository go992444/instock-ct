"""Browser localStorage snapshot for Instock CT session data."""

from __future__ import annotations

import json
from typing import Any

from instock_ct.models import ExpiryLot, SkuMaster, WeeklySales

BROWSER_STORAGE_KEY = "instock_ct_snapshot_v1"
SNAPSHOT_VERSION = 2


def expiry_lot_to_dict(lot: ExpiryLot) -> dict[str, Any]:
    return {
        "sku_id": lot.sku_id,
        "expiry_date": lot.expiry_date,
        "qty": lot.qty,
    }


def expiry_lot_from_dict(data: dict[str, Any]) -> ExpiryLot:
    return ExpiryLot(
        sku_id=str(data["sku_id"]),
        expiry_date=str(data.get("expiry_date", "")),
        qty=float(data.get("qty", 0)),
    )


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
        "expiry_lots": [expiry_lot_to_dict(lot) for lot in sku.expiry_lots],
    }


def sku_from_dict(data: dict[str, Any]) -> SkuMaster:
    lots_raw = data.get("expiry_lots") or []
    expiry_lots = [expiry_lot_from_dict(item) for item in lots_raw if isinstance(item, dict)]
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
        expiry_lots=expiry_lots,
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
    expiry_lots: list[ExpiryLot] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": SNAPSHOT_VERSION,
        "skus": [sku_to_dict(sku) for sku in skus],
        "imported_sales": [weekly_sale_to_dict(row) for row in (imported_sales or [])],
    }
    if expiry_lots:
        payload["expiry_lots"] = [expiry_lot_to_dict(lot) for lot in expiry_lots]
    return payload


def parse_snapshot(
    raw: str,
) -> tuple[list[SkuMaster], list[WeeklySales] | None, list[ExpiryLot] | None]:
    payload = json.loads(raw)
    version = payload.get("version", 1)
    if version not in (1, SNAPSHOT_VERSION):
        raise ValueError("unsupported snapshot version")
    skus = [sku_from_dict(item) for item in payload.get("skus", [])]
    if not skus:
        raise ValueError("empty sku list")
    sales_raw = payload.get("imported_sales") or []
    imported_sales = [weekly_sale_from_dict(item) for item in sales_raw] if sales_raw else None

    expiry_lots: list[ExpiryLot] | None = None
    lots_raw = payload.get("expiry_lots")
    if lots_raw:
        expiry_lots = [expiry_lot_from_dict(item) for item in lots_raw if isinstance(item, dict)]
    elif version >= SNAPSHOT_VERSION:
        flattened: list[ExpiryLot] = []
        for sku in skus:
            flattened.extend(sku.expiry_lots)
        expiry_lots = flattened or None

    return skus, imported_sales, expiry_lots


def snapshot_to_json(
    skus: list[SkuMaster],
    imported_sales: list[WeeklySales] | None,
    expiry_lots: list[ExpiryLot] | None = None,
) -> str:
    if expiry_lots is None:
        flattened: list[ExpiryLot] = []
        for sku in skus:
            flattened.extend(sku.expiry_lots)
        expiry_lots = flattened or None
    return json.dumps(build_snapshot(skus, imported_sales, expiry_lots), ensure_ascii=False)
