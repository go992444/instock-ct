# Instock CT

의료 B2B 클리닉몰(폐쇄몰) **재고관리·발주** 업무를 가정한 **포트폴리오 시범**입니다.  
SCM 인스탁(재고) 매니저 채용용 — 결품 위험, MOQ·리드타임 발주, 긴급 프로모션 영향 분석, ERP CSV 연동.

> 모든 SKU·단가·수요 데이터는 **가상(Fictional Medi Market)** 입니다.

---

## 데모 (로컬)

```powershell
cd instock_ct
pip install -r requirements.txt
streamlit run app.py
```

또는 repo root:

```powershell
pip install -r requirements-instock.txt
streamlit run streamlit_app.py
```

---

## Streamlit Cloud 배포

1. GitHub에 `instock_ct/` + `streamlit_app.py` + `requirements-instock.txt` push
2. [share.streamlit.io](https://share.streamlit.io/) → **New app**
3. 설정:
   - **Repository:** `go992444/betman-toto-analyzer` (본인 repo)
   - **Branch:** `master`
   - **Main file path:** `streamlit_app.py`
   - **Requirements file:** `requirements-instock.txt`
4. **Deploy** → URL을 이력서·지원서에 기재

배포 URL 예시: `https://instock-ct-xxxx.streamlit.app`

---

## 기능 (5탭)

| 탭 | 설명 |
|----|------|
| ① 결품 위험 | SKU별 재고일수, 🔴🟡🟢, 권장 발주량 |
| ② 발주 추천 | MOQ·리드타임·안전재고, **ERP 발주안 CSV** 다운로드 |
| ③ 프로모션 영향 | 수요 +N% 시 결품·추가 발주량 |
| ④ 수요 예측 | 주간 출고 CSV → 이동평균 예측 → 발주 연동 |
| ⑤ ERP 연동 | 한글 ERP 내보내기 CSV 가져오기 (재고·출고) |
| ⑥ 마스터 편집 | 표에서 현재고·출고·MOQ 등 직접 수정·저장 |

---

## ERP CSV 형식

### 재고 내보내기 (가져오기)

```text
품목코드,품명,카테고리,현재고,일평균출고,리드타임일,MOQ,거래처명,안전재고일
```

샘플: [`samples/erp_inventory_export.sample.csv`](samples/erp_inventory_export.sample.csv)

### 주간 출고 내보내기 (가져오기)

```text
품목코드,주간시작일,출고수량
```

샘플: [`samples/erp_weekly_shipment.sample.csv`](samples/erp_weekly_shipment.sample.csv)

### 발주안 내보내기 (②번 탭 → download)

```text
품목코드,품명,권장발주수량,MOQ,리드타임일,거래처명,비고
```

---

## 면접 데모 순서 (5분)

1. **① 결품 위험** — 임박 SKU → 영업·물류팀 공유
2. **③ 프로모션 +30%** — 선발주 필요 SKU
3. **⑤ ERP 연동** — 샘플 CSV 업로드 → 마스터 반영
4. **② 발주 추천** — MOQ 조건 변경 + **발주안 CSV** 다운로드
5. **④ 수요 예측** — ERP 출고 이력 기반 예측 발주

---

## 이력서·지원서용 한 줄

> 의료 B2B 이커머스 Instock CT 시범(Python/Streamlit) — 결품 위험 대시보드, MOQ·리드타임 발주, 프로모션 영향 분석, ERP CSV 연동. 기존 현장 **재고 선제 알림·출고 전산화** 경험을 SCM 발주 관점으로 확장.

---

## 기술 스택

- Python 3.11+, pandas, Streamlit
- 단위 테스트 8건 (`test_inventory_engine`, `test_erp_import`)
- 개발: AI 보조 워크플로 (Cursor / Claude)

---

## 스크린샷

| 화면 | 파일 |
|------|------|
| 결품 위험 | [`docs/screenshots/01_stockout.png`](docs/screenshots/01_stockout.png) |
| 발주 추천 | [`docs/screenshots/02_reorder.png`](docs/screenshots/02_reorder.png) |
| 프로모션 영향 | [`docs/screenshots/03_promo.png`](docs/screenshots/03_promo.png) |
| ERP 연동 | [`docs/screenshots/04_erp.png`](docs/screenshots/04_erp.png) |

---

## 프로젝트 구조

```text
instock_ct/
  app.py                 # Streamlit UI
  inventory_engine.py    # 재고일수, 발주, 프로모션, 예측
  erp_import.py          # ERP 한글 CSV 매핑
  config.py              # 샘플 SKU (37개)
  samples/               # ERP CSV 샘플
  test_*.py
streamlit_app.py         # Cloud entrypoint
requirements-instock.txt
```

---

## 테스트

```powershell
python -m unittest instock_ct.test_inventory_engine instock_ct.test_erp_import -v
```
