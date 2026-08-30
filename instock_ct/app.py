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
)
from instock_ct.inventory_engine import (  # noqa: E402
    assess_stockout_risk,
    build_reorder_plan,
    forecast_from_weekly_sales,
    recommended_reorder_qty,
    risk_label,
    simulate_promo_impact,
    summarize_risk_counts,
)
from instock_ct.models import SkuMaster, WeeklySales  # noqa: E402
from instock_ct.erp_import import (  # noqa: E402
    PRESET_LABELS,
    build_reorder_export_frame,
    build_sample_erp_sku_csv_bytes,
    parse_sales_csv,
    parse_sku_csv,
    skus_to_erp_export_frame,
)
from instock_ct.sample_sales import build_sample_weekly_sales, weekly_sales_to_dataframe_rows  # noqa: E402

_SAMPLES_DIR = _APP_DIR / "samples"

st.set_page_config(page_title="Instock CT", page_icon="📊", layout="wide")

RISK_COLORS = {
    "critical": "🔴",
    "warning": "🟡",
    "ok": "🟢",
}


def _init_state() -> None:
    if "skus" not in st.session_state:
        st.session_state.skus = [copy.deepcopy(s) for s in DEFAULT_SKUS]
    if "imported_sales" not in st.session_state:
        st.session_state.imported_sales = None


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
    st.sidebar.caption("📌 **⑥ 마스터 편집** — 재고·품목 표에서 직접 수정")
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
    if st.sidebar.button("샘플 SKU 초기화", width="stretch"):
        st.session_state.skus = [copy.deepcopy(s) for s in DEFAULT_SKUS]
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


_CATEGORY_LABEL_TO_CODE = {label: code for code, label in CATEGORIES.items()}


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
            }
            for s in skus
        ]
    )


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

        if not category_label or category_label not in _CATEGORY_LABEL_TO_CODE:
            errors.append(f"{row_no}행 ({sku_id}): 카테고리를 목록에서 선택하세요.")
            continue

        try:
            on_hand = float(row.get("현재고", 0))
            avg_daily = float(row.get("일평균출고", 0))
            lead_time = int(row.get("리드타임일", 1))
            moq = int(row.get("MOQ", 1))
            safety_days = float(row.get("안전재고일", 7))
        except (TypeError, ValueError):
            errors.append(f"{row_no}행 ({sku_id}): 숫자 형식이 올바르지 않습니다.")
            continue

        if on_hand < 0 or avg_daily < 0 or lead_time < 1 or moq < 1 or safety_days < 0:
            errors.append(f"{row_no}행 ({sku_id}): 음수 또는 최소값 미만입니다.")
            continue

        skus.append(
            SkuMaster(
                sku_id=sku_id,
                name=name,
                category=_CATEGORY_LABEL_TO_CODE[category_label],
                category_label=category_label,
                on_hand=on_hand,
                avg_daily_demand=avg_daily,
                lead_time_days=lead_time,
                moq=moq,
                vendor=str(row.get("거래처명", "")).strip() or "-",
                safety_stock_days=safety_days,
            )
        )

    if errors:
        return None, errors
    if not skus:
        return None, ["저장할 SKU가 없습니다."]
    return skus, []


def tab_master_edit(skus: list[SkuMaster]) -> None:
    st.subheader("재고·품목 마스터 편집")
    st.caption("표에서 값을 수정한 뒤 **변경사항 저장** — 다른 탭에 즉시 반영됩니다. 행 추가·삭제도 가능합니다.")

    category_options = list(CATEGORIES.values())
    edited = st.data_editor(
        _skus_to_edit_frame(skus),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "품목코드": st.column_config.TextColumn("품목코드", required=True, width="small"),
            "품명": st.column_config.TextColumn("품명", required=True, width="medium"),
            "카테고리": st.column_config.SelectboxColumn(
                "카테고리",
                options=category_options,
                required=True,
                width="medium",
            ),
            "현재고": st.column_config.NumberColumn("현재고", min_value=0, step=1, format="%.0f"),
            "일평균출고": st.column_config.NumberColumn("일평균출고", min_value=0, step=0.1, format="%.1f"),
            "리드타임일": st.column_config.NumberColumn("리드타임(일)", min_value=1, step=1),
            "MOQ": st.column_config.NumberColumn("MOQ", min_value=1, step=1),
            "거래처명": st.column_config.TextColumn("거래처명", width="small"),
            "안전재고일": st.column_config.NumberColumn("안전재고(일)", min_value=0, step=1),
        },
        key="master_editor",
    )

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        save = st.button("변경사항 저장", type="primary", width="stretch")
    with c2:
        st.download_button(
            "ERP 형식 CSV 다운로드",
            skus_to_erp_export_frame(skus).to_csv(index=False).encode("utf-8-sig"),
            file_name="erp_inventory_export.csv",
            mime="text/csv",
            width="stretch",
        )
    with c3:
        st.info("Tip: ERP 연동 탭 CSV 업로드와 동일한 컬럼 형식입니다.")

    if save:
        parsed, errors = _parse_edit_frame(edited)
        if errors:
            for msg in errors[:8]:
                st.error(msg)
            if len(errors) > 8:
                st.error(f"외 {len(errors) - 8}건 오류")
        else:
            st.session_state.skus = parsed
            st.success(f"SKU {len(parsed)}건 저장되었습니다.")
            st.rerun()


def tab_stockout_board(skus: list[SkuMaster], target_days: float) -> None:
    st.subheader("결품 위험 현황")
    risks = [assess_stockout_risk(s) for s in skus]
    counts = summarize_risk_counts(risks)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔴 결품 임박", counts["critical"])
    c2.metric("🟡 주의", counts["warning"])
    c3.metric("🟢 양호", counts["ok"])
    c4.metric("SKU 수", len(skus))

    rows = []
    for row in sorted(risks, key=lambda item: item.days_of_supply):
        rows.append(
            {
                "위험": f"{RISK_COLORS[row.risk_level]} {risk_label(row.risk_level)}",
                "SKU": row.sku_id,
                "품명": row.name,
                "카테고리": row.category_label,
                "현재고": row.on_hand,
                "일평균 출고": round(row.avg_daily_demand, 1),
                "재고일수": round(row.days_of_supply, 1),
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
        },
    )

    critical = [r for r in risks if r.risk_level == "critical"]
    if critical:
        st.warning(
            f"결품 임박 SKU {len(critical)}건 — 영업·물류팀 공유 필요: "
            + ", ".join(r.sku_id for r in critical[:8])
            + (" …" if len(critical) > 8 else "")
        )


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


def tab_erp_import() -> None:
    st.subheader("ERP·WMS 연동")
    st.caption("사내 ERP 내보내기 CSV → Instock CT · 발주안 CSV → ERP 재등록")

    preset = st.radio(
        "파일 형식",
        options=list(PRESET_LABELS.keys()),
        format_func=lambda k: PRESET_LABELS[k],
        horizontal=True,
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**① 재고·품목 정보 가져오기**")
        st.download_button(
            "ERP 재고 내보내기 샘플 CSV",
            build_sample_erp_sku_csv_bytes(),
            file_name="erp_inventory_export.sample.csv",
            mime="text/csv",
        )
        inv_file = st.file_uploader("재고 CSV", type=["csv"], key="erp_inv")
        if inv_file is not None:
            skus, report = parse_sku_csv(pd.read_csv(inv_file), preset=preset)
            if report.ok:
                st.session_state.skus = skus
                st.success("; ".join(report.messages))
                for w in report.warnings[:5]:
                    st.warning(w)
                st.dataframe(skus_to_erp_export_frame(skus).head(10), hide_index=True)
            else:
                st.error("; ".join(report.messages))

    with col_b:
        st.markdown("**② 주간 출고 데이터 가져오기**")
        sample_path = _SAMPLES_DIR / "erp_weekly_shipment.sample.csv"
        if sample_path.is_file():
            st.download_button(
                "ERP 출고 내보내기 샘플 CSV",
                sample_path.read_bytes(),
                file_name="erp_weekly_shipment.sample.csv",
                mime="text/csv",
            )
        ship_file = st.file_uploader("출고 CSV", type=["csv"], key="erp_ship")
        if ship_file is not None:
            sales, report = parse_sales_csv(pd.read_csv(ship_file), preset=preset)
            if report.ok:
                st.session_state.imported_sales = sales
                st.success("; ".join(report.messages))
                st.info("④ 수요 예측 탭에서 이 데이터를 사용합니다.")
            else:
                st.error("; ".join(report.messages))

    st.markdown("---")
    st.markdown("**ERP 한글 내보내기 필수 컬럼 (재고)**")
    st.code(
        "품목코드, 품명, 카테고리, 현재고, 일평균출고, 리드타임일, MOQ, 거래처명, 안전재고일",
        language="text",
    )
    st.markdown("**ERP 한글 내보내기 필수 컬럼 (출고)**")
    st.code("품목코드, 주간시작일, 출고수량", language="text")


def tab_forecast(skus: list[SkuMaster], target_days: float) -> None:
    st.subheader("수요 추이 · 간단 예측")
    st.caption("최근 N주 이동평균 기반 — 실무용 간이 예측 (딥러닝 아님)")

    sample_df = pd.DataFrame(weekly_sales_to_dataframe_rows(build_sample_weekly_sales()))
    if st.session_state.get("imported_sales"):
        st.success(f"ERP 연동 출고 이력 {len(st.session_state.imported_sales)}건 사용 가능")

    st.download_button(
        "샘플 주간 출고 CSV (기본 형식)",
        sample_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="weekly_sales_sample.csv",
        mime="text/csv",
    )

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

    if uploaded:
        raw = pd.read_csv(uploaded)
        if preset == "erp_korean":
            sales, report = parse_sales_csv(raw, preset=preset)
            if not report.ok:
                st.error("; ".join(report.messages))
                return
            frame = pd.DataFrame(
                [{"sku_id": s.sku_id, "week_start": s.week_start, "qty": s.qty} for s in sales]
            )
        else:
            frame = raw
    elif st.session_state.get("imported_sales"):
        sales = st.session_state.imported_sales
        frame = pd.DataFrame(
            [{"sku_id": s.sku_id, "week_start": s.week_start, "qty": s.qty} for s in sales]
        )
    else:
        frame = sample_df
        st.info("데모: 내장 샘플 12주 데이터 사용 중")

    frame.columns = [str(c).strip().lower() for c in frame.columns]
    required = {"sku_id", "week_start", "qty"}
    if not required.issubset(set(frame.columns)):
        st.error(f"CSV에 {required} 컬럼이 필요합니다.")
        return

    if sales is None:
        sales = [
            WeeklySales(
                sku_id=str(row["sku_id"]),
                week_start=str(row["week_start"]),
                qty=float(row["qty"]),
            )
            for _, row in frame.iterrows()
        ]
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
                "다음주 예측": round(item.forecast_next_week, 1),
                "환산 일출고": round(item.suggested_daily_demand, 2),
                "추세": item.trend,
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


def main() -> None:
    _init_state()
    target_days, categories = _render_sidebar()
    skus = _filter_skus(_sku_list(), categories)

    st.title("📊 Instock CT")
    st.caption(
        "의료 B2B 클리닉몰 · 재고관리 매니저용 시범 — "
        "결품 위험 · MOQ/리드타임 발주 · 프로모션 영향 · 수요 예측 · 마스터 편집"
    )

    t1, t2, t3, t4, t5, t6 = st.tabs(
        [
            "① 결품 위험",
            "② 발주 추천",
            "③ 프로모션 영향",
            "④ 수요 예측",
            "⑤ ERP 연동",
            "⑥ 마스터 편집",
        ]
    )
    with t1:
        tab_stockout_board(skus, target_days)
    with t2:
        tab_reorder(skus, target_days)
    with t3:
        tab_promo(skus)
    with t4:
        tab_forecast(skus, target_days)
    with t5:
        tab_erp_import()
    with t6:
        tab_master_edit(_sku_list())

    st.markdown("---")
    st.caption(
        "포트폴리오 시범 · 가상 Medi Market 데이터 · "
        "Python/Streamlit 개발 (AI 보조 워크플로)"
    )


if __name__ == "__main__":
    main()
