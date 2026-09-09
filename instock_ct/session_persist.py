"""Session persistence: server snapshot + browser localStorage."""

from __future__ import annotations

import uuid
from pathlib import Path

import streamlit as st

from instock_ct.browser_persist import (
    browser_persist_available,
    clear_browser_storage,
    ensure_browser_storage_restored,
    persist_browser_storage,
)
from instock_ct.browser_storage import parse_snapshot, snapshot_to_json
from instock_ct.config import DEFAULT_SKUS
from instock_ct.models import SkuMaster, WeeklySales

CLIENT_QUERY_PARAM = "cid"
PERSIST_DIR = Path(__file__).resolve().parent / ".persist"
_DEFAULT_SKU_IDS = frozenset(sku.sku_id for sku in DEFAULT_SKUS)


def is_demo_skus(skus: list[SkuMaster]) -> bool:
    if len(skus) != len(DEFAULT_SKUS):
        return False
    return frozenset(sku.sku_id for sku in skus) == _DEFAULT_SKU_IDS


def mark_persist_dirty() -> None:
    st.session_state._persist_dirty = True


def _persist_path(client_id: str) -> Path:
    safe_id = "".join(ch for ch in client_id if ch.isalnum() or ch in "-_")
    return PERSIST_DIR / f"{safe_id}.json"


def save_server_snapshot(
    client_id: str,
    skus: list[SkuMaster],
    imported_sales: list[WeeklySales] | None,
) -> None:
    PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    _persist_path(client_id).write_text(
        snapshot_to_json(skus, imported_sales),
        encoding="utf-8",
    )


def load_server_snapshot(
    client_id: str,
) -> tuple[list[SkuMaster], list[WeeklySales] | None] | None:
    path = _persist_path(client_id)
    if not path.is_file():
        return None
    try:
        return parse_snapshot(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def delete_server_snapshot(client_id: str) -> None:
    path = _persist_path(client_id)
    if path.is_file():
        path.unlink()


def resolve_client_id() -> str:
    """Stable per-browser id stored in the URL query string."""
    query_value = st.query_params.get(CLIENT_QUERY_PARAM)
    if isinstance(query_value, list):
        query_value = query_value[0] if query_value else None
    if query_value:
        client_id = str(query_value)
        st.session_state.client_id = client_id
        return client_id

    remembered = st.session_state.get("client_id")
    if remembered:
        client_id = str(remembered)
        st.query_params[CLIENT_QUERY_PARAM] = client_id
        return client_id

    client_id = str(uuid.uuid4())
    st.session_state.client_id = client_id
    st.query_params[CLIENT_QUERY_PARAM] = client_id
    return client_id


def ensure_session_restored() -> None:
    """Restore SKU master from server file and/or browser localStorage."""
    if st.session_state.get("_session_persist_ready"):
        return

    client_id = resolve_client_id()
    st.session_state.client_id = client_id

    server_data = load_server_snapshot(client_id)
    if server_data is not None:
        skus, imported_sales = server_data
        st.session_state.skus = skus
        st.session_state.imported_sales = imported_sales
        st.session_state._session_persist_ready = True
        st.session_state._browser_storage_ready = True
        st.session_state._session_persist_restored = True
        st.session_state._session_persist_source = "server"
        st.session_state._last_persist_count = len(skus)
        return

    ensure_browser_storage_restored()
    if st.session_state.get("_browser_storage_restored"):
        st.session_state._session_persist_restored = True
        st.session_state._session_persist_source = "browser"
        skus = st.session_state.get("skus", [])
        st.session_state._last_persist_count = len(skus)
        try:
            save_server_snapshot(
                client_id,
                skus,
                st.session_state.get("imported_sales"),
            )
        except OSError:
            pass

    st.session_state._session_persist_ready = True


def persist_session_data(*, force: bool = False) -> bool:
    """Save only after explicit user edits/imports — never overwrite with demo data."""
    skus: list[SkuMaster] = st.session_state.get("skus", [])
    if not skus:
        return False
    if not force and not st.session_state.get("_persist_dirty"):
        return False
    if not force and is_demo_skus(skus):
        return False

    imported_sales: list[WeeklySales] | None = st.session_state.get("imported_sales")
    client_id = st.session_state.get("client_id") or resolve_client_id()
    st.session_state.client_id = client_id

    saved = False
    try:
        save_server_snapshot(client_id, skus, imported_sales)
        saved = True
    except OSError:
        pass

    if browser_persist_available():
        saved = persist_browser_storage() or saved

    if saved:
        st.session_state._persist_dirty = False
        st.session_state._last_persist_count = len(skus)
    return saved


def clear_session_data() -> None:
    client_id = st.session_state.get("client_id")
    if client_id:
        delete_server_snapshot(client_id)
    clear_browser_storage()
    st.session_state._persist_dirty = False
    st.session_state._last_persist_count = 0


def session_persist_available() -> bool:
    return True


def persist_status_label() -> str:
    count = st.session_state.get("_last_persist_count") or len(st.session_state.get("skus", []))
    if st.session_state.get("_persist_dirty"):
        return f"⚠️ 저장 필요 · {count}건"
    if count and not is_demo_skus(st.session_state.get("skus", [])):
        return f"💾 저장됨 · {count}건"
    return f"💾 자동 저장 · {count}건"
