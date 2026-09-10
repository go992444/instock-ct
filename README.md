# Instock CT

의료 B2B 클리닉몰(폐쇄몰) **재고관리·발주** 포트폴리오 시범 (Python/Streamlit).

> 모든 SKU·수요 데이터는 **가상(Fictional Medi Market)** 입니다. API 키·외부 연동 없음.

---

## 로컬 실행

```powershell
pip install -r requirements.txt
streamlit run streamlit_app.py
```

---

## Streamlit Cloud 배포

1. [share.streamlit.io](https://share.streamlit.io/) → **New app**
2. Repository: **`go992444/instock-ct`** (public)
3. Main file: **`streamlit_app.py`**
4. Requirements: **`requirements.txt`**
5. App URL (선택): `instock-ct`

---

## 기능 (3탭)

| 탭 | 설명 |
|----|------|
| ① 재고·발주·유통기한 | 결품·발주·유통기한 통합 SKU 표, 저회전·LOT·FEFO·발주 CSV |
| ② 수요·프로모션 | 주간 출고 예측, 긴급 프로모션 결품·추가 발주 영향 |
| ③ 데이터 연동 | ERP·WMS 가져오기, 마스터 표 편집 |

---

## 테스트

```powershell
python -m unittest instock_ct.test_inventory_engine instock_ct.test_erp_import instock_ct.test_expiry_engine -v
```

---

## 이력서 한 줄

> 의료 B2B Instock CT(Python/Streamlit) — 결품 위험, MOQ·리드타임 발주, 프로모션 영향, 유통기한(FEFO), ERP CSV 연동, 마스터 편집.
