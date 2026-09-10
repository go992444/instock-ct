"""Parse ERP / WMS CSV exports into Instock CT models."""

from __future__ import annotations

import copy
import io
from dataclasses import dataclass, field

import pandas as pd

from instock_ct.config import CATEGORIES, DEFAULT_SKUS
from instock_ct.models import ExpiryLot, SkuMaster, WeeklySales

try:
    from instock_ct.expiry_engine import parse_expiry_date
except ImportError:  # pragma: no cover
    parse_expiry_date = None  # type: ignore[assignment]

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
    "품목번호": "sku_id",
    "sku": "sku_id",
    "품명": "name",
    "상품명": "name",
    "품목명": "name",
    "카테고리": "category_label",
    "분류": "category_label",
    "현재고": "on_hand",
    "현재재고": "on_hand",
    "재고수량": "on_hand",
    "가용재고": "on_hand",
    "일평균출고": "avg_daily_demand",
    "일출고": "avg_daily_demand",
    "평균일출고": "avg_daily_demand",
    "출고계": "outbound_total",
    "판매출고": "outbound_total",
    "리드타임": "lead_time_days",
    "리드타임일": "lead_time_days",
    "리드타임(일)": "lead_time_days",
    "납기일수": "lead_time_days",
    "moq": "moq",
    "MOQ": "moq",
    "최소발주": "moq",
    "거래처": "vendor",
    "거래처명": "vendor",
    "매입처": "vendor",
    "안전재고일": "safety_stock_days",
    "안전재고(일)": "safety_stock_days",
    "안전일수": "safety_stock_days",
    "유통기한": "nearest_expiry",
    "소비기한": "nearest_expiry",
    "expiration_date": "nearest_expiry",
    "nearest_expiry": "nearest_expiry",
    "임박재고": "expiring_qty",
    "expiring_qty": "expiring_qty",
}

ERP_KOREAN_SALES_MAP: dict[str, str] = {
    "품목코드": "sku_id",
    "상품코드": "sku_id",
    "품목번호": "sku_id",
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

WMS_EXPIRY_MAP: dict[str, str] = {
    "품목코드": "sku_id",
    "품목번호": "sku_id",
    "상품코드": "sku_id",
    "sku": "sku_id",
    "sku_id": "sku_id",
    "유통기한": "expiry_date",
    "소비기한": "expiry_date",
    "유효기간": "expiry_date",
    "expiration_date": "expiry_date",
    "expiry_date": "expiry_date",
    "수량": "qty",
    "재고수량": "qty",
    "재고": "qty",
    "qty": "qty",
    "lot수량": "qty",
    "LOT수량": "qty",
    "현재고": "qty",
}

CATEGORY_LABEL_TO_CODE: dict[str, str] = {
    "내시경": "endoscopy",
    "의료기기 소mo품": "medical_consumable",
    "의료기기 소모품": "medical_consumable",
    "의료소mo품": "medical_consumable",
    "소mo품": "general",
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

_CATEGORY_SOURCE_KEYS = ("품목분류2", "품목분류1", "카테고리", "분류")

PRESET_LABELS = {
    "instock_native": "기본 형식 (영문 컬럼)",
    "erp_korean": "ERP 한글 형식 (품목코드·현재고·일평균출고)",
    "younglimwon": "영림원 재고현황 (품목번호·재고수량·출고계)",
}

MERGE_MODE_LABELS = {
    "replace": "전체 교체 (기존 데이터 삭제)",
    "merge": "병합 (같은 품목코드는 파일 값으로 갱신)",
    "append": "신규만 추가 (기존 품목은 유지)",
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
    has_sku = bool(cols & {"품목코드", "상품코드", "품목번호"})
    has_week = bool(cols & {"주간시작일", "주차", "출고일", "일자", "week_start"})
    has_qty = bool(cols & {"출고수량", "수량", "qty"})
    return has_sku and has_week and has_qty


def _normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def _normalize_column_key(name: str) -> str:
    return str(name).strip().replace(" ", "").replace("_", "").lower()


def _column_lookup(frame: pd.DataFrame) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for col in frame.columns:
        lookup[_normalize_column_key(col)] = col
    return lookup


def _find_source_column(frame: pd.DataFrame, *candidates: str) -> str | None:
    lookup = _column_lookup(frame)
    for cand in candidates:
        key = _normalize_column_key(cand)
        if key in lookup:
            return lookup[key]
    for cand in candidates:
        key = _normalize_column_key(cand)
        for norm, col in lookup.items():
            if norm == key or norm.endswith(key) or key in norm:
                return col
    return None


def _series_from_column(frame: pd.DataFrame, column: str) -> pd.Series:
    def _clean(value: object) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        text = str(value).strip()
        if text.lower() in {"", "none", "nan", "-"}:
            return ""
        return text

    return frame[column].map(_clean)


def _inject_category_column(frame: pd.DataFrame) -> pd.DataFrame:
    """Coalesce ERP category columns; 품목분류2 takes priority over 품목분류1."""
    out = _normalize_columns(frame)
    source_columns: list[str] = []
    for key in _CATEGORY_SOURCE_KEYS:
        col = _find_source_column(out, key)
        if col is not None and col not in source_columns:
            source_columns.append(col)

    if not source_columns:
        return out

    coalesced = pd.Series([""] * len(out), index=out.index, dtype=object)
    for key in _CATEGORY_SOURCE_KEYS:
        col = _find_source_column(out, key)
        if col is None:
            continue
        values = _series_from_column(out, col)
        coalesced = coalesced.where(coalesced != "", values)

    out = out.copy()
    out["카테고리"] = coalesced
    for col in source_columns:
        if col != "카테고리":
            out = out.drop(columns=[col])
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
        return code, text
    lowered = text.lower()
    for key, cat_code in CATEGORY_LABEL_TO_CODE.items():
        if key.lower() == lowered:
            return cat_code, text
    if text in CATEGORIES:
        return text, CATEGORIES[text]

    compact = text.replace(" ", "")
    if "내시경" in compact:
        return "endoscopy", text
    if "한약" in compact:
        return "herbal", text
    upper = compact.upper()
    if upper == "PB" or upper.startswith("PB"):
        return "pb", text
    if "의료기기" in compact and "소모" in compact:
        return "medical_consumable", text
    if "의료" in compact and "소모" in compact:
        return "medical_consumable", text
    if "소모" in compact:
        return "general", text
    if "의료기기" in compact or "장비" in compact:
        return "medical_equipment", text

    return "general", text


def is_younglimwon_inventory_frame(frame: pd.DataFrame) -> bool:
    cols = {str(column).strip() for column in frame.columns}
    return bool({"품목번호", "재고수량"} <= cols)


def is_inventory_export_frame(frame: pd.DataFrame) -> bool:
    cols = {str(column).strip() for column in frame.columns}
    has_sku = bool(cols & {"품목코드", "품목번호", "상품코드"})
    has_stock = bool(cols & {"현재고", "현재재고", "재고수량"})
    has_name = bool(cols & {"품명", "품목명", "상품명"})
    return has_sku and has_stock and has_name and not is_korean_sales_frame(frame)


def is_wms_expiry_frame(frame: pd.DataFrame) -> bool:
    cols = {str(column).strip() for column in frame.columns}
    has_sku = bool(cols & {"품목코드", "품목번호", "상품코드", "sku_id", "sku"})
    has_expiry = bool(cols & {"유통기한", "소비기한", "유효기간", "expiration_date", "expiry_date"})
    has_qty = bool(cols & {"수량", "재고수량", "재고", "qty", "LOT수량", "lot수량"})
    return has_sku and has_expiry and has_qty


def read_uploaded_csv(upload) -> pd.DataFrame:
    """Read CSV upload with common Korean ERP encodings."""
    raw = upload.getvalue()
    upload.seek(0)
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=encoding)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(io.BytesIO(raw), encoding="utf-8", errors="replace")


def _flatten_excel_columns(columns: object) -> list[str]:
    """Flatten MultiIndex / tuple headers from 영림원 2-row exports."""
    names: list[str] = []
    for col in columns:
        if isinstance(col, tuple):
            parts: list[str] = []
            for part in col:
                text = str(part).strip()
                if not text or text.lower().startswith("unnamed"):
                    continue
                parts.append(text)
            if parts:
                names.append(parts[-1])
            else:
                names.append(str(col[-1]).strip())
        else:
            names.append(str(col).strip())
    return names


def _detect_single_header_row(preview: pd.DataFrame) -> int:
    keywords = {"품목번호", "품목코드", "품목분류2", "재고수량", "출고계", "품명", "품목명"}
    best_row = 1
    best_score = -1
    for i in range(min(12, len(preview))):
        row_vals = {
            str(value).strip()
            for value in preview.iloc[i].values
            if pd.notna(value) and str(value).strip()
        }
        score = len(row_vals & keywords)
        if score > best_score:
            best_score = score
            best_row = i
    return best_row if best_score > 0 else 1


def _detect_multirow_excel_header(preview: pd.DataFrame) -> list[int] | None:
    """Detect 영림원-style grouped headers (구분 → 품목분류2)."""
    for i in range(min(14, len(preview) - 1)):
        next_vals = {
            str(value).strip()
            for value in preview.iloc[i + 1].values
            if pd.notna(value) and str(value).strip()
        }
        if "품목분류2" in next_vals or "품목분류1" in next_vals:
            return [i, i + 1]
    return None


def _rename_duplicate_gubun_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """영림원 export sometimes repeats '구분' for 분류1/분류2 in one header row."""
    if _find_source_column(frame, "품목분류2") is not None:
        return frame
    cols = [str(c).strip() for c in frame.columns]
    gubun_indices = [index for index, name in enumerate(cols) if name == "구분"]
    if len(gubun_indices) >= 2:
        cols[gubun_indices[0]] = "품목분류1"
        cols[gubun_indices[1]] = "품목분류2"
        out = frame.copy()
        out.columns = cols
        return out
    return frame


def read_uploaded_excel(upload) -> pd.DataFrame:
    """Read Excel with auto-detected header rows (영림원 2-row headers supported)."""
    name = str(getattr(upload, "name", "") or "").lower()
    engine = "xlrd" if name.endswith(".xls") else None
    raw = upload.getvalue()
    upload.seek(0)
    buffer = io.BytesIO(raw)
    preview = pd.read_excel(buffer, header=None, nrows=20, engine=engine)
    buffer.seek(0)

    header_rows = _detect_multirow_excel_header(preview)
    if header_rows:
        df = pd.read_excel(io.BytesIO(raw), header=header_rows, engine=engine)
        df.columns = _flatten_excel_columns(df.columns)
    else:
        header_row = _detect_single_header_row(preview)
        df = pd.read_excel(io.BytesIO(raw), header=header_row, engine=engine)

    upload.seek(0)
    df = _rename_duplicate_gubun_columns(_normalize_columns(df))
    upload.seek(0)
    return df


def read_uploaded_table(upload) -> pd.DataFrame:
    """Read CSV or Excel upload into a DataFrame."""
    name = str(getattr(upload, "name", "") or "").lower()
    if name.endswith((".xlsx", ".xls")):
        return read_uploaded_excel(upload)
    return read_uploaded_csv(upload)


def parse_inventory_upload(
    upload,
    *,
    preset: str = "erp_korean",
    min_outbound: float = 10.0,
    period_days: float = 30.0,
) -> tuple[list[SkuMaster], ImportReport]:
    """Parse a CSV/Excel inventory upload into SKU masters."""
    raw = read_uploaded_table(upload)
    if preset == "younglimwon" or is_younglimwon_inventory_frame(raw):
        return parse_younglimwon_inventory(
            raw,
            min_outbound=min_outbound,
            period_days=period_days,
        )
    return parse_sku_csv(raw, preset=preset)


def merge_sku_masters(
    existing: list[SkuMaster],
    imported: list[SkuMaster],
    *,
    mode: str = "merge",
) -> tuple[list[SkuMaster], dict[str, int]]:
    """Combine imported SKUs with the current master list."""
    if mode == "replace":
        merged = copy.deepcopy(imported)
        return merged, {
            "added": len(imported),
            "updated": 0,
            "skipped": 0,
            "total": len(merged),
        }

    by_id = {sku.sku_id: copy.deepcopy(sku) for sku in existing}
    order = [sku.sku_id for sku in existing]
    added = updated = skipped = 0

    for sku in imported:
        if sku.sku_id in by_id:
            if mode == "merge":
                by_id[sku.sku_id] = sku
                updated += 1
            else:
                skipped += 1
        else:
            by_id[sku.sku_id] = sku
            order.append(sku.sku_id)
            added += 1

    merged = [by_id[sku_id] for sku_id in order]
    return merged, {
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "total": len(merged),
    }


def sales_from_sku_masters(
    skus: list[SkuMaster],
    *,
    week_label: str | None = None,
    period_days: float = 30.0,
    period_end_date: str | None = None,
    period_start_date: str | None = None,
) -> list[WeeklySales]:
    """Build weekly-equivalent sales rows from master avg_daily_demand."""
    label = week_label
    if label is None:
        if period_end_date or period_start_date:
            label = format_younglimwon_period_label(
                period_days,
                period_end_date,
                period_start_date,
            )
        else:
            label = "마스터(일평균환산)"
    sales: list[WeeklySales] = []
    for sku in skus:
        if sku.avg_daily_demand <= 0:
            continue
        sales.append(
            WeeklySales(
                sku_id=sku.sku_id,
                week_start=label,
                qty=round(sku.avg_daily_demand * 7.0, 2),
            )
        )
    return sales


def sync_sales_from_inventory(
    raw: pd.DataFrame,
    skus: list[SkuMaster],
    *,
    preset: str = "erp_korean",
    min_outbound: float = 0.0,
    period_days: float = 30.0,
    period_end_date: str | None = None,
    period_start_date: str | None = None,
) -> list[WeeklySales]:
    """Derive forecast sales from upload file, falling back to master daily demand."""
    sales, report = parse_sales_upload(
        raw,
        preset=preset,
        min_outbound=min_outbound,
        period_days=period_days,
        period_end_date=period_end_date,
        period_start_date=period_start_date,
    )
    if report.ok and sales:
        return sales
    return sales_from_sku_masters(
        skus,
        period_days=period_days,
        period_end_date=period_end_date,
        period_start_date=period_start_date,
    )


def prepare_younglimwon_inventory(
    frame: pd.DataFrame,
    *,
    min_outbound: float = 0.0,
    period_days: float = 30.0,
) -> pd.DataFrame:
    """Map 영림원 재고현황 export → Instock ERP CSV shape."""
    df = _normalize_columns(frame)
    if "품목번호" not in df.columns:
        raise ValueError("영림원 형식이 아닙니다 — '품목번호' 컬럼이 필요합니다.")

    work = df[df["품목번호"].notna()].copy()
    work["품목번호"] = work["품목번호"].astype(str).str.strip()
    work = work[~work["품목번호"].str.upper().eq("TOTAL")]

    work["출고계"] = pd.to_numeric(work.get("출고계"), errors="coerce").fillna(0.0)
    if min_outbound > 0:
        work = work[work["출고계"] >= min_outbound].copy()

    work["재고수량"] = pd.to_numeric(work.get("재고수량"), errors="coerce").fillna(0.0)
    period = max(1.0, float(period_days))
    avg_daily = (work["출고계"] / period).round(2)

    work = _inject_category_column(work)
    category = work.get("카테고리", pd.Series(["일반 소모품"] * len(work), index=work.index))
    category = category.fillna("").astype(str)
    category = category.where(category != "", "일반 소모품")

    name_col = "품목명" if "품목명" in work.columns else "품명"
    if name_col not in work.columns:
        work[name_col] = work["품목번호"]
    names = work[name_col].fillna(work["품목번호"]).astype(str)

    return pd.DataFrame(
        {
            "품목코드": work["품목번호"].values,
            "품명": names.values,
            "카테고리": category.values,
            "현재고": work["재고수량"].values,
            "일평균출고": avg_daily.values,
        }
    )


def build_younglimwon_outbound_preview(
    frame: pd.DataFrame,
    *,
    min_outbound: float = 0.0,
    period_days: float = 30.0,
    limit: int = 10,
) -> pd.DataFrame:
    """Top SKUs showing 출고계 ÷ period → 일평균출고 calculation."""
    df = _normalize_columns(frame)
    if "품목번호" not in df.columns:
        return pd.DataFrame()
    outbound_col = None
    for candidate in ("출고계", "판매출고", "출고"):
        if candidate in df.columns:
            outbound_col = candidate
            break
    if outbound_col is None:
        return pd.DataFrame()

    work = df[df["품목번호"].notna()].copy()
    work["품목번호"] = work["품목번호"].astype(str).str.strip()
    work = work[~work["품목번호"].str.upper().eq("TOTAL")]
    work[outbound_col] = pd.to_numeric(work[outbound_col], errors="coerce").fillna(0.0)
    if min_outbound > 0:
        work = work[work[outbound_col] >= min_outbound].copy()
    if work.empty:
        return pd.DataFrame()

    period = max(1.0, float(period_days))
    name_col = "품목명" if "품목명" in work.columns else "품명"
    if name_col not in work.columns:
        work[name_col] = work["품목번호"]

    preview = work.nlargest(min(limit, len(work)), outbound_col).copy()
    return pd.DataFrame(
        {
            "품목코드": preview["품목번호"].astype(str).values,
            "품명": preview[name_col].fillna(preview["품목번호"]).astype(str).values,
            "출고계": preview[outbound_col].values,
            "기간(일)": int(period),
            "일평균출고": (preview[outbound_col] / period).round(2).values,
        }
    )


def build_outbound_preview_from_skus(
    skus: list[SkuMaster],
    *,
    period_days: float = 30.0,
    limit: int = 10,
) -> pd.DataFrame:
    """Reverse-engineer preview from saved 일평균출고 for verification."""
    period = max(1.0, float(period_days))
    ranked = sorted(
        [s for s in skus if s.avg_daily_demand > 0],
        key=lambda sku: sku.avg_daily_demand,
        reverse=True,
    )[:limit]
    if not ranked:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "품목코드": sku.sku_id,
                "품명": sku.name,
                "출고계(역산)": round(sku.avg_daily_demand * period, 1),
                "기간(일)": int(period),
                "일평균출고": sku.avg_daily_demand,
            }
            for sku in ranked
        ]
    )


def parse_younglimwon_inventory(
    frame: pd.DataFrame,
    *,
    min_outbound: float = 0.0,
    period_days: float = 30.0,
) -> tuple[list[SkuMaster], ImportReport]:
    prepared = prepare_younglimwon_inventory(
        frame,
        min_outbound=min_outbound,
        period_days=period_days,
    )
    skus, report = parse_sku_csv(prepared, preset="erp_korean")
    if report.ok:
        note = f"영림원 재고현황 {len(skus)}건"
        if min_outbound > 0:
            note += f" (출고계 {min_outbound:g}+)"
        report.messages.insert(0, note)
    return skus, report


def parse_sku_csv(
    frame: pd.DataFrame,
    *,
    preset: str = "erp_korean",
) -> tuple[list[SkuMaster], ImportReport]:
    frame = _normalize_columns(frame)
    frame = _rename_duplicate_gubun_columns(frame)
    if preset != "instock_native":
        frame = _inject_category_column(frame)
    if preset == "instock_native":
        mapped = frame.copy()
        mapped.columns = [c.lower() for c in mapped.columns]
    else:
        mapped = _rename_with_map(frame, ERP_KOREAN_SKU_MAP)
        mapped.columns = [str(c).lower() for c in mapped.columns]

    required = {"sku_id", "name", "on_hand"}
    missing = required - set(mapped.columns)
    report = ImportReport(ok=not missing, row_count=len(mapped), messages=[], warnings=[])
    if missing:
        report.messages.append(f"필수 컬럼 누락: {', '.join(sorted(missing))}")
        return [], report
    if "avg_daily_demand" not in mapped.columns:
        report.warnings.append(
            "일평균출고 컬럼 없음 — 0으로 처리합니다. 출고 CSV 업로드 또는 ③ 데이터 연동 → 마스터 편집으로 보완하세요."
        )

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
        avg_daily = coerce_float(row.get("avg_daily_demand"), default=0.0)
        lead_time_raw = coerce_float(row.get("lead_time_days", 7), default=7.0)
        moq_raw = coerce_float(row.get("moq", 1), default=1.0)
        safety_raw = coerce_float(row.get("safety_stock_days", 7), default=7.0)
        if on_hand is None:
            report.warnings.append(f"{sku_id}: 현재고 변환 실패 — 행 제외")
            continue
        lead_time = int(lead_time_raw)
        moq = int(moq_raw)
        safety = float(safety_raw)
        vendor = str(row.get("vendor", "-")).strip() or "-"

        if avg_daily <= 0:
            report.warnings.append(f"{sku_id}: 일평균출고 0 — 결품 계산 제외 권장")

        nearest_expiry = None
        expiring_qty = None
        if "nearest_expiry" in mapped.columns and pd.notna(row.get("nearest_expiry")):
            raw_expiry = str(row.get("nearest_expiry", "")).strip()
            if raw_expiry:
                if parse_expiry_date and parse_expiry_date(raw_expiry) is None:
                    report.warnings.append(f"{sku_id}: 유통기한 형식 오류 — '{raw_expiry}'")
                else:
                    parsed = parse_expiry_date(raw_expiry) if parse_expiry_date else None
                    nearest_expiry = parsed.isoformat() if parsed else raw_expiry[:10]
        if "expiring_qty" in mapped.columns and pd.notna(row.get("expiring_qty")):
            qty_raw = coerce_float(row.get("expiring_qty"), default=None)
            if qty_raw is not None:
                expiring_qty = qty_raw

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
                nearest_expiry=nearest_expiry,
                expiring_qty=expiring_qty,
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


def format_younglimwon_period_label(
    period_days: float,
    period_end_date: str | None = None,
    period_start_date: str | None = None,
) -> str:
    period = max(1, int(round(float(period_days))))
    start = str(period_start_date).strip()[:10] if period_start_date else ""
    end = str(period_end_date).strip()[:10] if period_end_date else ""
    if start and end:
        return f"{start}~{end} ({period}일)"
    if end:
        return f"{end} ({period}일 합계)"
    return f"기간합계({period}일)"


def parse_younglimwon_aggregated_sales(
    frame: pd.DataFrame,
    *,
    min_outbound: float = 0.0,
    period_days: float = 30.0,
    period_end_date: str | None = None,
    period_start_date: str | None = None,
) -> tuple[list[WeeklySales], ImportReport]:
    """Convert 영림원 재고현황(출고계) into weekly-equivalent shipment rows."""
    df = _normalize_columns(frame)
    report = ImportReport(ok=False, row_count=0, messages=[], warnings=[])
    if "품목번호" not in df.columns:
        report.messages.append("영림원 출고(집계) 형식이 아닙니다 — '품목번호' 컬럼이 필요합니다.")
        return [], report

    outbound_col = None
    for candidate in ("출고계", "판매출고", "출고"):
        if candidate in df.columns:
            outbound_col = candidate
            break
    if not outbound_col:
        report.messages.append("출고계(또는 판매출고) 컬럼이 필요합니다.")
        return [], report

    work = df[df["품목번호"].notna()].copy()
    work["품목번호"] = work["품목번호"].astype(str).str.strip()
    work = work[~work["품목번호"].str.upper().eq("TOTAL")]
    work[outbound_col] = pd.to_numeric(work[outbound_col], errors="coerce").fillna(0.0)
    if min_outbound > 0:
        work = work[work[outbound_col] >= min_outbound].copy()

    period = max(1.0, float(period_days))
    week_start = format_younglimwon_period_label(
        period,
        period_end_date,
        period_start_date,
    )
    sales: list[WeeklySales] = []
    for _, row in work.iterrows():
        sku_id = str(row["품목번호"]).strip()
        if not sku_id:
            continue
        total = float(row[outbound_col])
        weekly_qty = round(total * 7.0 / period, 2)
        sales.append(WeeklySales(sku_id=sku_id, week_start=week_start, qty=weekly_qty))

    report.ok = len(sales) > 0
    report.row_count = len(sales)
    if sales:
        note = f"영림원 출고(기간 합계) {len(sales)}건 → 주간 환산"
        if min_outbound > 0:
            note += f" (출고계 {min_outbound:g}+)"
        report.messages.append(note)
        report.warnings.append(
            "주간별 추이가 없어 기간 합계를 한 주치로 환산했습니다. "
            f"기준: {week_start}. "
            "결품·발주는 재고 가져오기의 일평균출고를 우선 사용하세요."
        )
    else:
        report.messages.append("읽을 수 있는 출고 행이 없습니다.")
    return sales, report


def parse_sales_upload(
    frame: pd.DataFrame,
    *,
    preset: str = "erp_korean",
    min_outbound: float = 0.0,
    period_days: float = 30.0,
    period_end_date: str | None = None,
    period_start_date: str | None = None,
) -> tuple[list[WeeklySales], ImportReport]:
    """Parse weekly shipment CSV or 영림원 aggregated outbound exports."""
    frame = _normalize_columns(frame)

    if is_korean_sales_frame(frame):
        return parse_sales_csv(frame, preset="erp_korean")

    cols = {str(column).strip() for column in frame.columns}
    if is_younglimwon_inventory_frame(frame) or {"품목번호", "출고계"} <= cols:
        return parse_younglimwon_aggregated_sales(
            frame,
            min_outbound=min_outbound,
            period_days=period_days,
            period_end_date=period_end_date,
            period_start_date=period_start_date,
        )

    if is_inventory_export_frame(frame):
        report = ImportReport(
            ok=False,
            row_count=len(frame),
            messages=[
                "이 파일은 재고·품목 형식입니다. 왼쪽 「재고 CSV / Excel」에 올려 주세요. "
                "영림원 재고현황(2.xlsx)은 출고계로 일평균출고가 자동 계산됩니다. "
                "출고 CSV는 주간 이력(품목코드·주간시작일·출고수량)용입니다."
            ],
            warnings=[],
        )
        return [], report

    if preset == "instock_native":
        return parse_native_sales_frame(frame)
    return parse_sales_csv(frame, preset=preset)


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


def parse_wms_expiry_lots(frame: pd.DataFrame) -> tuple[list[ExpiryLot], ImportReport]:
    """Parse outsourced WMS export: SKU + expiry date + qty per row."""
    frame = _normalize_columns(frame)
    mapped = _rename_with_map(frame, WMS_EXPIRY_MAP)
    mapped.columns = [str(c).lower() for c in mapped.columns]

    required = {"sku_id", "expiry_date", "qty"}
    missing = required - set(mapped.columns)
    report = ImportReport(ok=not missing, row_count=len(mapped), messages=[], warnings=[])
    if missing:
        report.messages.append(f"필수 컬럼 누락: {', '.join(sorted(missing))}")
        report.messages.append("필요: 품목코드(또는 품목번호), 유통기한, 수량")
        return [], report

    lots: list[ExpiryLot] = []
    for index, row in mapped.iterrows():
        sku_id = str(row.get("sku_id", "")).strip()
        if not sku_id:
            continue
        raw_expiry = str(row.get("expiry_date", "")).strip()
        if not raw_expiry or raw_expiry.lower() in {"none", "nan", "-", "n/a"}:
            report.warnings.append(f"행 {index + 2} ({sku_id}): 유통기한 없음 — 건너뜀")
            continue
        if parse_expiry_date is None or parse_expiry_date(raw_expiry) is None:
            report.warnings.append(
                f"행 {index + 2} ({sku_id}): 유통기한 형식 오류 — '{raw_expiry}'"
            )
            continue
        expiry_iso = parse_expiry_date(raw_expiry).isoformat()
        qty = coerce_float(row.get("qty"), default=None)
        if qty is None or qty < 0:
            report.warnings.append(
                f"행 {index + 2} ({sku_id}): 수량 형식 오류 — '{row.get('qty')}'"
            )
            continue
        lots.append(ExpiryLot(sku_id=sku_id, expiry_date=expiry_iso, qty=qty))

    report.ok = len(lots) > 0
    report.row_count = len(lots)
    if lots:
        sku_count = len({lot.sku_id for lot in lots})
        report.messages.append(f"WMS 유통기한 {len(lots)}건 ({sku_count} SKU) 로드")
    else:
        report.messages.append("읽을 수 있는 유통기한 행이 없습니다.")
    return lots, report


def apply_expiry_lots_to_skus(
    skus: list[SkuMaster],
    lots: list[ExpiryLot],
) -> tuple[list[SkuMaster], ImportReport]:
    """Match WMS expiry rows to loaded SKUs and attach lot-level quantities."""
    from dataclasses import replace

    by_sku: dict[str, list[ExpiryLot]] = {}
    for lot in lots:
        by_sku.setdefault(lot.sku_id, []).append(lot)

    for sku_id in by_sku:
        by_sku[sku_id].sort(key=lambda item: item.expiry_date)

    known_ids = {sku.sku_id for sku in skus}
    unmatched = sorted(set(by_sku) - known_ids)

    updated: list[SkuMaster] = []
    matched_skus = 0
    for sku in skus:
        sku_lots = by_sku.get(sku.sku_id)
        if not sku_lots:
            updated.append(replace(sku, expiry_lots=[], nearest_expiry=None, expiring_qty=None))
            continue
        nearest = sku_lots[0]
        updated.append(
            replace(
                sku,
                expiry_lots=list(sku_lots),
                nearest_expiry=nearest.expiry_date,
                expiring_qty=nearest.qty,
            )
        )
        matched_skus += 1

    report = ImportReport(
        ok=matched_skus > 0,
        row_count=len(lots),
        messages=[f"유통기한 매칭 {matched_skus} SKU / {len(lots)} LOT 행 적용"],
        warnings=[],
    )
    if unmatched:
        preview = ", ".join(unmatched[:8])
        if len(unmatched) > 8:
            preview += " …"
        report.warnings.append(
            f"재고 마스터에 없는 SKU {len(unmatched)}건 — {preview}"
        )
    if matched_skus == 0:
        report.ok = False
        report.messages.append("매칭된 SKU가 없습니다. 품목코드가 재고 import와 같은지 확인하세요.")
    return updated, report


def build_sample_wms_expiry_csv_bytes() -> bytes:
    frame = pd.DataFrame(
        [
            {"품목코드": "MC-001", "유통기한": "2026-10-15", "수량": 120},
            {"품목코드": "MC-001", "유통기한": "2026-12-01", "수량": 80},
            {"품목코드": "MC-013", "유통기한": "2026-09-20", "수량": 42},
        ]
    )
    return frame.to_csv(index=False).encode("utf-8-sig")


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
                "유통기한": sku.nearest_expiry or "",
                "임박재고": sku.expiring_qty if sku.expiring_qty is not None else "",
            }
        )
    return pd.DataFrame(rows)


def build_sample_erp_sku_csv_bytes() -> bytes:
    frame = skus_to_erp_export_frame(list(DEFAULT_SKUS)[:15])
    return frame.to_csv(index=False).encode("utf-8-sig")


def build_minimal_erp_sku_csv_bytes() -> bytes:
    """Empty-ish template: only required columns + one example row."""
    frame = pd.DataFrame(
        [
            {
                "품목코드": "품목코드-예시",
                "품명": "품명을 입력",
                "현재고": 0,
                "일평균출고": 0,
            }
        ]
    )
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
