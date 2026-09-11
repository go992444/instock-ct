"""
Instock CT — 의료 B2B 이커머스 발주·재고 관리 시범 (Portfolio)

실행:
  cd instock_ct
  pip install -r requirements.txt
  streamlit run app.py
"""

from __future__ import annotations

APP_BUILD = "9ff0cab2"

import copy
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

_APP_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _APP_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from instock_ct.config import (  # noqa: E402
    CATEGORIES,
    DEFAULT_SKUS,
    DEFAULT_TARGET_COVERAGE_DAYS,
    EXPIRY_CRITICAL_DAYS,
    EXPIRY_WARNING_DAYS,
    DEFAULT_EXPIRY_THRESHOLDS_BY_CATEGORY,
    DEFAULT_TURNOVER_THRESHOLDS_BY_CATEGORY,
    LOW_TURNOVER_THRESHOLD,
)
from instock_ct.inventory_engine import (  # noqa: E402
    assess_stockout_risk,
    build_reorder_plan,
    forecast_from_weekly_sales,
    recommended_reorder_qty,
    risk_label,
    simulate_promo_impact,
    summarize_risk_counts,
    filter_slow_movers,
    get_turnover_threshold,
)
from instock_ct.models import SkuMaster, WeeklySales  # noqa: E402
from instock_ct.erp_import import (  # noqa: E402
    MERGE_MODE_LABELS,
    PRESET_LABELS,
    apply_expiry_lots_to_skus,
    build_reorder_export_frame,
    build_sample_erp_sku_csv_bytes,
    build_minimal_erp_sku_csv_bytes,
    build_outbound_preview_from_skus,
    build_sample_wms_expiry_csv_bytes,
    build_younglimwon_outbound_preview,
    coerce_float,
    avg_daily_from_outbound,
    extract_younglimwon_outbound_totals,
    format_younglimwon_period_label,
    younglimwon_outbound_and_stock_maps,
    is_korean_sales_frame,
    merge_sku_masters,
    parse_inventory_upload,
    parse_native_sales_frame,
    parse_sales_csv,
    parse_sales_upload,
    parse_sku_csv,
    parse_wms_expiry_lots,
    parse_younglimwon_inventory,
    read_uploaded_table,
    sales_from_sku_masters,
    sync_sales_from_inventory,
    is_younglimwon_inventory_frame,
    skus_to_erp_export_frame,
)
from instock_ct.erp_import import _resolve_category  # noqa: E402
from instock_ct.sample_sales import build_sample_weekly_sales, weekly_sales_to_dataframe_rows  # noqa: E402
from instock_ct.session_persist import (  # noqa: E402
    clear_session_data,
    ensure_session_restored,
    is_demo_skus,
    mark_persist_dirty,
    persist_result_message,
    persist_session_data,
    persist_status_label,
    render_persist_flash,
    session_persist_available,
    set_persist_flash,
)
from instock_ct.expiry_engine import (  # noqa: E402
    build_expiry_lot_alerts,
    expiry_label,
    parse_expiry_date,
    summarize_expiry_counts,
)
from instock_ct.models import ExpiryAlert  # noqa: E402

_SAMPLES_DIR = _APP_DIR / "samples"

st.set_page_config(page_title="Instock CT", page_icon="📊", layout="wide")


def _inject_notranslate() -> None:
    """Discourage browser auto-translate (keeps ERP product names intact)."""
    st.markdown(
        """
        <style>
        html, body, [data-testid="stAppViewContainer"], [data-testid="stDataFrame"],
        [data-testid="stSelectbox"], [data-testid="stMetric"], .notranslate {
            translate: no !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    components.html(
        """
        <script>
        (function () {
            document.documentElement.setAttribute("translate", "no");
            document.documentElement.classList.add("notranslate");
            if (!document.querySelector('meta[name="google"][content="notranslate"]')) {
                const meta = document.createElement("meta");
                meta.name = "google";
                meta.content = "notranslate";
                document.head.appendChild(meta);
            }
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def _render_product_name(name: str) -> None:
    safe = (
        name.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    st.markdown(
        f'<p class="notranslate" translate="no"><strong>품명</strong> {safe}</p>',
        unsafe_allow_html=True,
    )


def _date_to_iso(value: object | None) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text[:10] if text else None


def _younglimwon_period_start_iso() -> str | None:
    return _date_to_iso(st.session_state.get("ylw_period_start_date"))


def _younglimwon_period_end_iso() -> str | None:
    return _date_to_iso(st.session_state.get("ylw_period_end_date"))


def _younglimwon_period_days() -> float:
    start = st.session_state.get("ylw_period_start_date")
    end = st.session_state.get("ylw_period_end_date")
    if start is not None and end is not None:
        try:
            return float(max(1, (end - start).days + 1))
        except TypeError:
            pass
    return float(st.session_state.get("ylw_period_days", 30.0))


def _younglimwon_period_label() -> str:
    return format_younglimwon_period_label(
        _younglimwon_period_days(),
        _younglimwon_period_end_iso(),
        _younglimwon_period_start_iso(),
    )


def _apply_period_preset(days: int, *, prefix: str) -> None:
    end = date.today()
    start = end - timedelta(days=max(1, days) - 1)
    if prefix == "ylw":
        st.session_state.ylw_period_start_date = start
        st.session_state.ylw_period_end_date = end
    else:
        st.session_state.forecast_ship_start_date = start
        st.session_state.forecast_ship_end_date = end


def _render_period_preset_buttons(*, prefix: str) -> None:
    st.caption("**기간 프리셋** — export 구간에 맞게 원클릭 설정")
    c1, c2, c3 = st.columns(3)
    if c1.button("최근 30일", use_container_width=True, key=f"{prefix}_preset_30"):
        _apply_period_preset(30, prefix=prefix)
        st.rerun()
    if c2.button("최근 90일", use_container_width=True, key=f"{prefix}_preset_90"):
        _apply_period_preset(90, prefix=prefix)
        st.rerun()
    if c3.button("최근 365일", use_container_width=True, key=f"{prefix}_preset_365"):
        _apply_period_preset(365, prefix=prefix)
        st.rerun()


def _store_younglimwon_source_frame(raw: pd.DataFrame) -> None:
    if is_younglimwon_inventory_frame(raw):
        st.session_state.last_younglimwon_frame = raw.copy()
        totals = extract_younglimwon_outbound_totals(raw)
        st.session_state.ylw_outbound_totals = totals or None
        st.session_state.ylw_recalc_sig = _younglimwon_recalc_signature()


def _younglimwon_source_frame() -> pd.DataFrame | None:
    frame = st.session_state.get("last_younglimwon_frame")
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        return frame
    return None


def _younglimwon_outbound_totals() -> dict[str, float]:
    totals = st.session_state.get("ylw_outbound_totals")
    if isinstance(totals, dict):
        return {str(k): float(v) for k, v in totals.items()}
    return {}


def _younglimwon_recalc_signature() -> tuple[float, str | None, str | None]:
    return (
        round(float(st.session_state.get("ylw_min_outbound", 10.0)), 4),
        _younglimwon_period_start_iso(),
        _younglimwon_period_end_iso(),
    )


def _has_younglimwon_outbound_source() -> bool:
    return _younglimwon_source_frame() is not None or bool(_younglimwon_outbound_totals())


def _reapply_younglimwon_demand(
    skus: list[SkuMaster],
    *,
    min_outbound: float,
    period_days: float,
) -> list[SkuMaster]:
    raw = _younglimwon_source_frame()
    if raw is not None:
        outbound_map, stock_map = younglimwon_outbound_and_stock_maps(raw)
        if not outbound_map:
            return skus
        updated: list[SkuMaster] = []
        for sku in skus:
            if sku.sku_id not in outbound_map:
                updated.append(copy.deepcopy(sku))
                continue
            merged = copy.deepcopy(sku)
            outbound = outbound_map[sku.sku_id]
            merged.avg_daily_demand = avg_daily_from_outbound(
                outbound,
                period_days=period_days,
                min_outbound=min_outbound,
            )
            if sku.sku_id in stock_map:
                merged.on_hand = stock_map[sku.sku_id]
            updated.append(merged)
        return updated

    totals = _younglimwon_outbound_totals()
    if not totals:
        return skus

    updated: list[SkuMaster] = []
    for sku in skus:
        if sku.sku_id not in totals:
            updated.append(copy.deepcopy(sku))
            continue
        merged = copy.deepcopy(sku)
        merged.avg_daily_demand = avg_daily_from_outbound(
            totals[sku.sku_id],
            period_days=period_days,
            min_outbound=min_outbound,
        )
        updated.append(merged)
    return updated


def _sync_younglimwon_demand_if_needed() -> None:
    if not _has_younglimwon_outbound_source():
        return
    sig = _younglimwon_recalc_signature()
    if st.session_state.get("ylw_recalc_sig") == sig:
        return
    min_out, period = float(sig[0]), _younglimwon_period_days()
    updated = _reapply_younglimwon_demand(
        _sku_list(),
        min_outbound=min_out,
        period_days=period,
    )
    st.session_state.skus = updated
    st.session_state.ylw_recalc_sig = sig
    _refresh_sales_from_skus(updated)
    _save_session()
    st.rerun()


def _younglimwon_period_is_valid() -> bool:
    start = st.session_state.get("ylw_period_start_date")
    end = st.session_state.get("ylw_period_end_date")
    if start is None or end is None:
        return True
    try:
        return end >= start
    except TypeError:
        return True


def _render_inventory_file_period_registration() -> tuple[float, float, bool]:
    """Mandatory file metadata: which date range this export represents."""
    st.warning(
        "영림원 파일에는 **며칠~며칠** 정보가 없습니다. "
        "파일을 올리기 **전에** ERP export와 같은 기간을 아래에 **등록**해 주세요."
    )
    _render_period_preset_buttons(prefix="ylw")
    default_end = date.today()
    default_start = default_end - timedelta(days=29)
    c0, c1, c2 = st.columns(3)
    with c0:
        min_out = st.number_input(
            "출고계 최소 (이상만)",
            min_value=0.0,
            value=float(st.session_state.get("ylw_min_outbound", 10.0)),
            step=1.0,
            help="영림원 재고현황 업로드 시 적용",
            key="ylw_min_outbound",
        )
    with c1:
        st.date_input(
            "이 파일 · 시작일 (포함)",
            value=default_start,
            help="이 export의 출고계가 집계된 첫 날",
            key="ylw_period_start_date",
        )
    with c2:
        st.date_input(
            "이 파일 · 종료일 (포함)",
            value=default_end,
            help="이 export의 출고계가 집계된 마지막 날",
            key="ylw_period_end_date",
        )

    period_days = _younglimwon_period_days()
    st.session_state["ylw_period_days"] = int(period_days)
    period_ok = _younglimwon_period_is_valid()
    if period_ok:
        st.success(
            f"**등록된 파일 기간:** {_younglimwon_period_label()} · "
            f"일평균출고 = 출고계 ÷ {int(period_days)}"
        )
    else:
        st.error("종료일은 시작일과 같거나 이후여야 합니다. 기간을 등록한 뒤 파일을 업로드하세요.")
    return float(min_out), period_days, period_ok


def _render_younglimwon_outbound_body(
    skus: list[SkuMaster],
) -> tuple[float, float]:
    ylw_min_out, ylw_period = _render_younglimwon_date_range()
    source_frame = _younglimwon_source_frame()
    _render_outbound_calc_panel(
        period_days=ylw_period,
        period_label=_younglimwon_period_label(),
        raw_frame=source_frame,
        outbound_totals=_younglimwon_outbound_totals() or None,
        skus=skus if source_frame is None and not _younglimwon_outbound_totals() else None,
        min_outbound=float(ylw_min_out),
        expanded=False,
    )
    _sync_younglimwon_demand_if_needed()
    if _has_younglimwon_outbound_source():
        st.caption("집계 기간·출고계 최소값을 바꾸면 **일평균출고가 자동 반영**됩니다.")
    return float(ylw_min_out), float(ylw_period)


def _render_younglimwon_outbound_tools(
    skus: list[SkuMaster],
    *,
    compact: bool = False,
) -> tuple[float, float]:
    """출고계 period settings (compact = inline, no nested expanders)."""
    if compact:
        st.caption("출고계 기간 · 일평균출고 (영림원 export와 동일하게)")
        return _render_younglimwon_date_range()
    st.markdown("### 📅 출고계 기간 · 일평균출고")
    st.info(
        "영림원 **출고계** = ERP가 이미 합산한 **기간 출고 합계**입니다. "
        "파일에 날짜가 없으므로 아래 **집계 시작·종료일**로 export 구간을 맞춰 주세요. "
        "날짜별 필터가 아니라 **일평균출고 = 출고계 ÷ 기간(일)** 로만 계산합니다."
    )
    return _render_younglimwon_outbound_body(skus)


def _render_outbound_calc_panel(
    *,
    period_days: float,
    period_label: str,
    raw_frame: pd.DataFrame | None = None,
    outbound_totals: dict[str, float] | None = None,
    skus: list[SkuMaster] | None = None,
    min_outbound: float = 0.0,
    expanded: bool = True,
    wrap_expander: bool = True,
) -> None:
    def _body() -> None:
        st.caption(
            f"**{period_label}** · 계산식: **일평균출고 = 출고계 ÷ {int(period_days)}**"
        )
        preview = pd.DataFrame()
        if raw_frame is not None and is_younglimwon_inventory_frame(raw_frame):
            preview = build_younglimwon_outbound_preview(
                raw_frame,
                min_outbound=min_outbound,
                period_days=period_days,
            )
        elif outbound_totals:
            preview = _preview_from_outbound_totals(
                _sku_list(),
                outbound_totals,
                min_outbound=min_outbound,
                period_days=period_days,
            )
        elif skus:
            st.caption(
                "원본 **출고계**가 없어 저장된 일평균출고만 역산 표시합니다. "
                "정확한 재계산은 재고 파일을 다시 가져오세요."
            )
            preview = build_outbound_preview_from_skus(skus, period_days=period_days)
        if preview.empty:
            st.info("검증할 출고계·일평균출고 데이터가 없습니다.")
        else:
            st.dataframe(preview, use_container_width=True, hide_index=True)

    if wrap_expander:
        with st.expander("🔍 출고계 → 일평균출고 검증 (상위 10건)", expanded=expanded):
            _body()
    else:
        _body()


def _preview_from_outbound_totals(
    skus: list[SkuMaster],
    totals: dict[str, float],
    *,
    min_outbound: float,
    period_days: float,
    limit: int = 10,
) -> pd.DataFrame:
    names = {sku.sku_id: sku.name for sku in skus}
    period = max(1.0, float(period_days))
    rows = [
        {
            "품목코드": sku_id,
            "품명": names.get(sku_id, sku_id),
            "출고계": outbound,
            "기간(일)": int(period),
            "일평균출고": round(outbound / period, 2),
        }
        for sku_id, outbound in totals.items()
        if outbound >= min_outbound
    ]
    if not rows:
        return pd.DataFrame()
    rows.sort(key=lambda row: row["출고계"], reverse=True)
    return pd.DataFrame(rows[:limit])


def _render_younglimwon_date_range(
    *,
    show_min_outbound: bool = True,
    title: str | None = None,
) -> tuple[float, float]:
    """Shared 출고계 date range when export files have no date column."""
    if title:
        st.markdown(title)
    _render_period_preset_buttons(prefix="ylw")
    default_end = date.today()
    default_start = default_end - timedelta(days=29)

    if show_min_outbound:
        c0, c1, c2 = st.columns(3)
    else:
        c0 = None
        c1, c2 = st.columns(2)

    if c0 is not None:
        with c0:
            min_out = st.number_input(
                "출고계 최소 (이상만)",
                min_value=0.0,
                value=float(st.session_state.get("ylw_min_outbound", 10.0)),
                step=1.0,
                help="영림원 재고현황 업로드 시 적용",
                key="ylw_min_outbound",
            )
    else:
        min_out = float(st.session_state.get("ylw_min_outbound", 10.0))

    with c1:
        st.date_input(
            "집계 시작일",
            value=default_start,
            help="출고계 집계 구간 시작",
            key="ylw_period_start_date",
        )
    with c2:
        st.date_input(
            "집계 종료일",
            value=default_end,
            help="출고계 집계 구간 종료 (export 기준일)",
            key="ylw_period_end_date",
        )

    start = st.session_state.get("ylw_period_start_date")
    end = st.session_state.get("ylw_period_end_date")
    period_days = _younglimwon_period_days()
    st.session_state["ylw_period_days"] = int(period_days)
    if start and end and end < start:
        st.error("집계 종료일은 시작일과 같거나 이후여야 합니다.")
    st.caption(
        f"적용 기간 **{_younglimwon_period_label()}** · "
        f"일평균출고 = 출고계 ÷ {int(period_days)}"
    )
    return float(min_out), period_days


def _forecast_upload_period_start_iso() -> str | None:
    return _date_to_iso(st.session_state.get("forecast_ship_start_date"))


def _forecast_upload_period_end_iso() -> str | None:
    return _date_to_iso(st.session_state.get("forecast_ship_end_date"))


def _forecast_upload_period_days() -> float:
    start = st.session_state.get("forecast_ship_start_date")
    end = st.session_state.get("forecast_ship_end_date")
    if start is not None and end is not None:
        try:
            return float(max(1, (end - start).days + 1))
        except TypeError:
            pass
    return float(st.session_state.get("forecast_ship_period_days", 30.0))


def _forecast_upload_period_label() -> str:
    return format_younglimwon_period_label(
        _forecast_upload_period_days(),
        _forecast_upload_period_end_iso(),
        _forecast_upload_period_start_iso(),
    )


def _render_forecast_upload_period_inputs() -> tuple[float, float]:
    """Date range for the weekly shipment file being uploaded (not ERP master)."""
    default_end = date.today()
    default_start = default_end - timedelta(days=29)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.date_input(
            "이 파일 출고 시작일",
            value=default_start,
            help="업로드 파일에 날짜가 없을 때 — 출고 집계 시작",
            key="forecast_ship_start_date",
        )
    with c2:
        st.date_input(
            "이 파일 출고 종료일",
            value=default_end,
            help="업로드 파일에 날짜가 없을 때 — 출고 집계 종료",
            key="forecast_ship_end_date",
        )
    with c3:
        min_out = st.number_input(
            "출고계 최소 (영림원)",
            min_value=0.0,
            value=float(st.session_state.get("ylw_min_outbound", 10.0)),
            step=1.0,
            key="forecast_ship_min_outbound",
        )
    start = st.session_state.get("forecast_ship_start_date")
    end = st.session_state.get("forecast_ship_end_date")
    period_days = _forecast_upload_period_days()
    st.session_state["forecast_ship_period_days"] = int(period_days)
    if start and end and end < start:
        st.error("출고 종료일은 시작일과 같거나 이후여야 합니다.")
    st.caption(
        f"이 업로드 파일 기간 **{_forecast_upload_period_label()}** · "
        f"일평균 = 출고계 ÷ {int(period_days)}"
    )
    return float(min_out), period_days


RISK_COLORS = {
    "critical": "🔴",
    "warning": "🟡",
    "ok": "🟢",
}

EXPIRY_COLORS = {
    "expired": "⛔",
    "critical": "🔴",
    "warning": "🟡",
    "ok": "🟢",
}

TAB_OPTIONS: tuple[str, ...] = (
    "① 재고·발주·유통기한",
    "② 수요·프로모션",
    "③ 데이터 연동",
)


def _init_state() -> None:
    if "skus" not in st.session_state:
        st.session_state.skus = [copy.deepcopy(s) for s in DEFAULT_SKUS]
    if "imported_sales" not in st.session_state:
        st.session_state.imported_sales = None
    if "expiry_lots" not in st.session_state:
        st.session_state.expiry_lots = None
    if "master_editor_rev" not in st.session_state:
        st.session_state.master_editor_rev = 0


def _reapply_stored_expiry_lots(skus: list[SkuMaster]) -> list[SkuMaster]:
    lots = st.session_state.get("expiry_lots")
    if not lots:
        return skus
    updated, _ = apply_expiry_lots_to_skus(skus, lots)
    return updated


def _bump_data_editor(name: str) -> None:
    """Reset Streamlit data_editor widget state to avoid React DOM errors."""
    rev_key = f"{name}_rev"
    st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1


def _data_editor_key(name: str) -> str:
    return f"{name}_v{st.session_state.get(f'{name}_rev', 0)}"


def _file_uploader_key(name: str) -> str:
    return f"{name}_v{st.session_state.get(f'{name}_rev', 0)}"


def _reset_file_uploader(name: str) -> None:
    st.session_state[f"{name}_rev"] = st.session_state.get(f"{name}_rev", 0) + 1


def _save_session() -> bool:
    mark_persist_dirty()
    saved = persist_session_data()
    set_persist_flash(saved)
    return saved


def _sku_list() -> list[SkuMaster]:
    return st.session_state.skus


def _skus_by_id() -> dict[str, SkuMaster]:
    return {s.sku_id: s for s in _sku_list()}


def _fmt_num(value: float, digits: int = 1) -> str:
    if value >= 999:
        return "999+"
    return f"{value:.{digits}f}"


def _category_shares(skus: list[SkuMaster]) -> list[tuple[str, float, int]]:
    """Return (label, share, count) sorted by count descending."""
    if not skus:
        return []
    counts: dict[str, int] = {}
    for sku in skus:
        label = (sku.category_label or CATEGORIES.get(sku.category, sku.category)).strip()
        counts[label] = counts.get(label, 0) + 1
    total = len(skus)
    rows = [(label, count / total, count) for label, count in counts.items()]
    rows.sort(key=lambda row: (-row[2], row[0]))
    return rows


def _render_sidebar() -> tuple[float, str | None]:
    st.sidebar.header("Instock CT")
    st.sidebar.caption("Medi Market형 B2B 의료 소모품 · 발주·재고 시범")
    st.sidebar.caption("📌 **③ 데이터 연동** — ERP·WMS 업로드 · 마스터 편집")
    st.sidebar.caption(f"빌드 `{APP_BUILD}` — 미리보기 표 제거됨")
    target_days = st.sidebar.slider(
        "목표 재고 유지일",
        7,
        45,
        int(DEFAULT_TARGET_COVERAGE_DAYS),
        help="발주 후 유지하고 싶은 재고 일수",
    )
    category_filter = st.sidebar.multiselect(
        "카테고리 필터",
        options=list(CATEGORIES.keys()),
        default=list(CATEGORIES.keys()),
        format_func=lambda key: CATEGORIES[key],
    )
    if st.sidebar.button("샘플 SKU 초기화", use_container_width=True):
        clear_session_data()
        st.session_state.skus = [copy.deepcopy(s) for s in DEFAULT_SKUS]
        st.session_state.imported_sales = None
        _bump_data_editor("master_editor")
        st.rerun()
    if session_persist_available():
        st.sidebar.caption(persist_status_label())
        if st.sidebar.button("💾 지금 저장", use_container_width=True):
            if is_demo_skus(_sku_list()):
                st.sidebar.warning("데모 데이터는 저장하지 않습니다.")
            else:
                saved = _save_session()
                if saved:
                    st.sidebar.success("저장 완료")
                else:
                    st.sidebar.error("저장 실패")
                st.rerun()
        st.sidebar.caption("같은 브라우저·같은 주소(URL)로 다시 열면 데이터가 복원됩니다.")
        if st.sidebar.button("저장 데이터 삭제", use_container_width=True):
            clear_session_data()
            st.session_state.skus = [copy.deepcopy(s) for s in DEFAULT_SKUS]
            st.session_state.imported_sales = None
            st.session_state._session_persist_ready = True
            st.session_state._browser_storage_ready = True
            _bump_data_editor("master_editor")
            st.rerun()
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**카테고리 비중 (현재 {len(_sku_list())}건)**")
    shares = _category_shares(_sku_list())
    if shares:
        for label, share, count in shares:
            st.sidebar.progress(share, text=f"{label} {share:.0%} · {count}건")
    else:
        st.sidebar.caption("표시할 품목이 없습니다.")
    return float(target_days), category_filter or None


def _filter_skus(skus: list[SkuMaster], categories: list[str] | None) -> list[SkuMaster]:
    if not categories:
        return skus
    allowed = set(categories)
    return [s for s in skus if s.category in allowed]


def _skus_to_edit_frame(skus: list[SkuMaster]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "품목코드": s.sku_id,
                "품명": s.name,
                "카테고리": s.category_label,
                "현재고": s.on_hand,
                "일평균출고": s.avg_daily_demand,
                "리드타임일": s.lead_time_days,
                "MOQ": s.moq,
                "거래처명": s.vendor,
                "안전재고일": s.safety_stock_days,
                "유통기한": s.nearest_expiry or "",
                "임박재고": s.expiring_qty if s.expiring_qty is not None else "",
            }
            for s in skus
        ]
    )


def _to_float(value: object, default: float = 0.0) -> float:
    parsed = coerce_float(value, default=None)
    return default if parsed is None else parsed


def _to_int(value: object, default: int = 1) -> int:
    return int(_to_float(value, float(default)))


def _parse_edit_frame(frame: pd.DataFrame) -> tuple[list[SkuMaster] | None, list[str]]:
    errors: list[str] = []
    if frame.empty:
        return None, ["저장할 SKU가 없습니다."]

    skus: list[SkuMaster] = []
    seen_ids: set[str] = set()

    for index, row in frame.iterrows():
        row_no = int(index) + 1 if isinstance(index, int) else len(skus) + 1
        sku_id = str(row.get("품목코드", "")).strip()
        name = str(row.get("품명", "")).strip()
        category_label = str(row.get("카테고리", "")).strip()

        if not sku_id and not name:
            continue
        if not sku_id:
            errors.append(f"{row_no}행: 품목코드를 입력하세요.")
            continue
        if not name:
            errors.append(f"{row_no}행 ({sku_id}): 품명을 입력하세요.")
            continue
        if sku_id in seen_ids:
            errors.append(f"{row_no}행: 품목코드 중복 — {sku_id}")
            continue
        seen_ids.add(sku_id)

        if not category_label:
            errors.append(f"{row_no}행 ({sku_id}): 카테고리를 입력하세요.")
            continue

        cat_code, cat_label = _resolve_category(category_label)

        try:
            on_hand = _to_float(row.get("현재고", 0))
            avg_daily = _to_float(row.get("일평균출고", 0))
            lead_time = _to_int(row.get("리드타임일", 1), 1)
            moq = _to_int(row.get("MOQ", 1), 1)
            safety_days = _to_float(row.get("안전재고일", 7), 7.0)
        except (TypeError, ValueError):
            errors.append(f"{row_no}행 ({sku_id}): 숫자 형식이 올바르지 않습니다.")
            continue

        if lead_time < 1:
            lead_time = 1
        if moq < 1:
            moq = 1

        invalid_fields: list[str] = []
        if avg_daily < 0:
            invalid_fields.append("일평균출고")
        if safety_days < 0:
            invalid_fields.append("안전재고(일)")
        if invalid_fields:
            errors.append(
                f"{row_no}행 ({sku_id}): {', '.join(invalid_fields)} — 0 이상이어야 합니다."
            )
            continue

        raw_expiry = str(row.get("유통기한", "")).strip()
        nearest_expiry = None
        if raw_expiry and raw_expiry.lower() not in {"none", "nan", "-", "n/a"}:
            parsed_expiry = parse_expiry_date(raw_expiry)
            if parsed_expiry is None:
                errors.append(f"{row_no}행 ({sku_id}): 유통기한 형식 오류 — YYYY-MM-DD")
                continue
            nearest_expiry = parsed_expiry.isoformat()

        expiring_qty = None
        raw_expiring = row.get("임박재고", "")
        if raw_expiring is not None and str(raw_expiring).strip() not in {"", "nan", "None"}:
            expiring_qty = _to_float(raw_expiring, 0.0)
            if expiring_qty < 0:
                errors.append(f"{row_no}행 ({sku_id}): 임박재고는 0 이상이어야 합니다.")
                continue

        skus.append(
            SkuMaster(
                sku_id=sku_id,
                name=name,
                category=cat_code,
                category_label=cat_label,
                on_hand=on_hand,
                avg_daily_demand=avg_daily,
                lead_time_days=lead_time,
                moq=moq,
                vendor=str(row.get("거래처명", "")).strip() or "-",
                safety_stock_days=safety_days,
                nearest_expiry=nearest_expiry,
                expiring_qty=expiring_qty,
            )
        )

    if errors:
        return None, errors
    if not skus:
        return None, ["저장할 SKU가 없습니다."]
    return skus, []


def tab_master_edit(skus: list[SkuMaster]) -> None:
    _render_master_edit(skus)


@st.fragment
def _render_master_edit(skus: list[SkuMaster]) -> None:
    st.caption("표에서 값을 수정한 뒤 **변경사항 저장** — 다른 탭에 즉시 반영됩니다. 행 추가·삭제도 가능합니다.")

    flash = st.session_state.pop("master_save_flash", None)
    render_persist_flash()
    if flash:
        st.success(flash)

    st.info("재고·WMS 파일 업로드는 **「ERP · WMS 가져오기」** 탭에서 하세요. 여기는 표 편집용입니다.")
    st.markdown("---")

    st.markdown("**📥 대량 가져오기 (CSV / Excel)**")
    st.caption(
        "ERP·영림원·최소 4컬럼 형식을 지원합니다. "
        "카테고리는 **품목분류2** 값이 우선 반영됩니다."
    )
    bulk_preset = st.radio(
        "파일 형식",
        options=list(PRESET_LABELS.keys()),
        format_func=lambda k: PRESET_LABELS[k],
        horizontal=True,
        key="master_bulk_preset",
    )
    bulk_mode = st.selectbox(
        "가져오기 방식",
        options=list(MERGE_MODE_LABELS.keys()),
        format_func=lambda k: MERGE_MODE_LABELS[k],
        key="master_bulk_mode",
    )
    ylw_min_out, ylw_period = _render_younglimwon_date_range()
    tpl_c1, tpl_c2 = st.columns(2)
    with tpl_c1:
        st.download_button(
            "최소 템플릿 (4컬럼)",
            build_minimal_erp_sku_csv_bytes(),
            file_name="erp_inventory_minimal.csv",
            mime="text/csv",
            use_container_width=True,
            key="master_bulk_tpl_min",
        )
    with tpl_c2:
        st.download_button(
            "전체 샘플 CSV",
            build_sample_erp_sku_csv_bytes(),
            file_name="erp_inventory_export.sample.csv",
            mime="text/csv",
            use_container_width=True,
            key="master_bulk_tpl_sample",
        )
    bulk_file = st.file_uploader(
        "재고 CSV / Excel (.xlsx)",
        type=["csv", "xlsx", "xls"],
        key=_file_uploader_key("master_bulk_inv"),
    )
    run_bulk_import = st.button(
        "가져오기 실행",
        type="primary",
        use_container_width=True,
        key="master_bulk_run",
        disabled=bulk_file is None,
    )
    if run_bulk_import and bulk_file is not None:
        raw = read_uploaded_table(bulk_file)
        imported, report = parse_inventory_upload(
            bulk_file,
            preset=bulk_preset,
            min_outbound=float(ylw_min_out),
            period_days=float(ylw_period),
        )
        if report.ok:
            merged, stats = merge_sku_masters(skus, imported, mode=bulk_mode)
            st.session_state.skus = merged
            st.session_state.imported_sales = sync_sales_from_inventory(
                raw,
                merged,
                preset=bulk_preset,
                min_outbound=float(ylw_min_out),
                period_days=float(ylw_period),
                period_end_date=_younglimwon_period_end_iso(),
                period_start_date=_younglimwon_period_start_iso(),
            ) or None
            _bump_data_editor("master_editor")
            _reset_file_uploader("master_bulk_inv")
            parts = [f"파일 {len(imported)}건 처리"]
            if stats["added"]:
                parts.append(f"신규 {stats['added']}건")
            if stats["updated"]:
                parts.append(f"갱신 {stats['updated']}건")
            if stats["skipped"]:
                parts.append(f"건너뜀 {stats['skipped']}건")
            parts.append(f"총 {stats['total']}건")
            if st.session_state.imported_sales:
                parts.append(f"② 수요·프로모션 {len(st.session_state.imported_sales)}건 연동")
            saved = _save_session()
            parts.append(persist_result_message(saved).strip())
            st.session_state.master_save_flash = " · ".join(parts)
            _store_younglimwon_source_frame(raw)
            for warning in report.warnings[:5]:
                st.warning(warning)
            st.rerun()
        else:
            st.error("; ".join(report.messages))

    st.markdown("---")
    st.markdown(f"**현재 품목 {len(skus)}건**")
    if len(skus) > 300:
        st.info("품목이 많으면 표 스크롤·저장에 시간이 걸릴 수 있습니다. 대량 수정은 CSV 가져오기를 권장합니다.")

    editor_height = 520 if len(skus) > 80 else None
    editor_kwargs: dict = {
        "num_rows": "dynamic",
        "use_container_width": True,
        "hide_index": True,
        "column_config": {
            "품목코드": st.column_config.TextColumn("품목코드", required=True, width="small"),
            "품명": st.column_config.TextColumn("품명", required=True, width="medium"),
            "카테고리": st.column_config.TextColumn(
                "카테고리",
                help="ERP 품목분류2 값 (가져오기 시 자동 입력)",
                required=True,
                width="medium",
            ),
            "현재고": st.column_config.NumberColumn("현재고", step=1, format="%.0f"),
            "일평균출고": st.column_config.NumberColumn("일평균출고", min_value=0, step=0.1, format="%.1f"),
            "리드타임일": st.column_config.NumberColumn("리드타임(일)", min_value=0, step=1),
            "MOQ": st.column_config.NumberColumn("MOQ", min_value=0, step=1),
            "거래처명": st.column_config.TextColumn("거래처명", width="small"),
            "안전재고일": st.column_config.NumberColumn("안전재고(일)", min_value=0, step=1),
            "유통기한": st.column_config.TextColumn(
                "유통기한",
                help="YYYY-MM-DD (비우면 미등록)",
                width="small",
            ),
            "임박재고": st.column_config.NumberColumn(
                "임박재고",
                min_value=0,
                step=1,
                help="해당 유통기한 LOT 수량 (비우면 현재고 기준)",
                format="%.0f",
            ),
        },
        "key": _data_editor_key("master_editor"),
    }
    if editor_height is not None:
        editor_kwargs["height"] = editor_height
    edited = st.data_editor(_skus_to_edit_frame(skus), **editor_kwargs)

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        save = st.button("변경사항 저장", type="primary", use_container_width=True, key="master_save_btn")
    with c2:
        st.download_button(
            "ERP 형식 CSV 다운로드",
            skus_to_erp_export_frame(skus).to_csv(index=False).encode("utf-8-sig"),
            file_name="erp_inventory_export.csv",
            mime="text/csv",
            use_container_width=True,
            key="master_csv_download",
        )
    with c3:
        st.info("Tip: 위 **대량 가져오기**로 ERP·영림원 파일을 바로 넣을 수 있습니다.")

    if save:
        parsed, errors = _parse_edit_frame(edited)
        if errors:
            for msg in errors[:8]:
                st.error(msg)
            if len(errors) > 8:
                st.error(f"외 {len(errors) - 8}건 오류")
        else:
            st.session_state.skus = parsed
            _refresh_sales_from_skus(parsed)
            sales_count = len(st.session_state.imported_sales or [])
            flash = f"SKU {len(parsed)}건 저장되었습니다."
            if sales_count:
                flash += f" ② 수요·프로모션 {sales_count}건 연동."
            saved = _save_session()
            flash += persist_result_message(saved)
            st.session_state.master_save_flash = flash
            _bump_data_editor("master_editor")
            st.rerun()


def _refresh_sales_from_skus(skus: list[SkuMaster]) -> None:
    sales = sales_from_sku_masters(
        skus,
        period_days=_younglimwon_period_days(),
        period_end_date=_younglimwon_period_end_iso(),
        period_start_date=_younglimwon_period_start_iso(),
    )
    st.session_state.imported_sales = sales if sales else None


def _default_turnover_thresholds() -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for code in CATEGORIES:
        thresholds[code] = DEFAULT_TURNOVER_THRESHOLDS_BY_CATEGORY.get(
            code,
            LOW_TURNOVER_THRESHOLD,
        )
    return thresholds


def _collect_turnover_threshold_inputs() -> tuple[dict[str, float] | None, list[str]]:
    errors: list[str] = []
    thresholds: dict[str, float] = {}
    rev = st.session_state.get("turnover_settings_rev", 0)

    for code, label in CATEGORIES.items():
        current = st.session_state.turnover_thresholds.get(code, LOW_TURNOVER_THRESHOLD)
        val = st.number_input(
            f"{label} — 저회전(회/년 미만)",
            min_value=0.5,
            max_value=24.0,
            value=float(current),
            step=0.5,
            help="연간 회전율이 이 값 미만이면 저회전",
            key=f"turnover_thr_{code}_{rev}",
        )
        if val <= 0:
            errors.append(f"{label}: 0.5 이상 입력하세요.")
        thresholds[code] = float(val)

    if errors:
        return None, errors
    return thresholds, []


def _worst_expiry_by_sku(alerts: list[ExpiryAlert]) -> dict[str, ExpiryAlert]:
    worst: dict[str, ExpiryAlert] = {}
    for alert in alerts:
        prev = worst.get(alert.sku_id)
        if prev is None or alert.days_remaining < prev.days_remaining:
            worst[alert.sku_id] = alert
    return worst


def _render_reorder_section(skus: list[SkuMaster], target_days: float) -> None:
    plans = [build_reorder_plan(s, target_coverage_days=target_days) for s in skus]
    need_order = [p for p in plans if p.recommended_qty > 0]
    st.metric("발주 필요 SKU", len(need_order), delta=f"전체 {len(skus)} SKU")

    rows = []
    for plan in sorted(need_order, key=lambda item: item.recommended_qty, reverse=True):
        sku = _skus_by_id()[plan.sku_id]
        rows.append(
            {
                "SKU": plan.sku_id,
                "품명": plan.name,
                "현재고": plan.current_on_hand,
                "발주점": round(plan.reorder_point, 1),
                "권장 발주량": plan.recommended_qty,
                "MOQ": plan.moq,
                "리드타임(일)": plan.lead_time_days,
                "발주 후 재고일수": round(plan.projected_dos_after, 1),
                "거래처": sku.vendor,
                "비고": plan.note,
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        export_df = build_reorder_export_frame(skus, target_coverage_days=target_days)
        if not export_df.empty:
            st.download_button(
                "ERP 발주안 CSV 다운로드",
                export_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="instock_reorder_suggest.csv",
                mime="text/csv",
            )
    else:
        st.success("현재 조건에서 추가 발주가 필요한 SKU가 없습니다.")

    st.divider()
    st.markdown("**품목별 발주 시뮬레이션**")
    sku_ids = [s.sku_id for s in skus]
    picked = st.selectbox(
        "품목 선택",
        sku_ids,
        format_func=lambda sid: f"{sid} — {_skus_by_id()[sid].name}",
        key="ops_reorder_sim_sku",
    )
    sku = _skus_by_id()[picked]
    col1, col2, col3 = st.columns(3)
    with col1:
        override_demand = st.number_input(
            "가정 일평균 출고",
            value=float(sku.avg_daily_demand),
            min_value=0.0,
            step=1.0,
            key="ops_reorder_sim_demand",
        )
    with col2:
        override_lead = st.number_input(
            "리드타임(일)",
            value=int(sku.lead_time_days),
            min_value=1,
            step=1,
            key="ops_reorder_sim_lead",
        )
    with col3:
        override_moq = st.number_input(
            "MOQ",
            value=int(sku.moq),
            min_value=1,
            step=1,
            key="ops_reorder_sim_moq",
        )

    sim = copy.deepcopy(sku)
    sim.avg_daily_demand = override_demand
    sim.lead_time_days = int(override_lead)
    sim.moq = int(override_moq)
    qty = recommended_reorder_qty(sim, target_coverage_days=target_days)
    m1, m2, m3 = st.columns(3)
    m1.metric("발주점", f"{sim.reorder_point:,.0f}")
    m2.metric("권장 발주량", qty)
    m3.metric("안전재고 수량", f"{sim.safety_stock_units:,.0f}")


def tab_operations_hub(skus: list[SkuMaster], target_days: float) -> None:
    _render_operations_hub(skus, target_days)


@st.fragment
def _render_operations_hub(skus: list[SkuMaster], target_days: float) -> None:
    st.subheader("재고·발주·유통기한")
    st.caption(
        "결품 위험 · MOQ/리드타임 발주 · WMS 유통기한을 SKU 한 표에서 확인 — "
        "세부는 아래 접기 메뉴"
    )

    if "turnover_thresholds" not in st.session_state:
        st.session_state.turnover_thresholds = _default_turnover_thresholds()
    if "turnover_settings_rev" not in st.session_state:
        st.session_state.turnover_settings_rev = 0
    if "expiry_thresholds" not in st.session_state:
        st.session_state.expiry_thresholds = _default_expiry_thresholds()
    if "expiry_settings_rev" not in st.session_state:
        st.session_state.expiry_settings_rev = 0

    draft_turnover = None
    draft_thresholds = None

    with st.expander("카테고리별 저회전 기준", expanded=False):
        draft_turnover, turnover_errors = _collect_turnover_threshold_inputs()
        t1, t2 = st.columns([1, 3])
        with t1:
            apply_turnover = st.button(
                "기준 적용",
                type="primary",
                use_container_width=True,
                key="turnover_apply",
            )
        with t2:
            reset_turnover = st.button(
                "기본값 복원",
                use_container_width=True,
                key="turnover_reset",
            )
        if reset_turnover:
            st.session_state.turnover_thresholds = _default_turnover_thresholds()
            st.session_state.turnover_settings_rev += 1
            st.rerun()
        if apply_turnover:
            if turnover_errors:
                for msg in turnover_errors[:5]:
                    st.error(msg)
            elif draft_turnover:
                st.session_state.turnover_thresholds = draft_turnover
                st.success("카테고리별 저회전 기준을 저장했습니다.")

    with st.expander("카테고리별 유통기한 임박·주의 기준", expanded=False):
        draft_thresholds, draft_errors = _collect_expiry_threshold_inputs()
        t1, t2 = st.columns([1, 3])
        with t1:
            apply_thresholds = st.button(
                "기준 적용",
                type="primary",
                use_container_width=True,
                key="ops_expiry_apply",
            )
        with t2:
            reset_thresholds = st.button(
                "기본값 복원",
                use_container_width=True,
                key="ops_expiry_reset",
            )
        if reset_thresholds:
            st.session_state.expiry_thresholds = _default_expiry_thresholds()
            st.session_state.expiry_settings_rev += 1
            st.rerun()
        if apply_thresholds:
            if draft_errors:
                for msg in draft_errors[:5]:
                    st.error(msg)
            elif draft_thresholds:
                st.session_state.expiry_thresholds = draft_thresholds
                st.success("카테고리별 유통기한 기준을 저장했습니다.")

    turnover_thresholds = (
        draft_turnover if draft_turnover else st.session_state.turnover_thresholds
    )
    expiry_thresholds = (
        draft_thresholds if draft_thresholds else st.session_state.expiry_thresholds
    )

    risks = [assess_stockout_risk(s) for s in skus]
    risk_by_sku = {r.sku_id: r for r in risks}
    plans = [build_reorder_plan(s, target_coverage_days=target_days) for s in skus]
    plan_by_sku = {p.sku_id: p for p in plans}
    expiry_alerts = build_expiry_lot_alerts(skus, thresholds_by_category=expiry_thresholds)
    worst_expiry = _worst_expiry_by_sku(expiry_alerts)

    counts = summarize_risk_counts(risks)
    slow_movers = filter_slow_movers(risks, thresholds_by_category=turnover_thresholds)
    expiry_counts = summarize_expiry_counts(expiry_alerts)
    need_order = sum(1 for p in plans if p.recommended_qty > 0)

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    c1.metric("🔴 결품 임박", counts["critical"])
    c2.metric("🟡 재고 주의", counts["warning"])
    c3.metric("📦 발주 필요", need_order)
    c4.metric("⛔ 기한 경과", expiry_counts["expired"])
    c5.metric("🔴 유통 임박", expiry_counts["critical"])
    c6.metric("📉 저회전", len(slow_movers))
    c7.metric("SKU 수", len(skus))

    unified_rows = []
    for sku in skus:
        risk = risk_by_sku[sku.sku_id]
        plan = plan_by_sku[sku.sku_id]
        exp = worst_expiry.get(sku.sku_id)
        turnover_display = (
            round(risk.annual_turnover, 1) if risk.annual_turnover is not None else None
        )
        unified_rows.append(
            {
                "결품": f"{RISK_COLORS[risk.risk_level]} {risk_label(risk.risk_level)}",
                "유통기한": (
                    f"{EXPIRY_COLORS[exp.risk_level]} {expiry_label(exp.risk_level)}"
                    if exp
                    else "—"
                ),
                "SKU": sku.sku_id,
                "품명": sku.name,
                "카테고리": sku.category_label,
                "현재고": risk.on_hand,
                "일평균 출고": round(risk.avg_daily_demand, 1),
                "재고일수": round(risk.days_of_supply, 1),
                "권장 발주": plan.recommended_qty,
                "발주점": round(plan.reorder_point, 1),
                "MOQ": plan.moq,
                "리드(일)": plan.lead_time_days,
                "가까운 유통기한": exp.expiry_date if exp else (sku.nearest_expiry or "—"),
                "잔여일": exp.days_remaining if exp else None,
                "연간 회전(회)": turnover_display,
                "거래처": sku.vendor,
                "_risk_rank": {"critical": 0, "warning": 1, "ok": 2}.get(risk.risk_level, 3),
                "_exp_rank": (
                    {"expired": 0, "critical": 1, "warning": 2, "ok": 3}.get(exp.risk_level, 4)
                    if exp
                    else 5
                ),
                "_dos": risk.days_of_supply,
            }
        )

    unified_rows.sort(key=lambda row: (row["_risk_rank"], row["_exp_rank"], row["_dos"]))
    display_df = pd.DataFrame(unified_rows).drop(
        columns=["_risk_rank", "_exp_rank", "_dos"], errors="ignore"
    )
    st.dataframe(
        display_df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "현재고": st.column_config.NumberColumn(format="%.0f"),
            "일평균 출고": st.column_config.NumberColumn(format="%.1f"),
            "재고일수": st.column_config.NumberColumn(format="%.1f"),
            "권장 발주": st.column_config.NumberColumn(format="%.0f"),
            "발주점": st.column_config.NumberColumn(format="%.1f"),
            "잔여일": st.column_config.NumberColumn(format="%d"),
            "연간 회전(회)": st.column_config.NumberColumn(format="%.1f"),
        },
    )

    critical = [r for r in risks if r.risk_level == "critical"]
    if critical:
        st.warning(
            f"결품 임박 SKU {len(critical)}건 — 영업·물류팀 공유 필요: "
            + ", ".join(r.sku_id for r in critical[:8])
            + (" …" if len(critical) > 8 else "")
        )

    urgent_expiry = [a for a in expiry_alerts if a.risk_level in ("expired", "critical")]
    if urgent_expiry:
        st.warning(
            f"유통기한 즉시 조치 {len(urgent_expiry)}건: "
            + ", ".join(f"{a.sku_id}({a.days_remaining}일)" for a in urgent_expiry[:8])
            + (" …" if len(urgent_expiry) > 8 else "")
        )

    with st.expander("발주 추천 · ERP CSV · 시뮬레이션", expanded=False):
        _render_reorder_section(skus, target_days)

    with st.expander("유통기한 LOT · FEFO", expanded=False):
        _render_expiry_details(skus, expiry_thresholds, expiry_alerts)

    with st.expander("저회전 재고 (카테고리별 기준 미만)", expanded=False):
        if slow_movers:
            slow_rows = []
            for row in slow_movers[:15]:
                cutoff = get_turnover_threshold(row.category, turnover_thresholds)
                slow_rows.append(
                    {
                        "위험": f"{RISK_COLORS[row.risk_level]} {risk_label(row.risk_level)}",
                        "SKU": row.sku_id,
                        "품명": row.name,
                        "카테고리": row.category_label,
                        "현재고": row.on_hand,
                        "재고일수": round(row.days_of_supply, 1),
                        "연간 회전(회)": round(row.annual_turnover or 0, 1),
                        "저회전 기준": round(cutoff, 1),
                        "비고": (
                            "발주·입고 억제 검토"
                            if row.risk_level == "ok"
                            else "결품·과잉 동시 점검"
                        ),
                    }
                )
            st.dataframe(
                pd.DataFrame(slow_rows),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "현재고": st.column_config.NumberColumn(format="%.0f"),
                    "재고일수": st.column_config.NumberColumn(format="%.1f"),
                    "연간 회전(회)": st.column_config.NumberColumn(format="%.1f"),
                },
            )
        else:
            st.caption("현재 기준에 해당하는 저회전 SKU가 없습니다.")


def tab_reorder(skus: list[SkuMaster], target_days: float) -> None:
    st.subheader("발주 추천 (MOQ · 리드타임 · 안전재고)")
    _render_reorder_section(skus, target_days)


def tab_analysis(skus: list[SkuMaster], target_days: float) -> None:
    st.subheader("수요·프로모션")
    tab_forecast_panel, tab_promo_panel = st.tabs(["수요 예측", "프로모션 영향"])
    with tab_forecast_panel:
        tab_forecast(skus, target_days)
    with tab_promo_panel:
        tab_promo(skus)


def tab_data(skus: list[SkuMaster]) -> None:
    st.subheader("데이터 연동")
    panel = st.radio(
        "데이터 연동 메뉴",
        options=["ERP · WMS 가져오기", "마스터 편집"],
        horizontal=True,
        label_visibility="collapsed",
        key="data_link_panel",
    )
    if panel == "ERP · WMS 가져오기":
        tab_erp_import(skus)
    else:
        tab_master_edit(_sku_list())


def tab_promo(skus: list[SkuMaster]) -> None:
    st.caption("주 1~2회 긴급 프로모션 가정 — 수요 증가 시 결품·추가 발주량을 추정합니다")
    uplift = st.slider("프로모션 수요 증가 (%)", 0, 80, 30, 5)
    promo_days = st.slider("프로모션 기간 (일)", 3, 14, 7)

    impacts = [simulate_promo_impact(s, promo_uplift_pct=uplift, promo_days=promo_days) for s in skus]
    at_risk = [i for i in impacts if i.stockout_during_promo]
    extra_total = sum(i.extra_reorder_qty for i in impacts)

    c1, c2, c3 = st.columns(3)
    c1.metric("프로모션 중 결품 위험 SKU", len(at_risk))
    c2.metric("추가 발주 권장 합계", f"{extra_total:,}")
    c3.metric("수요 증가율", f"+{uplift}%")

    rows = []
    for item in sorted(impacts, key=lambda row: row.promo_dos):
        rows.append(
            {
                "SKU": item.sku_id,
                "품명": item.name,
                "평상 재고일수": round(item.baseline_dos, 1),
                "프로모션 시 재고일수": round(item.promo_dos, 1),
                "추가 수요(기간)": round(item.extra_demand_total, 1),
                "추가 발주 권장": item.extra_reorder_qty,
                "프로모션 결품 위험": "예" if item.stockout_during_promo else "아니오",
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    if at_risk:
        st.error(
            "프로모션 전 선발주 검토: "
            + ", ".join(i.sku_id for i in at_risk[:10])
            + (" …" if len(at_risk) > 10 else "")
        )


def tab_erp_import(skus: list[SkuMaster]) -> None:
    st.info(
        "**발주용 (매일):** ERP **최근 30일** export → **「① 재고 가져오기」** → "
        "기간 등록 → 파일 → **재고 가져오기** → **① 재고·발주·유통기한** 탭 확인. "
        "주간 추세는 **「③ 주간 출고 (선택)」**."
    )

    m1, m2, m3 = st.columns(3)
    m1.metric("로드 SKU", f"{len(skus):,}")
    lot_count = len(st.session_state.get("expiry_lots") or [])
    m2.metric("WMS LOT", f"{lot_count:,}" if lot_count else "—")
    sales_count = len(st.session_state.get("imported_sales") or [])
    m3.metric("수요 데이터", f"{sales_count:,}건" if sales_count else "—")

    tab_inv, tab_wms, tab_ship = st.tabs(
        ["① 재고 가져오기", "② WMS 유통기한", "③ 주간 출고 (선택)"]
    )

    with tab_inv:
        st.markdown("**영림원 2.xlsx** → 품목·현재고·일평균출고 반영")
        st.markdown("##### 1. 데이터 기간 등록 (업로드 전 · 필수)")
        ylw_min_out, ylw_period, period_ok = _render_inventory_file_period_registration()
        st.markdown("##### 2. 재고 파일 업로드")
        st.caption("위에 등록한 기간과 **같은 export**일 때만 올려 주세요.")
        inv_file = st.file_uploader(
            "재고 Excel / CSV",
            type=["csv", "xlsx", "xls"],
            key=_file_uploader_key("erp_inv"),
            disabled=not period_ok,
        )
        with st.expander("다른 파일 형식 · 샘플", expanded=False):
            preset = st.radio(
                "파일 형식",
                options=list(PRESET_LABELS.keys()),
                format_func=lambda k: PRESET_LABELS[k],
                key="erp_import_preset",
                horizontal=True,
            )
            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "최소 템플릿 CSV",
                    build_minimal_erp_sku_csv_bytes(),
                    file_name="erp_inventory_minimal.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            with c2:
                st.download_button(
                    "전체 샘플 CSV",
                    build_sample_erp_sku_csv_bytes(),
                    file_name="erp_inventory_export.sample.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
        st.markdown("##### 3. 가져오기 실행")
        if st.button(
            "✅ 재고 가져오기",
            type="primary",
            use_container_width=True,
            key="erp_inv_run",
            disabled=inv_file is None or not period_ok,
        ):
            preset = st.session_state.get("erp_import_preset", "younglimwon")
            raw = read_uploaded_table(inv_file)
            skus, report = parse_inventory_upload(
                inv_file,
                preset=preset,
                min_outbound=float(ylw_min_out),
                period_days=float(ylw_period),
            )
            if report.ok:
                st.session_state.skus = _reapply_stored_expiry_lots(skus)
                st.session_state.imported_sales = sync_sales_from_inventory(
                    raw,
                    skus,
                    preset=preset,
                    min_outbound=float(ylw_min_out),
                    period_days=float(ylw_period),
                    period_end_date=_younglimwon_period_end_iso(),
                    period_start_date=_younglimwon_period_start_iso(),
                ) or None
                _bump_data_editor("master_editor")
                _reset_file_uploader("erp_inv")
                _store_younglimwon_source_frame(raw)
                saved = _save_session()
                st.success("; ".join(report.messages) + persist_result_message(saved))
                for w in report.warnings[:5]:
                    st.warning(w)
                st.rerun()
            else:
                st.error("; ".join(report.messages))

        if _has_younglimwon_outbound_source():
            _sync_younglimwon_demand_if_needed()
            with st.expander(
                f"계산 확인 · 마지막 가져오기 ({_younglimwon_period_label()})",
                expanded=False,
            ):
                st.caption(
                    "**이 표만** 출고계÷기간 계산 샘플(상위 10건)입니다. "
                    "전체 결과는 **① 재고·발주·유통기한** 탭에서 보세요."
                )
                _render_outbound_calc_panel(
                    period_days=ylw_period,
                    period_label=_younglimwon_period_label(),
                    raw_frame=_younglimwon_source_frame(),
                    outbound_totals=_younglimwon_outbound_totals() or None,
                    min_outbound=float(ylw_min_out),
                    wrap_expander=False,
                )

    with tab_wms:
        st.markdown("**WMS export** → SKU별 유통기한·LOT 수량 (영림원 파일에는 없음)")
        if lot_count:
            st.info(f"적용 중: {lot_count} LOT / {len({lot.sku_id for lot in st.session_state.expiry_lots})} SKU")
        wms_file = st.file_uploader(
            "WMS 유통기한 Excel / CSV",
            type=["csv", "xlsx", "xls"],
            key=_file_uploader_key("erp_wms_expiry"),
        )
        with st.expander("WMS 샘플 · 필수 컬럼", expanded=False):
            st.download_button(
                "샘플 CSV",
                build_sample_wms_expiry_csv_bytes(),
                file_name="wms_expiry.sample.csv",
                mime="text/csv",
            )
            st.code("상품코드(품목코드), 유통기한, 재고수량", language="text")
        if st.button(
            "✅ WMS 가져오기",
            type="primary",
            use_container_width=True,
            key="erp_wms_run",
            disabled=wms_file is None,
        ):
            try:
                raw = read_uploaded_table(wms_file)
                lots, report = parse_wms_expiry_lots(raw)
            except Exception as exc:
                st.error(f"파일을 읽을 수 없습니다: {exc}")
            else:
                if report.ok:
                    st.session_state.expiry_lots = lots
                    updated, match_report = apply_expiry_lots_to_skus(_sku_list(), lots)
                    st.session_state.skus = updated
                    _bump_data_editor("master_editor")
                    _reset_file_uploader("erp_wms_expiry")
                    saved = _save_session()
                    st.success(
                        "; ".join(report.messages + match_report.messages)
                        + persist_result_message(saved)
                    )
                    st.rerun()
                else:
                    st.error("; ".join(report.messages))
                for warning in report.warnings[:5]:
                    st.warning(warning)

    with tab_ship:
        st.markdown(
            "**주간 출고 이력** (품목코드·주간시작일·출고수량) — "
            "영림원 2.xlsx만 쓰면 **①만** 하면 됩니다."
        )
        ylw_min_out = float(st.session_state.get("ylw_min_outbound", 10.0))
        ylw_period = _younglimwon_period_days()
        ship_file = st.file_uploader(
            "출고 Excel / CSV",
            type=["csv", "xlsx", "xls"],
            key=_file_uploader_key("erp_ship"),
        )
        with st.expander("샘플 · 형식", expanded=False):
            preset = st.radio(
                "파일 형식",
                options=list(PRESET_LABELS.keys()),
                format_func=lambda k: PRESET_LABELS[k],
                key="erp_ship_preset",
                horizontal=True,
            )
            sample_path = _SAMPLES_DIR / "erp_weekly_shipment.sample.csv"
            if sample_path.is_file():
                st.download_button(
                    "주간 출고 샘플 CSV",
                    sample_path.read_bytes(),
                    file_name="erp_weekly_shipment.sample.csv",
                    mime="text/csv",
                )
            st.code("품목코드, 주간시작일, 출고수량", language="text")
        if st.button(
            "✅ 출고 가져오기",
            type="primary",
            use_container_width=True,
            key="erp_ship_run",
            disabled=ship_file is None,
        ):
            preset = st.session_state.get("erp_ship_preset", "erp_korean")
            try:
                raw = read_uploaded_table(ship_file)
                sales, report = parse_sales_upload(
                    raw,
                    preset=preset,
                    min_outbound=float(ylw_min_out),
                    period_days=float(ylw_period),
                    period_end_date=_younglimwon_period_end_iso(),
                    period_start_date=_younglimwon_period_start_iso(),
                )
            except Exception as exc:
                st.error(f"파일을 읽을 수 없습니다: {exc}")
            else:
                if report.ok:
                    st.session_state.imported_sales = sales
                    _reset_file_uploader("erp_ship")
                    saved = _save_session()
                    st.success("; ".join(report.messages) + persist_result_message(saved))
                    st.rerun()
                else:
                    st.error("; ".join(report.messages))
                for warning in report.warnings[:5]:
                    st.warning(warning)


def _render_weekly_sales_chart(sku_sales: pd.DataFrame) -> None:
    """Weekly qty trend via Plotly (browser fonts, no matplotlib CJK issue)."""
    import plotly.express as px

    plot_df = sku_sales.sort_values("week_start").copy()
    plot_df["week_start"] = plot_df["week_start"].astype(str)

    if len(plot_df) == 1:
        row = plot_df.iloc[0]
        st.metric("해당 주 출고량", f"{row['qty']:,.0f}", help=str(row["week_start"]))
        st.caption("주간 이력 2주 이상이면 추이 그래프가 표시됩니다.")
        return

    fig = px.line(
        plot_df,
        x="week_start",
        y="qty",
        markers=True,
        labels={"week_start": "주 시작일", "qty": "출고수량"},
    )
    fig.update_traces(line=dict(width=2, color="#2563eb"), marker=dict(size=7))
    fig.update_layout(
        height=320,
        margin=dict(l=20, r=20, t=10, b=40),
        yaxis=dict(rangemode="tozero"),
    )
    st.plotly_chart(fig, use_container_width=True)


def tab_forecast(skus: list[SkuMaster], target_days: float) -> None:
    st.caption(
        "주간 이력 2주 이상이면 **다음주 예측 = 최근주 + 주간 변화량 평균** · "
        "마스터/영림원 기간 1건이면 **주·월 평균**만 표시(추이 없음)"
    )

    sample_df = pd.DataFrame(weekly_sales_to_dataframe_rows(build_sample_weekly_sales()))
    master_sales = sales_from_sku_masters(
        skus,
        period_days=_younglimwon_period_days(),
        period_end_date=_younglimwon_period_end_iso(),
        period_start_date=_younglimwon_period_start_iso(),
    )
    if st.session_state.get("imported_sales"):
        linked_label = st.session_state.imported_sales[0].week_start
        st.success(
            f"출고·수요 데이터 {len(st.session_state.imported_sales)}건 · "
            f"기간 **{linked_label}** (③ 데이터 연동)"
        )
    elif master_sales:
        st.success(
            f"마스터 일평균출고 {len(master_sales)}건 · "
            f"기간 **{master_sales[0].week_start}** 로 환산"
        )

    st.download_button(
        "샘플 주간 출고 CSV (기본 형식)",
        sample_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="weekly_sales_sample.csv",
        mime="text/csv",
    )

    uploaded = None
    preset = st.session_state.get("forecast_preset", "erp_korean")
    with st.expander("주간 출고 CSV / Excel 추가 업로드 (선택)", expanded=False):
        st.caption(
            "파일에 **주간시작일**이 없으면(영림원 2.xlsx 등) 아래에서 "
            "**며칠~며칠 출고분인지** 꼭 지정하세요."
        )
        uploaded = st.file_uploader(
            "주간 출고 CSV / Excel",
            type=["csv", "xlsx", "xls"],
            key="forecast_upload",
        )
        preset = st.radio(
            "파일 형식",
            options=list(PRESET_LABELS.keys()),
            format_func=lambda k: PRESET_LABELS[k],
            horizontal=True,
            key="forecast_preset",
        )
        upload_min_out, upload_period_days = _render_forecast_upload_period_inputs()

    sales: list[WeeklySales] | None = None
    frame: pd.DataFrame
    load_warnings: list[str] = []
    upload_period_end = _forecast_upload_period_end_iso()
    upload_period_start = _forecast_upload_period_start_iso()

    if uploaded:
        try:
            raw = read_uploaded_table(uploaded)
        except Exception as exc:
            st.error(f"파일을 읽을 수 없습니다: {exc}")
            return
        file_has_week_dates = is_korean_sales_frame(raw) or "week_start" in {
            str(c).strip().lower() for c in raw.columns
        }
        use_korean = preset == "erp_korean" or is_korean_sales_frame(raw)
        if (
            use_korean
            and preset == "erp_korean"
            and is_korean_sales_frame(raw)
            and file_has_week_dates
        ):
            sales, report = parse_sales_csv(raw, preset="erp_korean")
        else:
            if preset != "erp_korean" and is_korean_sales_frame(raw):
                st.info("한글 컬럼(품목코드·주간시작일·출고수량)이 감지되어 ERP 한글 형식으로 읽습니다.")
            if not file_has_week_dates:
                st.info(f"파일에 날짜 없음 → **{_forecast_upload_period_label()}** 기준으로 환산합니다.")
            sales, report = parse_sales_upload(
                raw,
                preset=preset,
                min_outbound=float(upload_min_out),
                period_days=upload_period_days,
                period_end_date=upload_period_end,
                period_start_date=upload_period_start,
            )
        if not report.ok:
            st.error("; ".join(report.messages))
            return
        load_warnings = report.warnings
        st.success(
            f"업로드 파일 {len(sales)}건 반영 · 기간 **{_forecast_upload_period_label()}**"
        )
        frame = pd.DataFrame(
            [{"sku_id": s.sku_id, "week_start": s.week_start, "qty": s.qty} for s in sales]
        )
    elif st.session_state.get("imported_sales"):
        sales = st.session_state.imported_sales
        frame = pd.DataFrame(
            [{"sku_id": s.sku_id, "week_start": s.week_start, "qty": s.qty} for s in sales]
        )
    elif master_sales:
        sales = master_sales
        frame = pd.DataFrame(
            [{"sku_id": s.sku_id, "week_start": s.week_start, "qty": s.qty} for s in sales]
        )
    else:
        frame = sample_df
        st.info("데모: 내장 샘플 12주 데이터 사용 중")

    if sales is None:
        sales, report = parse_native_sales_frame(frame)
        if not report.ok:
            st.error("; ".join(report.messages))
            return
        load_warnings = report.warnings

    for warning in load_warnings[:8]:
        st.warning(warning)
    if len(load_warnings) > 8:
        st.warning(f"외 {len(load_warnings) - 8}건 변환 경고")

    if not sales:
        st.warning("예측할 데이터가 없습니다.")
        return

    frame.columns = [str(c).strip().lower() for c in frame.columns]
    names = {s.sku_id: s.name for s in skus}
    forecasts = forecast_from_weekly_sales(sales, sku_names=names)

    if not forecasts:
        st.warning("예측할 데이터가 없습니다.")
        return

    rows = []
    for item in forecasts[:30]:
        sku = _skus_by_id().get(item.sku_id)
        suggested_order = 0
        if sku:
            sim = copy.deepcopy(sku)
            sim.avg_daily_demand = item.suggested_daily_demand
            suggested_order = recommended_reorder_qty(sim, target_coverage_days=target_days)
        rows.append(
            {
                "SKU": item.sku_id,
                "품명": item.name,
                "집계 주수": item.history_weeks,
                "주간 평균": round(item.avg_weekly, 1),
                "월 평균": round(item.avg_monthly, 1),
                "다음주 예측": round(item.forecast_next_week, 1)
                if item.forecast_next_week is not None
                else "—",
                "환산 일출고": round(item.suggested_daily_demand, 2),
                "추세": item.trend,
                "예측 근거": item.forecast_basis,
                "예측 기반 발주량": suggested_order,
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    pick = st.selectbox(
        "품목별 출고 추이",
        [f.sku_id for f in forecasts[:15]],
        format_func=lambda sid: sid,
        key="forecast_trend_sku",
    )
    _render_product_name(names.get(pick, pick))
    sku_sales = frame[frame["sku_id"] == pick].sort_values("week_start")
    if not sku_sales.empty:
        _render_weekly_sales_chart(sku_sales)


def _default_expiry_thresholds() -> dict[str, tuple[float, float]]:
    thresholds: dict[str, tuple[float, float]] = {}
    for code in CATEGORIES:
        thresholds[code] = DEFAULT_EXPIRY_THRESHOLDS_BY_CATEGORY.get(
            code,
            (EXPIRY_CRITICAL_DAYS, EXPIRY_WARNING_DAYS),
        )
    return thresholds


def _collect_expiry_threshold_inputs() -> tuple[dict[str, tuple[float, float]] | None, list[str]]:
    errors: list[str] = []
    thresholds: dict[str, tuple[float, float]] = {}
    rev = st.session_state.get("expiry_settings_rev", 0)

    for code, label in CATEGORIES.items():
        critical, warning = st.session_state.expiry_thresholds.get(
            code,
            (EXPIRY_CRITICAL_DAYS, EXPIRY_WARNING_DAYS),
        )
        col1, col2 = st.columns(2)
        with col1:
            crit_val = st.number_input(
                f"{label} — 임박(일)",
                min_value=1,
                max_value=180,
                value=int(critical),
                step=1,
                key=f"expiry_crit_{code}_{rev}",
            )
        with col2:
            warn_val = st.number_input(
                f"{label} — 주의(일)",
                min_value=int(crit_val) + 1,
                max_value=730,
                value=max(int(warning), int(crit_val) + 1),
                step=1,
                key=f"expiry_warn_{code}_{rev}",
            )
        if warn_val <= crit_val:
            errors.append(f"{label}: 주의(일)는 임박(일)보다 커야 합니다.")
        thresholds[code] = (float(crit_val), float(warn_val))

    if errors:
        return None, errors
    return thresholds, []


def _render_expiry_details(
    skus: list[SkuMaster],
    thresholds: dict[str, tuple[float, float]],
    alerts: list[ExpiryAlert] | None = None,
) -> None:
    if alerts is None:
        alerts = build_expiry_lot_alerts(skus, thresholds_by_category=thresholds)

    lot_rows = sum(len(s.expiry_lots) for s in skus)
    tracked_skus = len({alert.sku_id for alert in alerts})
    without_expiry = len(skus) - tracked_skus
    counts = summarize_expiry_counts(alerts)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("⛔ 기한 경과", counts["expired"])
    c2.metric("🔴 임박", counts["critical"])
    c3.metric("🟡 주의", counts["warning"])
    c4.metric("🟢 양호", counts["ok"])
    c5.metric("LOT 행", lot_rows)
    c6.metric("미등록 SKU", without_expiry)

    if not alerts:
        st.info(
            "유통기한이 등록된 SKU가 없습니다. **③ 데이터 연동 → WMS 유통기한** "
            "또는 **마스터 편집**에서 입력하세요."
        )
        return

    lot_table = []
    for sku in skus:
        if not sku.expiry_lots:
            continue
        for lot in sku.expiry_lots:
            lot_table.append(
                {
                    "품목코드": sku.sku_id,
                    "품명": sku.name,
                    "유통기한": lot.expiry_date,
                    "LOT 수량": round(lot.qty, 0),
                    "현재고(전체)": round(sku.on_hand, 0),
                }
            )
    if lot_table:
        st.markdown("**유통기한별 재고 (WMS LOT)**")
        st.dataframe(
            pd.DataFrame(lot_table),
            hide_index=True,
            use_container_width=True,
            column_config={
                "LOT 수량": st.column_config.NumberColumn(format="%.0f"),
                "현재고(전체)": st.column_config.NumberColumn(format="%.0f"),
            },
        )

    rows = []
    for alert in alerts:
        rows.append(
            {
                "상태": f"{EXPIRY_COLORS[alert.risk_level]} {expiry_label(alert.risk_level)}",
                "SKU": alert.sku_id,
                "품명": alert.name,
                "카테고리": alert.category_label,
                "유통기한": alert.expiry_date,
                "잔여일": alert.days_remaining,
                "LOT 수량": round(alert.expiring_qty, 0),
                "현재고(전체)": alert.on_hand,
                "권장 조치": alert.action,
                "거래처": alert.vendor,
            }
        )
    st.markdown("**FEFO 우선순위 (잔여일 짧은 순 · LOT별)**")
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "잔여일": st.column_config.NumberColumn(format="%d"),
            "LOT 수량": st.column_config.NumberColumn(format="%.0f"),
            "현재고(전체)": st.column_config.NumberColumn(format="%.0f"),
        },
    )

    urgent = [a for a in alerts if a.risk_level in ("expired", "critical")]
    if urgent:
        st.warning(
            f"즉시 조치 필요 {len(urgent)}건: "
            + ", ".join(f"{a.sku_id}({a.days_remaining}일)" for a in urgent[:8])
            + (" …" if len(urgent) > 8 else "")
        )

    fefo = [a for a in alerts if a.risk_level != "ok"][:10]
    if fefo:
        st.markdown("**출고 우선 (FEFO)**")
        for idx, alert in enumerate(fefo, start=1):
            st.write(
                f"{idx}. **{alert.sku_id}** {alert.name} — "
                f"{alert.expiry_date} (D-{alert.days_remaining}), "
                f"수량 {alert.expiring_qty:,.0f} · {alert.action}"
            )


def tab_expiry(skus: list[SkuMaster]) -> None:
    _render_expiry(skus)


@st.fragment
def _render_expiry(skus: list[SkuMaster]) -> None:
    st.subheader("유통기한 관리")
    st.caption("WMS LOT별 유통기한·수량 — FEFO 출고 · 카테고리별 임박/주의 알림")

    if "expiry_thresholds" not in st.session_state:
        st.session_state.expiry_thresholds = _default_expiry_thresholds()
    if "expiry_settings_rev" not in st.session_state:
        st.session_state.expiry_settings_rev = 0

    with st.expander("카테고리별 임박·주의 기준", expanded=True):
        draft_thresholds, draft_errors = _collect_expiry_threshold_inputs()
        t1, t2 = st.columns([1, 3])
        with t1:
            apply_thresholds = st.button("기준 적용", type="primary", use_container_width=True)
        with t2:
            reset_thresholds = st.button("기본값 복원", use_container_width=True)
        if reset_thresholds:
            st.session_state.expiry_thresholds = _default_expiry_thresholds()
            st.session_state.expiry_settings_rev += 1
            st.rerun()
        if apply_thresholds:
            if draft_errors:
                for msg in draft_errors[:5]:
                    st.error(msg)
            elif draft_thresholds:
                st.session_state.expiry_thresholds = draft_thresholds
                st.success("카테고리별 기준을 저장했습니다.")

    thresholds = draft_thresholds if draft_thresholds else st.session_state.expiry_thresholds
    _render_expiry_details(skus, thresholds)


def _render_active_tab(active_tab: str, skus: list[SkuMaster], target_days: float) -> None:
    if active_tab == TAB_OPTIONS[0]:
        tab_operations_hub(skus, target_days)
    elif active_tab == TAB_OPTIONS[1]:
        tab_analysis(skus, target_days)
    elif active_tab == TAB_OPTIONS[2]:
        tab_data(skus)


def main() -> None:
    _inject_notranslate()
    ensure_session_restored()
    _init_state()
    if st.session_state.pop("_browser_storage_corrupt", False):
        st.warning("저장 데이터가 손상되어 데모 데이터를 사용합니다.")
    if st.session_state.pop("_session_persist_restored", False):
        source = st.session_state.pop("_session_persist_source", "server")
        label = {"server": "서버", "global": "저장소", "sqlite": "저장소", "browser": "브라우저"}.get(
            source, "서버"
        )
        st.success(f"{label}에서 SKU {len(st.session_state.skus)}건을 복원했습니다.")
    target_days, categories = _render_sidebar()
    skus = _filter_skus(_sku_list(), categories)

    st.title("📊 Instock CT")
    st.caption(
        "의료 B2B 클리닉몰 · 재고관리 매니저용 시범 — "
        "재고·발주·유통기한 · 수요·프로모션 · ERP/WMS 데이터 연동"
    )

    active_tab = st.selectbox(
        "탭",
        TAB_OPTIONS,
        key="active_main_tab",
        label_visibility="collapsed",
    )

    try:
        _render_active_tab(active_tab, skus, target_days)
    except Exception as exc:
        st.error(f"탭 로드 오류 ({active_tab}): {exc}")

    st.markdown("---")
    st.caption(
        "포트폴리오 시범 · 가상 Medi Market 데이터 · "
        f"Python/Streamlit · 빌드 {APP_BUILD}"
    )


if __name__ == "__main__":
    main()
