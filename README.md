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

## 기능 (6탭)

| 탭 | 설명 |
|----|------|
| ① 결품 위험 | 재고일수, 🔴🟡🟢, 권장 발주량 |
| ② 발주 추천 | MOQ·리드타임·안전재고, ERP 발주안 CSV |
| ③ 프로모션 영향 | 수요 +N% 시 결품·추가 발주 |
| ④ 수요 예측 | 주간 출고 CSV → 이동평균 예측 |
| ⑤ ERP 연동 | 한글 ERP CSV 가져오기 |
| ⑥ 마스터 편집 | 표에서 재고·품목 직접 수정 |

---

## 테스트

```powershell
python -m unittest instock_ct.test_inventory_engine instock_ct.test_erp_import -v
```

---

## 이력서 한 줄

> 의료 B2B Instock CT(Python/Streamlit) — 결품 위험, MOQ·리드타임 발주, 프로모션 영향, ERP CSV 연동, 마스터 편집.
