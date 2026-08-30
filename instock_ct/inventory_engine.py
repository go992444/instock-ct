"""Inventory calculations for Instock CT."""

from __future__ import annotations

import math
from collections import defaultdict

from instock_ct.config import DEFAULT_TARGET_COVERAGE_DAYS, RISK_CRITICAL_DOS, RISK_WARNING_DOS
from instock_ct.models import (
    ForecastResult,
    PromoImpact,
    ReorderPlan,
    SkuMaster,
    StockoutRisk,
    WeeklySales,
)


def _round_up_to_moq(qty: float, moq: int) -> int:
    if qty <= 0:
        return 0
    moq = max(1, moq)
    return int(math.ceil(qty / moq) * moq)


def classify_risk(days_of_supply: float) -> str:
    if days_of_supply <= RISK_CRITICAL_DOS:
        return "critical"
    if days_of_supply <= RISK_WARNING_DOS:
        return "warning"
    return "ok"


def risk_label(level: str) -> str:
    return {"critical": "결품 임박", "warning": "주의", "ok": "양호"}.get(level, level)


def recommended_reorder_qty(
    sku: SkuMaster,
    *,
    daily_demand: float | None = None,
    target_coverage_days: float = DEFAULT_TARGET_COVERAGE_DAYS,
) -> int:
    demand = daily_demand if daily_demand is not None else sku.avg_daily_demand
    if demand <= 0:
        return 0
    target_stock = sku.reorder_point + demand * target_coverage_days
    if sku.on_hand >= target_stock:
        return 0
    raw = target_stock - sku.on_hand
    return _round_up_to_moq(raw, sku.moq)


def assess_stockout_risk(sku: SkuMaster, *, daily_demand: float | None = None) -> StockoutRisk:
    demand = daily_demand if daily_demand is not None else sku.avg_daily_demand
    dos = sku.on_hand / demand if demand > 0 else float("inf")
    level = classify_risk(dos if dos != float("inf") else 999)
    stockout_in = dos if dos != float("inf") else None
    reorder = recommended_reorder_qty(sku, daily_demand=demand)
    return StockoutRisk(
        sku_id=sku.sku_id,
        name=sku.name,
        category_label=sku.category_label,
        on_hand=sku.on_hand,
        avg_daily_demand=demand,
        days_of_supply=dos if dos != float("inf") else 999.0,
        stockout_in_days=stockout_in,
        risk_level=level,
        reorder_qty=reorder,
        vendor=sku.vendor,
    )


def build_reorder_plan(
    sku: SkuMaster,
    *,
    daily_demand: float | None = None,
    target_coverage_days: float = DEFAULT_TARGET_COVERAGE_DAYS,
) -> ReorderPlan:
    demand = daily_demand if daily_demand is not None else sku.avg_daily_demand
    qty = recommended_reorder_qty(
        sku,
        daily_demand=demand,
        target_coverage_days=target_coverage_days,
    )
    projected_on_hand = sku.on_hand + qty
    projected_dos = projected_on_hand / demand if demand > 0 else float("inf")
    note = ""
    if qty == 0:
        note = "발주 불필요 (목표 재고 충족)"
    elif qty == sku.moq and qty > (sku.reorder_point - sku.on_hand):
        note = f"MOQ({sku.moq}) 적용"
    return ReorderPlan(
        sku_id=sku.sku_id,
        name=sku.name,
        current_on_hand=sku.on_hand,
        reorder_point=sku.reorder_point,
        recommended_qty=qty,
        projected_dos_after=projected_dos if projected_dos != float("inf") else 999.0,
        moq=sku.moq,
        lead_time_days=sku.lead_time_days,
        note=note,
    )


def simulate_promo_impact(
    sku: SkuMaster,
    *,
    promo_uplift_pct: float,
    promo_days: int = 7,
) -> PromoImpact:
    baseline_demand = sku.avg_daily_demand
    promo_demand = baseline_demand * (1 + promo_uplift_pct / 100)
    baseline_dos = sku.on_hand / baseline_demand if baseline_demand > 0 else 999.0
    promo_dos = sku.on_hand / promo_demand if promo_demand > 0 else 999.0
    extra_demand = (promo_demand - baseline_demand) * promo_days
    needed = max(0, promo_demand * (sku.lead_time_days + promo_days) + sku.safety_stock_units - sku.on_hand)
    extra_reorder = _round_up_to_moq(needed, sku.moq)
    return PromoImpact(
        sku_id=sku.sku_id,
        name=sku.name,
        baseline_dos=baseline_dos,
        promo_dos=promo_dos,
        extra_demand_total=extra_demand,
        extra_reorder_qty=extra_reorder,
        stockout_before_promo=baseline_dos < sku.lead_time_days,
        stockout_during_promo=promo_dos < promo_days,
    )


def forecast_from_weekly_sales(
    sales: list[WeeklySales],
    *,
    sku_names: dict[str, str] | None = None,
    window: int = 4,
) -> list[ForecastResult]:
    by_sku: dict[str, list[float]] = defaultdict(list)
    for row in sorted(sales, key=lambda item: (item.sku_id, item.week_start)):
        by_sku[row.sku_id].append(row.qty)

    results: list[ForecastResult] = []
    names = sku_names or {}
    for sku_id, history in by_sku.items():
        if not history:
            continue
        recent = history[-window:]
        avg_weekly = sum(recent) / len(recent)
        if len(recent) >= 2:
            trend_delta = recent[-1] - recent[0]
            trend = "상승" if trend_delta > 0 else "하락" if trend_delta < 0 else "보합"
        else:
            trend = "보합"
        forecast_next = avg_weekly
        if len(recent) >= 2:
            forecast_next = recent[-1] * 0.4 + avg_weekly * 0.6
        results.append(
            ForecastResult(
                sku_id=sku_id,
                name=names.get(sku_id, sku_id),
                history_weeks=len(history),
                avg_weekly=avg_weekly,
                forecast_next_week=forecast_next,
                suggested_daily_demand=forecast_next / 7.0,
                trend=trend,
            )
        )
    results.sort(key=lambda item: item.forecast_next_week, reverse=True)
    return results


def summarize_risk_counts(risks: list[StockoutRisk]) -> dict[str, int]:
    counts = {"critical": 0, "warning": 0, "ok": 0}
    for row in risks:
        counts[row.risk_level] = counts.get(row.risk_level, 0) + 1
    return counts
