"""Streamlit helpers for browser localStorage persistence."""

from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components
from streamlit_javascript import st_javascript

from instock_ct.browser_storage import BROWSER_STORAGE_KEY, parse_snapshot, snapshot_to_json
from instock_ct.models import SkuMaster, WeeklySales

_LOAD_KEY = "instock_browser_storage_load"


def ensure_browser_storage_restored() -> None:
    """Load SKU master from localStorage once per session (same browser)."""
    if st.session_state.get("_browser_storage_ready"):
        return

    stored = st_javascript(
        f"localStorage.getItem({json.dumps(BROWSER_STORAGE_KEY)})",
        key=_LOAD_KEY,
    )
    if stored is None:
        st.caption("저장된 데이터 확인 중…")
        st.stop()

    st.session_state._browser_storage_ready = True
    if stored in ("", "null"):
        return

    try:
        skus, imported_sales = parse_snapshot(stored)
    except (json.JSONDecodeError, ValueError, KeyError, TypeError):
        st.session_state._browser_storage_corrupt = True
        return

    st.session_state.skus = skus
    st.session_state.imported_sales = imported_sales
    st.session_state._browser_storage_restored = True


def persist_browser_storage() -> None:
    skus: list[SkuMaster] = st.session_state.get("skus", [])
    if not skus:
        return
    imported_sales: list[WeeklySales] | None = st.session_state.get("imported_sales")
    payload = snapshot_to_json(skus, imported_sales)
    components.html(
        f"""
        <script>
        localStorage.setItem({json.dumps(BROWSER_STORAGE_KEY)}, {json.dumps(payload)});
        </script>
        """,
        height=0,
        width=0,
    )


def clear_browser_storage() -> None:
    components.html(
        f"""
        <script>
        localStorage.removeItem({json.dumps(BROWSER_STORAGE_KEY)});
        </script>
        """,
        height=0,
        width=0,
    )
