"""Session persistence: SQLite + server snapshot + browser localStorage."""

from __future__ import annotations

import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from instock_ct.browser_persist import (
    browser_persist_available,
    clear_browser_storage,
    ensure_browser_storage_restored,
    flush_browser_save_if_pending,
    persist_browser_storage,
    queue_browser_save,
)
from instock_ct.browser_storage import parse_snapshot, snapshot_to_json
from instock_ct.config import DEFAULT_SKUS
from instock_ct.models import ExpiryLot, SkuMaster, WeeklySales

CLIENT_QUERY_PARAM = "cid"
_DEFAULT_PERSIST_CANDIDATES = (
    Path(tempfile.gettempdir()) / "instock_ct_persist",
    Path(__file__).resolve().parent / ".persist",
)
PERSIST_DIR = _DEFAULT_PERSIST_CANDIDATES[0]
GLOBAL_SNAPSHOT_PATH = PERSIST_DIR / "latest_user_data.json"
SQLITE_PATH = Path(tempfile.gettempdir()) / "instock_ct.db"
_DEFAULT_SKU_IDS = frozenset(sku.sku_id for sku in DEFAULT_SKUS)
_resolved_persist_dir: Path | None = None


def _resolve_persist_dir() -> Path:
    global _resolved_persist_dir, PERSIST_DIR, GLOBAL_SNAPSHOT_PATH
    if _resolved_persist_dir is not None:
        return _resolved_persist_dir
    for candidate in _DEFAULT_PERSIST_CANDIDATES:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            _resolved_persist_dir = candidate
            PERSIST_DIR = candidate
            GLOBAL_SNAPSHOT_PATH = candidate / "latest_user_data.json"
            return candidate
        except OSError:
            continue
    _resolved_persist_dir = _DEFAULT_PERSIST_CANDIDATES[0]
    return _resolved_persist_dir


def _sqlite_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    return conn


def _save_sqlite(key: str, payload: str) -> bool:
    try:
        conn = _sqlite_connect()
        conn.execute(
            """
            INSERT OR REPLACE INTO snapshots (key, payload, updated_at)
            VALUES (?, ?, ?)
            """,
            (key, payload, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        row = conn.execute("SELECT payload FROM snapshots WHERE key = ?", (key,)).fetchone()
        conn.close()
        return row is not None and row[0] == payload
    except (OSError, sqlite3.Error):
        return False


def _load_sqlite(key: str) -> tuple[list[SkuMaster], list[WeeklySales] | None, list[ExpiryLot] | None] | None:
    try:
        conn = _sqlite_connect()
        row = conn.execute("SELECT payload FROM snapshots WHERE key = ?", (key,)).fetchone()
        conn.close()
        if not row:
            return None
        return parse_snapshot(str(row[0]))
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return None


def _delete_sqlite(prefix: str | None = None) -> None:
    try:
        conn = _sqlite_connect()
        if prefix is None:
            conn.execute("DELETE FROM snapshots")
        else:
            conn.execute("DELETE FROM snapshots WHERE key = ? OR key = ?", (prefix, "global"))
        conn.commit()
        conn.close()
    except (OSError, sqlite3.Error):
        pass


def is_demo_skus(skus: list[SkuMaster]) -> bool:
    if len(skus) != len(DEFAULT_SKUS):
        return False
    return frozenset(sku.sku_id for sku in skus) == _DEFAULT_SKU_IDS


def mark_persist_dirty() -> None:
    st.session_state._persist_dirty = True


def _session_expiry_lots() -> list[ExpiryLot] | None:
    lots = st.session_state.get("expiry_lots")
    if lots:
        return lots
    flattened: list[ExpiryLot] = []
    for sku in st.session_state.get("skus", []):
        flattened.extend(sku.expiry_lots)
    return flattened or None


def _apply_restored_expiry_lots(expiry_lots: list[ExpiryLot] | None) -> None:
    if expiry_lots:
        st.session_state.expiry_lots = expiry_lots


def _persist_path(client_id: str) -> Path:
    safe_id = "".join(ch for ch in client_id if ch.isalnum() or ch in "-_")
    return _resolve_persist_dir() / f"{safe_id}.json"


def _write_snapshot_file(path: Path, payload: str) -> bool:
    try:
        persist_dir = _resolve_persist_dir()
        persist_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return path.is_file() and path.read_text(encoding="utf-8") == payload
    except OSError:
        return False


def _read_snapshot_file(path: Path) -> tuple[list[SkuMaster], list[WeeklySales] | None, list[ExpiryLot] | None] | None:
    if not path.is_file():
        return None
    try:
        return parse_snapshot(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def save_server_snapshot(
    client_id: str,
    skus: list[SkuMaster],
    imported_sales: list[WeeklySales] | None,
    expiry_lots: list[ExpiryLot] | None = None,
) -> bool:
    payload = snapshot_to_json(skus, imported_sales, expiry_lots)
    cid_ok = _write_snapshot_file(_persist_path(client_id), payload)
    global_ok = _write_snapshot_file(GLOBAL_SNAPSHOT_PATH, payload)
    sqlite_cid_ok = _save_sqlite(f"cid:{client_id}", payload)
    sqlite_global_ok = _save_sqlite("global", payload)
    return cid_ok or global_ok or sqlite_cid_ok or sqlite_global_ok


def load_server_snapshot(
    client_id: str,
) -> tuple[list[SkuMaster], list[WeeklySales] | None, list[ExpiryLot] | None, str] | None:
    for key, source in (
        (f"cid:{client_id}", "sqlite"),
        ("global", "sqlite"),
    ):
        data = _load_sqlite(key)
        if data is not None:
            return data[0], data[1], data[2], source

    data = _read_snapshot_file(_persist_path(client_id))
    if data is not None:
        return data[0], data[1], data[2], "server"

    data = _read_snapshot_file(GLOBAL_SNAPSHOT_PATH)
    if data is not None:
        return data[0], data[1], data[2], "global"

    return None


def delete_server_snapshot(client_id: str) -> None:
    path = _persist_path(client_id)
    if path.is_file():
        path.unlink()
    if GLOBAL_SNAPSHOT_PATH.is_file():
        GLOBAL_SNAPSHOT_PATH.unlink()
    _delete_sqlite(f"cid:{client_id}")


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
    flush_browser_save_if_pending()

    if st.session_state.get("_session_persist_ready"):
        return

    client_id = resolve_client_id()
    st.session_state.client_id = client_id

    server_data = load_server_snapshot(client_id)
    if server_data is not None:
        skus, imported_sales, expiry_lots, source = server_data
        st.session_state.skus = skus
        st.session_state.imported_sales = imported_sales
        _apply_restored_expiry_lots(expiry_lots)
        st.session_state._session_persist_ready = True
        st.session_state._browser_storage_ready = True
        st.session_state._session_persist_restored = True
        st.session_state._session_persist_source = source
        st.session_state._last_persist_count = len(skus)
        st.session_state._server_snapshot_exists = True
        return

    ensure_browser_storage_restored()
    if st.session_state.get("_browser_storage_restored"):
        st.session_state._session_persist_restored = True
        st.session_state._session_persist_source = "browser"
        skus = st.session_state.get("skus", [])
        st.session_state._last_persist_count = len(skus)
        st.session_state._server_snapshot_exists = save_server_snapshot(
            client_id,
            skus,
            st.session_state.get("imported_sales"),
            _session_expiry_lots(),
        )

    st.session_state._session_persist_ready = True
    if not st.session_state.get("_server_snapshot_exists"):
        st.session_state._server_snapshot_exists = (
            GLOBAL_SNAPSHOT_PATH.is_file() or _load_sqlite("global") is not None
        )


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

    expiry_lots = _session_expiry_lots()
    server_saved = save_server_snapshot(client_id, skus, imported_sales, expiry_lots)
    st.session_state._server_snapshot_exists = server_saved

    browser_saved = False
    if browser_persist_available():
        queue_browser_save(skus, imported_sales, expiry_lots)
        browser_saved = persist_browser_storage()

    saved = server_saved or browser_saved
    if saved:
        st.session_state._persist_dirty = False
        st.session_state._last_persist_count = len(skus)
        st.session_state._persist_source = "server" if server_saved else "browser"
    return saved


def clear_session_data() -> None:
    client_id = st.session_state.get("client_id")
    if client_id:
        delete_server_snapshot(client_id)
    clear_browser_storage()
    st.session_state.expiry_lots = None
    st.session_state._persist_dirty = False
    st.session_state._last_persist_count = 0
    st.session_state._server_snapshot_exists = False


def session_persist_available() -> bool:
    return True


def persist_status_label() -> str:
    count = st.session_state.get("_last_persist_count") or len(st.session_state.get("skus", []))
    has_server = st.session_state.get("_server_snapshot_exists")
    if st.session_state.get("_persist_dirty"):
        return f"⚠️ 저장 필요 · {count}건"
    if count and not is_demo_skus(st.session_state.get("skus", [])):
        if has_server:
            return f"💾 서버 저장됨 · {count}건"
        return f"⚠️ 메모리만 · {count}건 (재접속 시 사라질 수 있음)"
    return f"💾 자동 저장 · {count}건"


def set_persist_flash(saved: bool) -> None:
    if saved and st.session_state.get("_server_snapshot_exists"):
        st.session_state.master_persist_flash = "success"
    elif saved:
        st.session_state.master_persist_flash = "browser"
    else:
        st.session_state.master_persist_flash = "fail"


def render_persist_flash() -> None:
    level = st.session_state.pop("master_persist_flash", None)
    if level == "success":
        st.success("✅ **영구 저장 완료** — 탭을 닫았다 열어도 유지됩니다.")
    elif level == "browser":
        st.warning("⚠️ **브라우저 저장만 완료** — 같은 PC·같은 브라우저에서만 유지됩니다.")
    elif level == "fail":
        st.error("❌ **영구 저장 실패** — 아래 **ERP 형식 CSV 다운로드**로 백업해 주세요.")


def persist_result_message(saved: bool) -> str:
    if not saved:
        return "영구 저장 실패"
    if st.session_state.get("_server_snapshot_exists"):
        return "영구 저장 완료"
    return "브라우저 저장 완료"
