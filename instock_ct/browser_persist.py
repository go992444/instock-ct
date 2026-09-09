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
_PENDING = "__INSTOCK_PENDING__"
_NULL = "__INSTOCK_NULL__"
_ERROR = "__INSTOCK_ERROR__"

try:
    from streamlit_javascript import st_javascript as _st_javascript
except ImportError:  # pragma: no cover
    _st_javascript = None


def _root_local_storage_js() -> str:
    """Return JS expression for the top-level window localStorage."""
    return (
        "(function(){"
        "var root=window;"
        "while(root.parent&&root.parent!==root){root=root.parent;}"
        "return root.localStorage;"
        "})()"
    )


def _read_storage_js() -> str:
    key = json.dumps(BROWSER_STORAGE_KEY)
    return (
        "(function(){"
        "try{"
        f"var store={_root_local_storage_js()};"
        f"var value=store.getItem({key});"
        f"if(value===null)return {json.dumps(_NULL)};"
        "return value;"
        "}catch(e){"
        f"return {json.dumps(_ERROR)};"
        "}"
        "})()"
    )


def _write_storage_js(payload: str) -> str:
    key = json.dumps(BROWSER_STORAGE_KEY)
    encoded_payload = json.dumps(payload)
    return (
        "(function(){"
        "try{"
        f"var store={_root_local_storage_js()};"
        f"store.setItem({key},{encoded_payload});"
        'return "ok";'
        "}catch(e){"
        'return "error";'
        "}"
        "})()"
    )


def _clear_storage_js() -> str:
    key = json.dumps(BROWSER_STORAGE_KEY)
    return (
        "(function(){"
        "try{"
        f"var store={_root_local_storage_js()};"
        f"store.removeItem({key});"
        'return "ok";'
        "}catch(e){"
        'return "error";'
        "}"
        "})()"
    )


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
            _read_storage_js(),
            key=_LOAD_KEY,
            default=_PENDING,
        )
    except Exception as exc:  # pragma: no cover - component/runtime failures
        logger.warning("browser storage load failed: %s", exc)
        st.session_state._browser_storage_ready = True
        st.session_state._browser_storage_unavailable = True
        return

    if stored == _PENDING:
        st.caption("저장된 데이터 불러오는 중…")
        st.stop()

    st.session_state._browser_storage_ready = True

    if stored == _ERROR:
        st.session_state._browser_storage_unavailable = True
        return

    if stored in (_NULL, "", "null"):
        return

    try:
        skus, imported_sales = parse_snapshot(str(stored))
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
    try:
        components.html(
            f"<script>{_write_storage_js(payload)}</script>",
            height=0,
            width=0,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("browser storage save failed: %s", exc)


def clear_browser_storage() -> None:
    try:
        components.html(
            f"<script>{_clear_storage_js()}</script>",
            height=0,
            width=0,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("browser storage clear failed: %s", exc)
