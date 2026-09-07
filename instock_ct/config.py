"""Sample Medi Market SKU catalog (fictional demo data)."""

from __future__ import annotations

from instock_ct.models import SkuMaster

CATEGORIES: dict[str, str] = {
    "medical_consumable": "의료기기 소모품",
    "pb": "PB",
    "herbal": "한약재",
    "general": "일반 소모품",
    "medical_equipment": "의료기기",
}

# Category mix mirrors Integration posting (reference)
CATEGORY_SHARE: dict[str, float] = {
    "medical_consumable": 0.43,
    "pb": 0.23,
    "herbal": 0.15,
    "general": 0.13,
    "medical_equipment": 0.04,
}

RISK_CRITICAL_DOS = 5.0
RISK_WARNING_DOS = 14.0
DEFAULT_TARGET_COVERAGE_DAYS = 21.0
EXPIRY_CRITICAL_DAYS = 30.0
EXPIRY_WARNING_DAYS = 90.0
LOW_TURNOVER_THRESHOLD = 4.0

# 연간 회전(회/년) 미만이면 저회전 — 카테고리별 기준
DEFAULT_TURNOVER_THRESHOLDS_BY_CATEGORY: dict[str, float] = {
    "medical_consumable": 6.0,
    "pb": 4.0,
    "herbal": 3.0,
    "general": 4.0,
    "medical_equipment": 2.0,
}

# (임박 일수, 주의 일수) — 카테고리별 유통기한 알림 기준
DEFAULT_EXPIRY_THRESHOLDS_BY_CATEGORY: dict[str, tuple[float, float]] = {
    "medical_consumable": (30.0, 90.0),
    "pb": (45.0, 120.0),
    "herbal": (60.0, 180.0),
    "general": (30.0, 90.0),
    "medical_equipment": (90.0, 365.0),
}

_BASE_SKUS: tuple[SkuMaster, ...] = (
    SkuMaster("MC-001", "일회용 주사기 5ml (박스)", "medical_consumable", "의료기기 소모품", 820, 95, 5, 200, "메디서플라이", 5),
    SkuMaster("MC-002", "니트릴 장갑 M (100매)", "medical_consumable", "의료기기 소모품", 420, 78, 4, 100, "메디서플라이", 5),
    SkuMaster("MC-003", "알코올 스왑 (200매)", "medical_consumable", "의료기기 소모품", 150, 62, 3, 80, "케어링크", 4),
    SkuMaster("MC-004", "거즈 10x10 (50p)", "medical_consumable", "의료기기 소모품", 980, 45, 5, 150, "메디서플라이", 7),
    SkuMaster("MC-005", "IV 카테터 24G", "medical_consumable", "의료기기 소모품", 60, 28, 7, 50, "한국메디텍", 6),
    SkuMaster("MC-006", "멸균 시트 M", "medical_consumable", "의료기기 소모품", 310, 35, 4, 60, "케어링크", 5),
    SkuMaster("MC-007", "마스크 KF94 (50매)", "medical_consumable", "의료기기 소모품", 540, 88, 3, 100, "메디서플라이", 4),
    SkuMaster("MC-008", "일회용 앞치마", "medical_consumable", "의료기기 소모품", 90, 22, 5, 40, "케어링크", 5),
    SkuMaster("MC-009", "검체컵 500ml", "medical_consumable", "의료기기 소모품", 200, 18, 6, 30, "한국메디텍", 7),
    SkuMaster("MC-010", "혈압커프 일회용", "medical_consumable", "의료기기 소모품", 45, 15, 8, 25, "한국메디텍", 6),
    SkuMaster("MC-011", "봉합사 3-0", "medical_consumable", "의료기기 소모품", 120, 12, 10, 20, "서울메디", 7),
    SkuMaster("MC-012", "마이크로포어 테이프", "medical_consumable", "의료기기 소모품", 380, 40, 4, 80, "메디서플라이", 5),
    SkuMaster("MC-013", "전극 패드", "medical_consumable", "의료기기 소모품", 25, 14, 7, 20, "서울메디", 5),
    SkuMaster("MC-014", "카테터 고정패드", "medical_consumable", "의료기기 소모품", 170, 26, 5, 40, "케어링크", 5),
    SkuMaster("MC-015", "폼 드레싱 10x10", "medical_consumable", "의료기기 소모품", 55, 19, 6, 30, "한국메디텍", 6),
    SkuMaster("MC-016", "주사기 10ml", "medical_consumable", "의료기기 소모품", 640, 52, 5, 120, "메디서플라이", 5),
    SkuMaster("MC-017", "손소독제 500ml", "medical_consumable", "의료기기 소모품", 280, 48, 3, 60, "메디서플라이", 4),
    SkuMaster("PB-001", "PB 한방 패치 A", "pb", "PB", 190, 32, 7, 50, "PB파트너", 7),
    SkuMaster("PB-002", "PB 클리닉 타월", "pb", "PB", 410, 55, 5, 100, "PB파트너", 5),
    SkuMaster("PB-003", "PB 온열팩", "pb", "PB", 85, 24, 8, 40, "PB파트너", 6),
    SkuMaster("PB-004", "PB 침구 가이드", "pb", "PB", 130, 18, 10, 30, "PB파트너", 7),
    SkuMaster("PB-005", "PB 오일 500ml", "pb", "PB", 220, 28, 6, 40, "PB파트너", 6),
    SkuMaster("PB-006", "PB 프리미엄 뜸", "pb", "PB", 95, 20, 9, 25, "PB파트너", 7),
    SkuMaster("PB-007", "PB 부항 세트", "pb", "PB", 160, 15, 12, 20, "PB파트너", 8),
    SkuMaster("PB-008", "PB 라이너 시트", "pb", "PB", 300, 38, 5, 60, "PB파트너", 5),
    SkuMaster("PB-009", "PB 족욕 소금", "pb", "PB", 70, 12, 8, 20, "PB파트너", 6),
    SkuMaster("HB-001", "한약재 A (1kg)", "herbal", "한약재", 140, 22, 14, 20, "한약재센터", 10),
    SkuMaster("HB-002", "한약재 B (1kg)", "herbal", "한약재", 80, 16, 14, 15, "한약재센터", 10),
    SkuMaster("HB-003", "한약재 C (500g)", "herbal", "한약재", 200, 14, 12, 15, "한약재센터", 10),
    SkuMaster("HB-004", "한약재 D (1kg)", "herbal", "한약재", 55, 11, 15, 10, "한약재센터", 12),
    SkuMaster("HB-005", "한약재 E (500g)", "herbal", "한약재", 110, 9, 14, 10, "한약재센터", 10),
    SkuMaster("HB-006", "한약재 F (1kg)", "herbal", "한약재", 35, 8, 16, 10, "한약재센터", 12),
    SkuMaster("GN-001", "클리닉 티슈 (10p)", "general", "일반 소모품", 520, 42, 3, 80, "오피스케어", 4),
    SkuMaster("GN-002", "A4 복사용지", "general", "일반 소모품", 180, 25, 4, 50, "오피스케어", 5),
    SkuMaster("GN-003", "청소용 알코올 4L", "general", "일반 소모품", 90, 18, 5, 30, "오피스케어", 5),
    SkuMaster("GN-004", "쓰레기봉투 L", "general", "일반 소모품", 240, 20, 3, 40, "오피스케어", 4),
    SkuMaster("GN-005", "라벨 프린터 리본", "general", "일반 소모품", 15, 6, 10, 10, "오피스케어", 7),
    SkuMaster("EQ-001", "휴대용 혈압계", "medical_equipment", "의료기기", 18, 2.5, 21, 5, "EQ월드", 14),
    SkuMaster("EQ-002", "적외선 온열기", "medical_equipment", "의료기기", 8, 1.2, 28, 3, "EQ월드", 14),
)

# Demo expiry dates (기준: 2026년, 의료·PB·한약재 위주)
_EXPIRY_BY_SKU: dict[str, tuple[str, float | None]] = {
    "MC-003": ("2026-08-25", 150),
    "MC-005": ("2026-10-15", 60),
    "MC-007": ("2026-09-25", 540),
    "MC-008": ("2026-09-18", 90),
    "MC-013": ("2026-09-08", 25),
    "MC-015": ("2026-11-20", 55),
    "MC-017": ("2026-12-01", 280),
    "PB-003": ("2026-11-30", 85),
    "PB-006": ("2026-09-12", 95),
    "HB-004": ("2026-08-30", 55),
    "HB-006": ("2026-09-05", 35),
}


def _apply_demo_expiry(skus: tuple[SkuMaster, ...]) -> tuple[SkuMaster, ...]:
    from dataclasses import replace

    updated: list[SkuMaster] = []
    for sku in skus:
        expiry = _EXPIRY_BY_SKU.get(sku.sku_id)
        if expiry:
            updated.append(
                replace(
                    sku,
                    nearest_expiry=expiry[0],
                    expiring_qty=expiry[1],
                )
            )
        else:
            updated.append(sku)
    return tuple(updated)


DEFAULT_SKUS: tuple[SkuMaster, ...] = _apply_demo_expiry(_BASE_SKUS)
