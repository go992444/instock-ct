"""Parse ERP / WMS CSV exports into Instock CT models."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from instock_ct.config import CATEGORIES, DEFAULT_SKUS
from instock_ct.models import SkuMaster, WeeklySales

# Canonical internal column names
CANONICAL_SKU_COLUMNS = (
    "sku_id",
    "name",
    "category",
    "category_label",
    "on_hand",
    "avg_daily_demand",
    "lead_time_days",
    "moq",
    "vendor",
    "safety_stock_days",
)

CANONICAL_SALES_COLUMNS = ("sku_id", "week_start", "qty")

# Preset: typical Korean ERP / spreadsheet export (fictional layout)
ERP_KOREAN_SKU_MAP: dict[str, str] = {
    "품목코드": "sku_id",
    "상품코드": "sku_id",
    "sku": "sku_id",
    "품명": "name",
    "상품명": "name",
    "카테고리": "category_label",
    "분류": "category_label",
    "현재고": "on_hand",
    "재고수량": "on_hand",
    "가용재고": "on_hand",
    "일평균출고": "avg_daily_demand",
    "일출고": "avg_daily_demand",
    "평균일출고": "avg_daily_demand",
    "리드타임": "lead_time_days",
    "리드타임일": "lead_time_days",
    "납기일수": "lead_time_days",
    "moq": "moq",
    "MOQ": "moq",
    "최소발주": "moq",
    "거래처": "vendor",
    "거래처명": "vendor",
    "매입처": "vendor",
    "안전재고일": "safety_stock_days",
    "안전일수": "safety_stock_days",
}

ERP_KOREAN_SALES_MAP: dict[str, str] = {
    "품목코드": "sku_id",
    "상품코드": "sku_id",
    "sku_id": "sku_id",
    "주차": "week_start",
    "주간시작일": "week_start",
    "week_start": "week_start",
    "일자": "week_start",
    "출고일": "week_start",
    "출고수량": "qty",
    "수량": "qty",
    "qty": "qty",
}

CATEGORY_LABEL_TO_CODE: dict[str, str] = {
    "의료기기 소mo품": "medical_consumable",
    "의료기기 소모품": "medical_consumable",
    "의료소mo품": "medical_consumable",
    "소mo품": "medical_consumable",
    "pb": "pb",
    "PB": "pb",
    "자사PB": "pb",
    "한약재": "herbal",
    "일반 소mo품": "general",
    "일반 소모품": "general",
    "사무/소모품": "general",
    "의료기기": "medical_equipment",
    "장비": "medical_equipment",
}

PRESET_LABELS = {
    "instock_native": "기본 형식 (영문 컬럼)",
    "erp_korean": "ERP 한글 형식 (품목코드·현재고·일평균출고)",
}


@dataclass
class ImportReport:
    ok: bool
    row_count: int
    messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def coerce_float(value: object, *, default: float | None = None) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"none", "nan", "-"}:
            return default
        text = text.replace(",", "")
        try:
            return float(text)
        except ValueError:
            return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(result):
        return default
    return result


def is_korean_sales_frame(frame: pd.DataFrame) -> bool:
    cols = {str(column).strip() for column in frame.columns}
    return bool(cols & {"품목코드", "주간시작일", "출고수량", "상품코드"})


def _normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def _rename_with_map(frame: pd.DataFrame, column_map: dict[str, str]) -> pd.DataFrame:
    rename: dict[str, str] = {}
    for col in frame.columns:
        key = col.strip()
        if key in column_map:
            rename[col] = column_map[key]
        elif key.lower() in {k.lower(): v for k, v in column_map.items()}:
            for k, v in column_map.items():
                if k.lower() == key.lower():
                    rename[col] = v
                    break
    return frame.rename(columns=rename)


def _resolve_category(label: str) -> tuple[str, str]:
    text = (label or "").strip()
    if not text:
        return "general", CATEGORIES["general"]
    code = CATEGORY_LABEL_TO_CODE.get(text)
    if code:
        return code, CATEGORIES[code]
    lowered = text.lower()
    for key, cat_code in CATEGORY_LABEL_TO_CODE.items():
        if key.lower() == lowered:
            return cat_code, CATEGORIES[cat_code]
    if text in CATEGORIES:
        return text, CATEGORIES[text]
    return "general", text


def parse_sku_csv(
    frame: pd.DataFrame,
    *,
    preset: str = "erp_korean",
) -> tuple[list[SkuMaster], ImportReport]:
    frame = _normalize_columns(frame)
    if preset == "instock_native":
        mapped = frame.copy()
        mapped.columns = [c.lower() for c in mapped.columns]
    else:
        mapped = _rename_with_map(frame, ERP_KOREAN_SKU_MAP)
        mapped.columns = [str(c).lower() for c in mapped.columns]

    required = {"sku_id", "name", "on_hand", "avg_daily_demand"}
    missing = required - set(mapped.columns)
    report = ImportReport(ok=not missing, row_count=len(mapped), messages=[], warnings=[])
    if missing:
        report.messages.append(f"필수 컬럼 누락: {', '.join(sorted(missing))}")
        return [], report

    skus: list[SkuMaster] = []
    seen: set[str] = set()
    for index, row in mapped.iterrows():
        sku_id = str(row.get("sku_id", "")).strip()
        if not sku_id or sku_id in seen:
            if sku_id in seen:
                report.warnings.append(f"중복 SKU 무시: {sku_id} (행 {index + 2})")
            continue
        seen.add(sku_id)
        name = str(row.get("name", sku_id)).strip()
        cat_label_raw = str(row.get("category_label", row.get("category", "일반 소모품"))).strip()
        if "category" in mapped.columns and pd.notna(row.get("category")):
            cat_code = str(row.get("category")).strip()
            cat_label = CATEGORIES.get(cat_code, cat_label_raw)
        else:
            cat_code, cat_label = _resolve_category(cat_label_raw)

        on_hand = coerce_float(row.get("on_hand"), default=None)
        avg_daily = coerce_float(row.get("avg_daily_demand"), default=None)
        lead_time_raw = coerce_float(row.get("lead_time_days", 7), default=None)
        moq_raw = coerce_float(row.get("moq", 1), default=None)
        safety_raw = coerce_float(row.get("safety_stock_days", 7), default=None)
        if None in (on_hand, avg_daily, lead_time_raw, moq_raw, safety_raw):
            report.warnings.append(f"{sku_id}: 숫자 변환 실패")
            continue
        lead_time = int(lead_time_raw)
        moq = int(moq_raw)
        safety = float(safety_raw)
        vendor = str(row.get("vendor", "-")).strip() or "-"

        if avg_daily <= 0:
            report.warnings.append(f"{sku_id}: 일평균출고 0 — 결품 계산 제외 권장")

        skus.append(
            SkuMaster(
                sku_id=sku_id,
                name=name,
                category=cat_code,
                category_label=cat_label,
                on_hand=on_hand,
                avg_daily_demand=avg_daily,
                lead_time_days=max(1, lead_time),
                moq=max(1, moq),
                vendor=vendor,
                safety_stock_days=max(0.0, safety),
            )
        )

    report.ok = len(skus) > 0
    report.row_count = len(skus)
    if skus:
        report.messages.append(f"SKU {len(skus)}건 로드 완료")
    return skus, report


def parse_sales_csv(
    frame: pd.DataFrame,
    *,
    preset: str = "erp_korean",
) -> tuple[list[WeeklySales], ImportReport]:
    frame = _normalize_columns(frame)
    if preset == "instock_native":
        mapped = frame.copy()
        mapped.columns = [c.lower() for c in mapped.columns]
    else:
        mapped = _rename_with_map(frame, ERP_KOREAN_SALES_MAP)
        mapped.columns = [str(c).lower() for c in mapped.columns]

    required = set(CANONICAL_SALES_COLUMNS)
    missing = required - set(mapped.columns)
    report = ImportReport(ok=not missing, row_count=len(mapped), messages=[], warnings=[])
    if missing:
        report.messages.append(f"필수 컬럼 누락: {', '.join(sorted(missing))}")
        return [], report

    sales: list[WeeklySales] = []
    for index, row in mapped.iterrows():
        sku_id = str(row.get("sku_id", "")).strip()
        if not sku_id:
            continue
        week = str(row.get("week_start", "")).strip()
        qty = coerce_float(row.get("qty", 0), default=None)
        if qty is None:
            report.warnings.append(
                f"행 {index + 2} ({sku_id}): 출고수량 형식 오류 — '{row.get('qty')}'"
            )
            continue
        sales.append(WeeklySales(sku_id=sku_id, week_start=week, qty=qty))

    report.ok = len(sales) > 0
    report.row_count = len(sales)
    report.messages.append(f"출고 이력 {len(sales)}건 로드 완료")
    return sales, report


def parse_native_sales_frame(frame: pd.DataFrame) -> tuple[list[WeeklySales], ImportReport]:
    mapped = frame.copy()
    mapped.columns = [str(column).strip().lower() for column in mapped.columns]
    required = set(CANONICAL_SALES_COLUMNS)
    missing = required - set(mapped.columns)
    report = ImportReport(ok=not missing, row_count=len(mapped), messages=[], warnings=[])
    if missing:
        report.messages.append(f"필수 컬럼 누락: {', '.join(sorted(missing))}")
        return [], report

    sales: list[WeeklySales] = []
    for index, row in mapped.iterrows():
        sku_id = str(row.get("sku_id", "")).strip()
        if not sku_id:
            continue
        week = str(row.get("week_start", "")).strip()
        qty = coerce_float(row.get("qty"), default=None)
        if qty is None:
            report.warnings.append(
                f"행 {index + 2} ({sku_id}): 출고수량 형식 오류 — '{row.get('qty')}'"
            )
            continue
        sales.append(WeeklySales(sku_id=sku_id, week_start=week, qty=qty))

    report.ok = len(sales) > 0
    report.row_count = len(sales)
    if sales:
        report.messages.append(f"출고 이력 {len(sales)}건 로드 완료")
    else:
        report.messages.append("읽을 수 있는 출고 행이 없습니다.")
    return sales, report


def skus_to_erp_export_frame(skus: list[SkuMaster]) -> pd.DataFrame:
    """Reorder suggestion export compatible with Korean ERP-style columns."""
    rows = []
    for sku in skus:
        rows.append(
            {
                "품목코드": sku.sku_id,
                "품명": sku.name,
                "카테고리": sku.category_label,
                "현재고": sku.on_hand,
                "일평균출고": sku.avg_daily_demand,
                "리드타임일": sku.lead_time_days,
                "MOQ": sku.moq,
                "거래처명": sku.vendor,
                "안전재고일": sku.safety_stock_days,
            }
        )
    return pd.DataFrame(rows)


def build_sample_erp_sku_csv_bytes() -> bytes:
    frame = skus_to_erp_export_frame(list(DEFAULT_SKUS)[:15])
    return frame.to_csv(index=False).encode("utf-8-sig")


def build_reorder_export_frame(
    skus: list[SkuMaster],
    *,
    target_coverage_days: float = 21.0,
) -> pd.DataFrame:
    from instock_ct.inventory_engine import build_reorder_plan

    rows = []
    for sku in skus:
        plan = build_reorder_plan(sku, target_coverage_days=target_coverage_days)
        if plan.recommended_qty <= 0:
            continue
        rows.append(
            {
                "품목코드": sku.sku_id,
                "품명": sku.name,
                "권장발주수량": plan.recommended_qty,
                "MOQ": plan.moq,
                "리드타임일": plan.lead_time_days,
                "거래처명": sku.vendor,
                "비고": plan.note or "발주 추천",
            }
        )
    return pd.DataFrame(rows)
