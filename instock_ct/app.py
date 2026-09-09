"""
Instock CT — 의료 B2B 이커머스 발주·재고 관리 시범 (Portfolio)

실행:
  cd instock_ct
  pip install -r requirements.txt
  streamlit run app.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

_APP_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _APP_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from instock_ct.config import (  # noqa: E402
    CATEGORIES,
    CATEGORY_SHARE,
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
    build_reorder_export_frame,
    build_sample_erp_sku_csv_bytes,
    build_minimal_erp_sku_csv_bytes,
    coerce_float,
    is_korean_sales_frame,
    merge_sku_masters,
    parse_inventory_upload,
    parse_native_sales_frame,
    parse_sales_csv,
    parse_sales_upload,
    parse_sku_csv,
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
    build_expiry_alerts,
    expiry_label,
    parse_expiry_date,
    summarize_expiry_counts,
)

_SAMPLES_DIR = _APP_DIR / "samples"

st.set_page_config(page_title="Instock CT", page_icon="📊", layout="wide")

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
    "① 결품 위험",
    "② 발주 추천",
    "③ 프로모션 영향",
    "④ 수요 예측",
    "⑤ ERP 연동",
    "⑥ 유통기한",
    "⑦ 마스터 편집",
)


def _init_state() -> None:
    if "skus" not in st.session_state:
        st.session_state.skus = [copy.deepcopy(s) for s in DEFAULT_SKUS]
    if "imported_sales" not in st.session_state:
        st.session_state.imported_sales = None
    if "master_editor_rev" not in st.session_state:
        st.session_state.master_editor_rev = 0


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


def _render_sidebar() -> tuple[float, str | None]:
    st.sidebar.header("Instock CT")
    st.sidebar.caption("Medi Market형 B2B 의료 소모품 · 발주·재고 시범")
    st.sidebar.caption("📌 **⑦ 마스터 편집** — 재고·품목·유통기한 표에서 직접 수정")
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
    st.sidebar.markdown("**카테고리 비중 (공고 참고)**")
    for code, share in CATEGORY_SHARE.items():
        st.sidebar.progress(share, text=f"{CATEGORIES[code]} {share:.0%}")
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
    st.subheader("재고·품목 마스터 편집")
    st.caption("표에서 값을 수정한 뒤 **변경사항 저장** — 다른 탭에 즉시 반영됩니다. 행 추가·삭제도 가능합니다.")

    flash = st.session_state.pop("master_save_flash", None)
    render_persist_flash()
    if flash:
        st.success(flash)

    with st.expander("📥 대량 가져오기 (CSV / Excel)", expanded=len(skus) < 30):
        st.caption(
            "ERP·영림원·최소 4컬럼 형식을 지원합니다. "
            "카테고리는 **품목분류2** 값이 우선 반영됩니다. "
            "파일 선택 후 **가져오기 실행**을 누르세요. "
            "가져온 **일평균출고**는 ④ 수요 예측·② 발주에 자동 연동됩니다."
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
        ylw_c1, ylw_c2 = st.columns(2)
        with ylw_c1:
            master_ylw_min = st.number_input(
                "영림원: 출고계 최소 (이상만)",
                min_value=0.0,
                value=10.0,
                step=1.0,
                key="master_ylw_min_outbound",
            )
        with ylw_c2:
            master_ylw_period = st.number_input(
                "영림원: 출고계 기간(일) → 일평균출고",
                min_value=1,
                max_value=365,
                value=30,
                step=1,
                key="master_ylw_period_days",
            )
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
                min_outbound=float(master_ylw_min),
                period_days=float(master_ylw_period),
            )
            if report.ok:
                merged, stats = merge_sku_masters(skus, imported, mode=bulk_mode)
                st.session_state.skus = merged
                st.session_state.imported_sales = sync_sales_from_inventory(
                    raw,
                    merged,
                    preset=bulk_preset,
                    min_outbound=float(master_ylw_min),
                    period_days=float(master_ylw_period),
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
                    parts.append(f"④ 수요예측 {len(st.session_state.imported_sales)}건 연동")
                saved = _save_session()
                parts.append(persist_result_message(saved).strip())
                st.session_state.master_save_flash = " · ".join(parts)
                for warning in report.warnings[:5]:
                    st.warning(warning)
                st.rerun()
            else:
                st.error("; ".join(report.messages))

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
                flash += f" ④ 수요예측 {sales_count}건 연동."
            saved = _save_session()
            flash += persist_result_message(saved)
            st.session_state.master_save_flash = flash
            _bump_data_editor("master_editor")
            st.rerun()


def _refresh_sales_from_skus(skus: list[SkuMaster]) -> None:
    sales = sales_from_sku_masters(skus)
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


def tab_stockout_board(skus: list[SkuMaster], target_days: float) -> None:
    _render_stockout_board(skus)


@st.fragment
def _render_stockout_board(skus: list[SkuMaster]) -> None:
    st.subheader("결품 위험 · 재고 회전")
    st.caption("재고일수·연간 회전율 — 결품 임박과 카테고리별 저회전(과잉) 재고 확인")

    if "turnover_thresholds" not in st.session_state:
        st.session_state.turnover_thresholds = _default_turnover_thresholds()
    if "turnover_settings_rev" not in st.session_state:
        st.session_state.turnover_settings_rev = 0

    with st.expander("카테고리별 저회전 기준", expanded=False):
        draft_turnover, turnover_errors = _collect_turnover_threshold_inputs()
        t1, t2 = st.columns([1, 3])
        with t1:
            apply_turnover = st.button("기준 적용", type="primary", use_container_width=True, key="turnover_apply")
        with t2:
            reset_turnover = st.button("기본값 복원", use_container_width=True, key="turnover_reset")
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

    turnover_thresholds = (
        draft_turnover if draft_turnover else st.session_state.turnover_thresholds
    )

    risks = [assess_stockout_risk(s) for s in skus]
    counts = summarize_risk_counts(risks)
    slow_movers = filter_slow_movers(risks, thresholds_by_category=turnover_thresholds)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🔴 결품 임박", counts["critical"])
    c2.metric("🟡 주의", counts["warning"])
    c3.metric("🟢 양호", counts["ok"])
    c4.metric("📉 저회전", len(slow_movers))
    c5.metric("SKU 수", len(skus))

    rows = []
    for row in sorted(risks, key=lambda item: item.days_of_supply):
        turnover_display = (
            round(row.annual_turnover, 1) if row.annual_turnover is not None else None
        )
        rows.append(
            {
                "위험": f"{RISK_COLORS[row.risk_level]} {risk_label(row.risk_level)}",
                "SKU": row.sku_id,
                "품명": row.name,
                "카테고리": row.category_label,
                "현재고": row.on_hand,
                "일평균 출고": round(row.avg_daily_demand, 1),
                "재고일수": round(row.days_of_supply, 1),
                "연간 회전(회)": turnover_display,
                "권장 발주량": row.reorder_qty,
                "거래처": row.vendor,
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "현재고": st.column_config.NumberColumn(format="%.0f"),
            "일평균 출고": st.column_config.NumberColumn(format="%.1f"),
            "재고일수": st.column_config.NumberColumn(format="%.1f"),
            "연간 회전(회)": st.column_config.NumberColumn(
                format="%.1f",
                help="365 ÷ 재고일수 (연간 수량 기준)",
            ),
        },
    )

    critical = [r for r in risks if r.risk_level == "critical"]
    if critical:
        st.warning(
            f"결품 임박 SKU {len(critical)}건 — 영업·물류팀 공유 필요: "
            + ", ".join(r.sku_id for r in critical[:8])
            + (" …" if len(critical) > 8 else "")
        )

    st.markdown("**저회전 재고 (카테고리별 기준 미만)**")
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
                    "비고": "발주·입고 억제 검토" if row.risk_level == "ok" else "결품·과잉 동시 점검",
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
    picked = st.selectbox("품목 선택", sku_ids, format_func=lambda sid: f"{sid} — {_skus_by_id()[sid].name}")
    sku = _skus_by_id()[picked]
    col1, col2, col3 = st.columns(3)
    with col1:
        override_demand = st.number_input("가정 일평균 출고", value=float(sku.avg_daily_demand), min_value=0.0, step=1.0)
    with col2:
        override_lead = st.number_input("리드타임(일)", value=int(sku.lead_time_days), min_value=1, step=1)
    with col3:
        override_moq = st.number_input("MOQ", value=int(sku.moq), min_value=1, step=1)

    sim = copy.deepcopy(sku)
    sim.avg_daily_demand = override_demand
    sim.lead_time_days = int(override_lead)
    sim.moq = int(override_moq)
    qty = recommended_reorder_qty(sim, target_coverage_days=target_days)
    m1, m2, m3 = st.columns(3)
    m1.metric("발주점", f"{sim.reorder_point:,.0f}")
    m2.metric("권장 발주량", qty)
    m3.metric("안전재고 수량", f"{sim.safety_stock_units:,.0f}")


def tab_promo(skus: list[SkuMaster]) -> None:
    st.subheader("긴급 프로모션 영향 분석")
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
    st.subheader("ERP·WMS 연동")
    st.caption("사내 ERP 내보내기 CSV → Instock CT · 발주안 CSV → ERP 재등록")
    st.info(
        "**전 컬럼을 손으로 채울 필요 없습니다.** "
        "WMS·ERP·재고 Excel에서 **품목코드·품명·현재고**만 있어도 가져올 수 있습니다. "
        "나머지(리드타임·MOQ·유통기한 등)는 없으면 기본값이 들어가고, **⑦ 마스터 편집**에서 나중에 보완하면 됩니다."
    )

    st.markdown(f"**현재 로드된 품목 ({len(skus)}건)**")
    if skus:
        st.dataframe(
            _skus_to_edit_frame(skus),
            hide_index=True,
            use_container_width=True,
            height=320,
        )
    else:
        st.warning("표시할 SKU가 없습니다. 사이드바에서 카테고리를 확인하거나 샘플 SKU를 초기화하세요.")

    st.markdown("---")
    preset = st.radio(
        "파일 형식",
        options=list(PRESET_LABELS.keys()),
        format_func=lambda k: PRESET_LABELS[k],
        horizontal=True,
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**① 재고·품목 정보 가져오기**")
        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "최소 템플릿 (4컬럼)",
                build_minimal_erp_sku_csv_bytes(),
                file_name="erp_inventory_minimal.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with d2:
            st.download_button(
                "전체 샘플 CSV",
                build_sample_erp_sku_csv_bytes(),
                file_name="erp_inventory_export.sample.csv",
                mime="text/csv",
                use_container_width=True,
            )
        st.caption("필수: 품목코드 · 품명 · 현재고 · (권장) 일평균출고")
        ylw_min_out = st.number_input(
            "영림원: 출고계 최소 (이상만)",
            min_value=0.0,
            value=10.0,
            step=1.0,
            help="2.xlsx처럼 영림원 재고현황 업로드 시 적용",
            key="ylw_min_outbound",
        )
        ylw_period = st.number_input(
            "영림원: 출고계 기간(일) → 일평균출고",
            min_value=1,
            max_value=365,
            value=30,
            step=1,
            help="월간 재고현황이면 30, 주간이면 7",
            key="ylw_period_days",
        )
        inv_file = st.file_uploader(
            "재고 CSV / Excel (.xlsx)",
            type=["csv", "xlsx", "xls"],
            key=_file_uploader_key("erp_inv"),
        )
        run_inv_import = st.button(
            "재고 가져오기 실행",
            type="primary",
            use_container_width=True,
            key="erp_inv_run",
            disabled=inv_file is None,
        )
        if run_inv_import and inv_file is not None:
            raw = read_uploaded_table(inv_file)
            skus, report = parse_inventory_upload(
                inv_file,
                preset=preset,
                min_outbound=float(ylw_min_out),
                period_days=float(ylw_period),
            )
            if report.ok:
                st.session_state.skus = skus
                st.session_state.imported_sales = sync_sales_from_inventory(
                    raw,
                    skus,
                    preset=preset,
                    min_outbound=float(ylw_min_out),
                    period_days=float(ylw_period),
                ) or None
                _bump_data_editor("master_editor")
                _reset_file_uploader("erp_inv")
                saved = _save_session()
                st.success("; ".join(report.messages) + persist_result_message(saved))
                if st.session_state.imported_sales:
                    st.info(
                        f"④ 수요 예측 탭에 출고 데이터 {len(st.session_state.imported_sales)}건 연동됨"
                    )
                for w in report.warnings[:5]:
                    st.warning(w)
                st.dataframe(skus_to_erp_export_frame(skus).head(10), hide_index=True)
            else:
                st.error("; ".join(report.messages))

    with col_b:
        st.markdown("**② 주간 출고 데이터 가져오기 (선택)**")
        st.caption(
            "영림원 **2.xlsx**는 왼쪽 재고 업로드만으로 충분합니다(출고계→일평균출고). "
            "여기는 ④ 수요 예측용 **주간 출고 이력** 또는 같은 재고현황 파일을 넣을 때 사용합니다."
        )
        sample_path = _SAMPLES_DIR / "erp_weekly_shipment.sample.csv"
        if sample_path.is_file():
            st.download_button(
                "ERP 출고 내보내기 샘플 CSV",
                sample_path.read_bytes(),
                file_name="erp_weekly_shipment.sample.csv",
                mime="text/csv",
            )
        ship_file = st.file_uploader(
            "출고 CSV / Excel",
            type=["csv", "xlsx", "xls"],
            key=_file_uploader_key("erp_ship"),
        )
        run_ship_import = st.button(
            "출고 가져오기 실행",
            type="primary",
            use_container_width=True,
            key="erp_ship_run",
            disabled=ship_file is None,
        )
        if run_ship_import and ship_file is not None:
            try:
                raw = read_uploaded_table(ship_file)
                sales, report = parse_sales_upload(
                    raw,
                    preset=preset,
                    min_outbound=float(ylw_min_out),
                    period_days=float(ylw_period),
                )
            except Exception as exc:
                st.error(f"파일을 읽을 수 없습니다: {exc}")
            else:
                if report.ok:
                    st.session_state.imported_sales = sales
                    _reset_file_uploader("erp_ship")
                    saved = _save_session()
                    st.success("; ".join(report.messages) + persist_result_message(saved))
                    st.info("④ 수요 예측 탭에서 이 데이터를 사용합니다.")
                else:
                    st.error("; ".join(report.messages))
                for warning in report.warnings[:5]:
                    st.warning(warning)

    st.markdown("---")
    st.markdown("**필수 컬럼 (재고 CSV)**")
    st.code("품목코드, 품명, 현재고", language="text")
    st.markdown("**선택 컬럼 — 없으면 기본값**")
    st.code(
        "일평균출고(0), 카테고리(일반 소모품), 리드타임일(7), MOQ(1), "
        "거래처명(-), 안전재고일(7), 유통기한, 임박재고",
        language="text",
    )
    st.markdown("**ERP 한글 내보내기 필수 컬럼 (출고)**")
    st.code("품목코드, 주간시작일, 출고수량", language="text")


def tab_forecast(skus: list[SkuMaster], target_days: float) -> None:
    st.subheader("수요 추이 · 간단 예측")
    st.caption(
        "주간 이력 2주 이상이면 **다음주 예측 = 최근주 + 주간 변화량 평균** · "
        "마스터/영림원 기간 1건이면 **주·월 평균**만 표시(추이 없음)"
    )

    sample_df = pd.DataFrame(weekly_sales_to_dataframe_rows(build_sample_weekly_sales()))
    master_sales = sales_from_sku_masters(skus)
    if st.session_state.get("imported_sales"):
        st.success(
            f"출고·수요 데이터 {len(st.session_state.imported_sales)}건 사용 "
            "(⑦ 마스터 편집·ERP 연동과 연동됨)"
        )
    elif master_sales:
        st.success(
            f"⑦ 마스터 편집 일평균출고 {len(master_sales)}건을 주간 수요로 환산해 사용합니다."
        )

    st.download_button(
        "샘플 주간 출고 CSV (기본 형식)",
        sample_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="weekly_sales_sample.csv",
        mime="text/csv",
    )

    uploaded = None
    preset = st.session_state.get("forecast_preset", "erp_korean")
    with st.expander("주간 출고 CSV 추가 업로드 (선택)", expanded=False):
        st.caption("별도 주간 이력 CSV가 있을 때만 사용하세요. 없으면 마스터·ERP 데이터를 자동 사용합니다.")
        uploaded = st.file_uploader("주간 출고 CSV", type=["csv"], key="forecast_upload")
        preset = st.radio(
            "CSV 형식",
            options=list(PRESET_LABELS.keys()),
            format_func=lambda k: PRESET_LABELS[k],
            horizontal=True,
            key="forecast_preset",
        )

    sales: list[WeeklySales] | None = None
    frame: pd.DataFrame
    load_warnings: list[str] = []

    if uploaded:
        try:
            raw = read_uploaded_table(uploaded)
        except Exception as exc:
            st.error(f"파일을 읽을 수 없습니다: {exc}")
            return
        use_korean = preset == "erp_korean" or is_korean_sales_frame(raw)
        if use_korean and preset == "erp_korean" and is_korean_sales_frame(raw):
            sales, report = parse_sales_csv(raw, preset="erp_korean")
        else:
            if preset != "erp_korean" and is_korean_sales_frame(raw):
                st.info("한글 컬럼(품목코드·주간시작일·출고수량)이 감지되어 ERP 한글 형식으로 읽습니다.")
            sales, report = parse_sales_upload(raw, preset=preset)
        if not report.ok:
            st.error("; ".join(report.messages))
            return
        load_warnings = report.warnings
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
        format_func=lambda sid: f"{sid} — {names.get(sid, sid)}",
    )
    sku_sales = frame[frame["sku_id"] == pick].sort_values("week_start")
    if not sku_sales.empty:
        chart = sku_sales.set_index("week_start")[["qty"]]
        st.line_chart(chart)


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


def tab_expiry(skus: list[SkuMaster]) -> None:
    _render_expiry(skus)


@st.fragment
def _render_expiry(skus: list[SkuMaster]) -> None:
    st.subheader("유통기한 관리")
    st.caption("가장 빠른 LOT 유통기한 기준 — FEFO 출고 · 카테고리별 임박/주의 알림")

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

    alerts = build_expiry_alerts(skus, thresholds_by_category=thresholds)
    tracked = len(alerts)
    without_expiry = len(skus) - tracked
    counts = summarize_expiry_counts(alerts)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("⛔ 기한 경과", counts["expired"])
    c2.metric("🔴 임박", counts["critical"])
    c3.metric("🟡 주의", counts["warning"])
    c4.metric("🟢 양호", counts["ok"])
    c5.metric("미등록 SKU", without_expiry)

    if not alerts:
        st.info("유통기한이 등록된 SKU가 없습니다. **⑦ 마스터 편집** 또는 ERP CSV에서 `유통기한` 컬럼을 입력하세요.")
        return

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
                "임박 기준": int(alert.critical_threshold_days),
                "주의 기준": int(alert.warning_threshold_days),
                "임박재고": round(alert.expiring_qty, 0),
                "현재고": alert.on_hand,
                "권장 조치": alert.action,
                "거래처": alert.vendor,
            }
        )
    st.markdown("**FEFO 우선순위 (잔여일 짧은 순)**")
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "잔여일": st.column_config.NumberColumn(format="%d"),
            "임박재고": st.column_config.NumberColumn(format="%.0f"),
            "현재고": st.column_config.NumberColumn(format="%.0f"),
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


def _render_active_tab(active_tab: str, skus: list[SkuMaster], target_days: float) -> None:
    if active_tab == TAB_OPTIONS[0]:
        tab_stockout_board(skus, target_days)
    elif active_tab == TAB_OPTIONS[1]:
        tab_reorder(skus, target_days)
    elif active_tab == TAB_OPTIONS[2]:
        tab_promo(skus)
    elif active_tab == TAB_OPTIONS[3]:
        tab_forecast(skus, target_days)
    elif active_tab == TAB_OPTIONS[4]:
        tab_erp_import(skus)
    elif active_tab == TAB_OPTIONS[5]:
        tab_expiry(skus)
    elif active_tab == TAB_OPTIONS[6]:
        tab_master_edit(_sku_list())


def main() -> None:
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
        "결품 위험 · MOQ/리드타임 발주 · 프로모션 · 수요 예측 · 유통기한 · 마스터 편집"
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
        "Python/Streamlit 개발 (AI 보조 워크플로)"
    )


if __name__ == "__main__":
    main()
