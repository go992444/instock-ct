"""Expiry date risk calculations for Instock CT."""

from __future__ import annotations

from datetime import date, datetime

from instock_ct.config import (
    DEFAULT_EXPIRY_THRESHOLDS_BY_CATEGORY,
    EXPIRY_CRITICAL_DAYS,
    EXPIRY_WARNING_DAYS,
)
from instock_ct.models import ExpiryAlert, ExpiryLot, SkuMaster


def get_expiry_thresholds(
    category: str,
    thresholds_by_category: dict[str, tuple[float, float]] | None = None,
) -> tuple[float, float]:
    """Return (critical_days, warning_days) for a SKU category."""
    source = thresholds_by_category or DEFAULT_EXPIRY_THRESHOLDS_BY_CATEGORY
    if category in source:
        critical, warning = source[category]
    else:
        critical, warning = EXPIRY_CRITICAL_DAYS, EXPIRY_WARNING_DAYS
    critical = max(0.0, float(critical))
    warning = max(critical + 1.0, float(warning))
    return critical, warning


def parse_expiry_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "-", "n/a"}:
        return None
    text = text.replace(".", "-").replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text[:10])
        return parsed.date()
    except ValueError:
        return None


def days_until_expiry(expiry: str, *, today: date | None = None) -> int | None:
    expiry_date = parse_expiry_date(expiry)
    if expiry_date is None:
        return None
    ref = today or date.today()
    return (expiry_date - ref).days


def classify_expiry(
    days_remaining: int,
    *,
    critical_days: float = EXPIRY_CRITICAL_DAYS,
    warning_days: float = EXPIRY_WARNING_DAYS,
) -> str:
    if days_remaining < 0:
        return "expired"
    if days_remaining <= critical_days:
        return "critical"
    if days_remaining <= warning_days:
        return "warning"
    return "ok"


def expiry_label(level: str) -> str:
    return {
        "expired": "기한 경과",
        "critical": "임박",
        "warning": "주의",
        "ok": "양호",
    }.get(level, level)


def recommended_expiry_action(alert: ExpiryAlert) -> str:
    if alert.risk_level == "expired":
        return "즉시 격리·폐기/반품 검토"
    if alert.risk_level == "critical":
        return "FEFO 우선 출고·할인/대체품 검토"
    if alert.risk_level == "warning":
        return "출고 순서 조정·차기 발주량 조절"
    return "정상 — 모니터링 유지"


def assess_expiry(
    sku: SkuMaster,
    *,
    today: date | None = None,
    critical_days: float | None = None,
    warning_days: float | None = None,
    thresholds_by_category: dict[str, tuple[float, float]] | None = None,
) -> ExpiryAlert | None:
    if not sku.nearest_expiry:
        return None

    remaining = days_until_expiry(sku.nearest_expiry, today=today)
    if remaining is None:
        return None

    if critical_days is None or warning_days is None:
        crit, warn = get_expiry_thresholds(sku.category, thresholds_by_category)
    else:
        crit = max(0.0, float(critical_days))
        warn = max(crit + 1.0, float(warning_days))

    qty = sku.expiring_qty if sku.expiring_qty is not None else sku.on_hand
    level = classify_expiry(
        remaining,
        critical_days=crit,
        warning_days=warn,
    )
    action = recommended_expiry_action(
        ExpiryAlert(
            sku_id=sku.sku_id,
            name=sku.name,
            category_label=sku.category_label,
            on_hand=sku.on_hand,
            expiring_qty=qty,
            expiry_date=sku.nearest_expiry,
            days_remaining=remaining,
            risk_level=level,
            vendor=sku.vendor,
            action="",
            critical_threshold_days=crit,
            warning_threshold_days=warn,
        )
    )
    return ExpiryAlert(
        sku_id=sku.sku_id,
        name=sku.name,
        category_label=sku.category_label,
        on_hand=sku.on_hand,
        expiring_qty=qty,
        expiry_date=sku.nearest_expiry,
        days_remaining=remaining,
        risk_level=level,
        vendor=sku.vendor,
        action=action,
        critical_threshold_days=crit,
        warning_threshold_days=warn,
    )


def assess_expiry_lot(
    sku: SkuMaster,
    lot: ExpiryLot,
    *,
    today: date | None = None,
    critical_days: float | None = None,
    warning_days: float | None = None,
    thresholds_by_category: dict[str, tuple[float, float]] | None = None,
) -> ExpiryAlert | None:
    remaining = days_until_expiry(lot.expiry_date, today=today)
    if remaining is None:
        return None

    if critical_days is None or warning_days is None:
        crit, warn = get_expiry_thresholds(sku.category, thresholds_by_category)
    else:
        crit = max(0.0, float(critical_days))
        warn = max(crit + 1.0, float(warning_days))

    level = classify_expiry(
        remaining,
        critical_days=crit,
        warning_days=warn,
    )
    draft = ExpiryAlert(
        sku_id=sku.sku_id,
        name=sku.name,
        category_label=sku.category_label,
        on_hand=sku.on_hand,
        expiring_qty=lot.qty,
        expiry_date=lot.expiry_date,
        days_remaining=remaining,
        risk_level=level,
        vendor=sku.vendor,
        action="",
        critical_threshold_days=crit,
        warning_threshold_days=warn,
    )
    return ExpiryAlert(
        sku_id=sku.sku_id,
        name=sku.name,
        category_label=sku.category_label,
        on_hand=sku.on_hand,
        expiring_qty=lot.qty,
        expiry_date=lot.expiry_date,
        days_remaining=remaining,
        risk_level=level,
        vendor=sku.vendor,
        action=recommended_expiry_action(draft),
        critical_threshold_days=crit,
        warning_threshold_days=warn,
    )


def build_expiry_alerts(
    skus: list[SkuMaster],
    *,
    today: date | None = None,
    thresholds_by_category: dict[str, tuple[float, float]] | None = None,
    critical_days: float = EXPIRY_CRITICAL_DAYS,
    warning_days: float = EXPIRY_WARNING_DAYS,
) -> list[ExpiryAlert]:
    alerts: list[ExpiryAlert] = []
    for sku in skus:
        if thresholds_by_category is not None:
            crit, warn = get_expiry_thresholds(sku.category, thresholds_by_category)
        else:
            crit, warn = critical_days, warning_days
        alert = assess_expiry(
            sku,
            today=today,
            critical_days=crit,
            warning_days=warn,
        )
        if alert:
            alerts.append(alert)
    alerts.sort(key=lambda row: (row.days_remaining, row.sku_id))
    return alerts


def build_expiry_lot_alerts(
    skus: list[SkuMaster],
    *,
    today: date | None = None,
    thresholds_by_category: dict[str, tuple[float, float]] | None = None,
    critical_days: float = EXPIRY_CRITICAL_DAYS,
    warning_days: float = EXPIRY_WARNING_DAYS,
) -> list[ExpiryAlert]:
    """Build one alert per WMS lot row; fall back to SKU summary when no lots."""
    alerts: list[ExpiryAlert] = []
    for sku in skus:
        if sku.expiry_lots:
            for lot in sku.expiry_lots:
                if thresholds_by_category is not None:
                    crit, warn = get_expiry_thresholds(sku.category, thresholds_by_category)
                else:
                    crit, warn = critical_days, warning_days
                alert = assess_expiry_lot(
                    sku,
                    lot,
                    today=today,
                    critical_days=crit,
                    warning_days=warn,
                )
                if alert:
                    alerts.append(alert)
            continue
        if thresholds_by_category is not None:
            crit, warn = get_expiry_thresholds(sku.category, thresholds_by_category)
        else:
            crit, warn = critical_days, warning_days
        alert = assess_expiry(
            sku,
            today=today,
            critical_days=crit,
            warning_days=warn,
        )
        if alert:
            alerts.append(alert)
    alerts.sort(key=lambda row: (row.days_remaining, row.sku_id, row.expiry_date))
    return alerts


def summarize_expiry_counts(alerts: list[ExpiryAlert]) -> dict[str, int]:
    counts = {"expired": 0, "critical": 0, "warning": 0, "ok": 0}
    for alert in alerts:
        counts[alert.risk_level] = counts.get(alert.risk_level, 0) + 1
    return counts
