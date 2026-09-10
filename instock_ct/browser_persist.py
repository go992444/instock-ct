"""Streamlit helpers for browser localStorage persistence."""

from __future__ import annotations

import json
import logging

import streamlit as st

from instock_ct.browser_storage import BROWSER_STORAGE_KEY, parse_snapshot, snapshot_to_json
from instock_ct.models import SkuMaster, WeeklySales

logger = logging.getLogger(__name__)

_LOAD_KEY = "instock_browser_storage_load"
_WRITE_KEY = "instock_browser_storage_write"
_CLEAR_KEY = "instock_browser_storage_clear"
_PENDING = "__INSTOCK_PENDING__"
_NULL = "__INSTOCK_NULL__"
_ERROR = "__INSTOCK_ERROR__"

try:
    from streamlit_javascript import st_javascript as _st_javascript
except ImportError:  # pragma: no cover
    _st_javascript = None


def _read_storage_js() -> str:
    key = json.dumps(BROWSER_STORAGE_KEY)
    return (
        "(function(){"
        "try{"
        f"var value=localStorage.getItem({key});"
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
        f"localStorage.setItem({key},{encoded_payload});"
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
        f"localStorage.removeItem({key});"
        'return "ok";'
        "}catch(e){"
        'return "error";'
        "}"
        "})()"
    )


def browser_persist_available() -> bool:
    return _st_javascript is not None


def queue_browser_save(skus: list[SkuMaster], imported_sales: list[WeeklySales] | None) -> None:
    st.session_state._browser_save_payload = snapshot_to_json(skus, imported_sales)


def flush_browser_save_if_pending() -> None:
    payload = st.session_state.get("_browser_save_payload")
    if not payload or _st_javascript is None:
        return
    try:
        result = _st_javascript(
            _write_storage_js(str(payload)),
            key=_WRITE_KEY,
            default=_PENDING,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("browser storage flush failed: %s", exc)
        return
    if result == _PENDING:
        st.caption("브라우저에 저장하는 중…")
        st.stop()
    if result == "ok":
        st.session_state.pop("_browser_save_payload", None)


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

    if stored in (_NULL, "", "null", None):
        return

    try:
        skus, imported_sales = parse_snapshot(str(stored))
    except (json.JSONDecodeError, ValueError, KeyError, TypeError):
        st.session_state._browser_storage_corrupt = True
        return

    st.session_state.skus = skus
    st.session_state.imported_sales = imported_sales
    st.session_state._browser_storage_restored = True


def persist_browser_storage() -> bool:
    payload = st.session_state.get("_browser_save_payload")
    if not payload or _st_javascript is None:
        skus: list[SkuMaster] = st.session_state.get("skus", [])
        if not skus:
            return False
        imported_sales: list[WeeklySales] | None = st.session_state.get("imported_sales")
        queue_browser_save(skus, imported_sales)
        payload = st.session_state.get("_browser_save_payload")
    if not payload:
        return False
    try:
        result = _st_javascript(
            _write_storage_js(str(payload)),
            key=_WRITE_KEY,
            default=_PENDING,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("browser storage save failed: %s", exc)
        return False
    if result == "ok":
        st.session_state.pop("_browser_save_payload", None)
        return True
    return False


def clear_browser_storage() -> None:
    st.session_state.pop("_browser_save_payload", None)
    if _st_javascript is None:
        return
    try:
        _st_javascript(_clear_storage_js(), key=_CLEAR_KEY)
    except Exception as exc:  # pragma: no cover
        logger.warning("browser storage clear failed: %s", exc)
