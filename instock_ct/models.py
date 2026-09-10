"""Data models for Instock CT."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExpiryLot:
    sku_id: str
    expiry_date: str
    qty: float


@dataclass
class SkuMaster:
    sku_id: str
    name: str
    category: str
    category_label: str
    on_hand: float
    avg_daily_demand: float
    lead_time_days: int
    moq: int
    vendor: str
    safety_stock_days: float = 7.0
    nearest_expiry: str | None = None
    expiring_qty: float | None = None
    expiry_lots: list[ExpiryLot] = field(default_factory=list)

    @property
    def safety_stock_units(self) -> float:
        return self.avg_daily_demand * self.safety_stock_days

    @property
    def days_of_supply(self) -> float:
        if self.avg_daily_demand <= 0:
            return float("inf")
        return self.on_hand / self.avg_daily_demand

    @property
    def reorder_point(self) -> float:
        return self.avg_daily_demand * self.lead_time_days + self.safety_stock_units


@dataclass(frozen=True)
class ExpiryAlert:
    sku_id: str
    name: str
    category_label: str
    on_hand: float
    expiring_qty: float
    expiry_date: str
    days_remaining: int
    risk_level: str
    vendor: str
    action: str
    critical_threshold_days: float = 0.0
    warning_threshold_days: float = 0.0


@dataclass(frozen=True)
class StockoutRisk:
    sku_id: str
    name: str
    category: str
    category_label: str
    on_hand: float
    avg_daily_demand: float
    days_of_supply: float
    stockout_in_days: float | None
    risk_level: str
    reorder_qty: int
    vendor: str
    annual_turnover: float | None = None


@dataclass(frozen=True)
class ReorderPlan:
    sku_id: str
    name: str
    current_on_hand: float
    reorder_point: float
    recommended_qty: int
    projected_dos_after: float
    moq: int
    lead_time_days: int
    note: str = ""


@dataclass
class PromoImpact:
    sku_id: str
    name: str
    baseline_dos: float
    promo_dos: float
    extra_demand_total: float
    extra_reorder_qty: int
    stockout_before_promo: bool
    stockout_during_promo: bool


@dataclass
class WeeklySales:
    sku_id: str
    week_start: str
    qty: float


@dataclass
class ForecastResult:
    sku_id: str
    name: str
    history_weeks: int
    avg_weekly: float
    forecast_next_week: float
    suggested_daily_demand: float
    trend: str
