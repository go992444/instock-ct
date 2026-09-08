"""Streamlit helpers for browser localStorage persistence."""

from __future__ import annotations

import json
import logging

import streamlit as st
import streamlit.components.v1 as components

from instock_ct.browser_storage import BROWSER_STORAGE_KEY, parse_snapshot, snapshot_to_json
from instock_ct.models import SkuMaster, WeeklySales

logger = logging.getLogger(__name__)

_LOAD_KEY = "instock_browser_storage_load"
_MAX_STORAGE_WAIT = 5

try:
    from streamlit_javascript import st_javascript as _st_javascript
except ImportError:  # pragma: no cover
    _st_javascript = None


def browser_persist_available() -> bool:
    return _st_javascript is not None


def ensure_browser_storage_restored() -> None:
    """Load SKU master from localStorage once per session (same browser)."""
    if st.session_state.get("_browser_storage_ready"):
        return

    if _st_javascript is None:
        st.session_state._browser_storage_ready = True
        return

    try:
        stored = _st_javascript(
            f"localStorage.getItem({json.dumps(BROWSER_STORAGE_KEY)})",
            key=_LOAD_KEY,
            default="",
        )
    except Exception as exc:  # pragma: no cover - component/runtime failures
        logger.warning("browser storage load failed: %s", exc)
        st.session_state._browser_storage_ready = True
        st.session_state._browser_storage_unavailable = True
        return

    if stored in (None, ""):
        waits = st.session_state.get("_storage_wait", 0) + 1
        st.session_state._storage_wait = waits
        if waits >= _MAX_STORAGE_WAIT:
            st.session_state._browser_storage_ready = True
        return

    st.session_state._browser_storage_ready = True
    if stored == "null":
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
    if not browser_persist_available():
        return
    skus: list[SkuMaster] = st.session_state.get("skus", [])
    if not skus:
        return
    imported_sales: list[WeeklySales] | None = st.session_state.get("imported_sales")
    payload = snapshot_to_json(skus, imported_sales)
    try:
        components.html(
            f"""
            <script>
            localStorage.setItem({json.dumps(BROWSER_STORAGE_KEY)}, {json.dumps(payload)});
            </script>
            """,
            height=0,
            width=0,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("browser storage save failed: %s", exc)


def clear_browser_storage() -> None:
    if not browser_persist_available():
        return
    try:
        components.html(
            f"""
            <script>
            localStorage.removeItem({json.dumps(BROWSER_STORAGE_KEY)});
            </script>
            """,
            height=0,
            width=0,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("browser storage clear failed: %s", exc)
