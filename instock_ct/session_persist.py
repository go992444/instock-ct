"""Session persistence: server snapshot file keyed by browser cookie."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

from instock_ct.browser_persist import (
    browser_persist_available,
    clear_browser_storage,
    ensure_browser_storage_restored,
    persist_browser_storage,
)
from instock_ct.browser_storage import parse_snapshot, snapshot_to_json
from instock_ct.models import SkuMaster, WeeklySales

COOKIE_NAME = "instock_client_id"
PERSIST_DIR = Path(__file__).resolve().parent / ".persist"


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


@st.cache_resource
def _cookie_manager():
    import extra_streamlit_components as stx

    return stx.CookieManager()


def resolve_client_id() -> str | None:
    """Return a stable browser id, or None while cookies are initializing."""
    remembered = st.session_state.get("client_id")
    if remembered:
        return str(remembered)

    manager = _cookie_manager()
    cookies = manager.get_all()
    if cookies is None:
        return None

    existing = cookies.get(COOKIE_NAME)
    if existing:
        client_id = str(existing)
        st.session_state.client_id = client_id
        return client_id

    if st.session_state.get("_client_id_cookie_set"):
        return st.session_state.get("client_id")

    new_id = str(uuid.uuid4())
    st.session_state.client_id = new_id
    st.session_state._client_id_cookie_set = True
    expires = datetime.now(timezone.utc) + timedelta(days=365)
    manager.set(
        COOKIE_NAME,
        new_id,
        expires_at=expires,
        key="instock_set_client_cookie",
    )
    return new_id


def ensure_session_restored() -> None:
    """Restore SKU master from server file and/or browser localStorage."""
    if st.session_state.get("_session_persist_ready"):
        return

    client_id = resolve_client_id()
    if client_id is None:
        st.caption("저장된 데이터 확인 중…")
        st.stop()

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
        return

    ensure_browser_storage_restored()
    if st.session_state.get("_browser_storage_restored"):
        st.session_state._session_persist_restored = True
        st.session_state._session_persist_source = "browser"
        try:
            save_server_snapshot(
                client_id,
                st.session_state.skus,
                st.session_state.get("imported_sales"),
            )
        except OSError:
            pass

    st.session_state._session_persist_ready = True


def persist_session_data() -> None:
    skus: list[SkuMaster] = st.session_state.get("skus", [])
    if not skus:
        return
    imported_sales: list[WeeklySales] | None = st.session_state.get("imported_sales")
    client_id = st.session_state.get("client_id")
    if client_id:
        try:
            save_server_snapshot(client_id, skus, imported_sales)
        except OSError:
            pass
    if browser_persist_available():
        persist_browser_storage()


def clear_session_data() -> None:
    client_id = st.session_state.get("client_id")
    if client_id:
        delete_server_snapshot(client_id)
    clear_browser_storage()


def session_persist_available() -> bool:
    return True
