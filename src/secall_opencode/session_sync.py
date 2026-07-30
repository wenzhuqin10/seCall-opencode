from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict

from .config import Config
from .converter import convert_export
from .opencode_client import OpenCodeClient
from .session_lifecycle import find_session_file, move_session_file
from .session_review_store import update_session_review


class SessionSyncWorker:
    def __init__(self, config: Config, interval: int = 10, settle_seconds: int = 20):
        self.config = config
        self.client = OpenCodeClient(config.opencode_command)
        self.interval = max(3, interval)
        self.settle_seconds = max(5, settle_seconds)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._known_updates: Dict[str, int] = {}
        self._pending: Dict[str, tuple[int, float]] = {}
        self._status: Dict[str, Any] = {
            "running": False,
            "syncing": False,
            "last_checked": "",
            "last_synced": "",
            "synced_total": 0,
            "pending_changes": 0,
            "last_error": "",
        }

    @staticmethod
    def _updated(item: Dict[str, Any]) -> int:
        try:
            return int(item.get("time_updated") or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _skip(item: Dict[str, Any]) -> bool:
        title = str(item.get("title") or "")
        return title.startswith("seCall knowledge:") or title.startswith("seCall RAG:")

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {**self._status, "pending_changes": len(self._pending)}

    def _set_status(self, **values: Any) -> None:
        with self._lock:
            self._status.update(values)

    def _sync_session(self, session_id: str, updated: int) -> None:
        found = find_session_file(self.config, session_id)
        if found and found[0] != "pending":
            move_session_file(self.config, session_id, "pending")
        data = self.client.export(session_id)
        converted = convert_export(
            data,
            self.config.vault,
            overwrite=True,
            destination_dir="staging/sessions",
        )
        if found:
            old_path = found[1]
            if old_path.exists() and old_path.resolve() != converted.output_path.resolve():
                old_path.unlink()
        update_session_review(
            self.config,
            session_id,
            "pending",
            "会话内容发生变化，等待重新预审核。" if found else "",
        )
        self._known_updates[session_id] = updated
        self._set_status(
            last_synced=datetime.now(timezone.utc).isoformat(),
            synced_total=int(self.status()["synced_total"]) + 1,
        )

    def scan(self, *, force: bool = False) -> Dict[str, Any]:
        self._set_status(syncing=True, last_error="")
        synced = 0
        try:
            sessions = self.client.list_sessions(1000)
            now = time.monotonic()
            for item in sessions:
                if self._skip(item):
                    continue
                session_id = str(item.get("id") or "")
                if not session_id:
                    continue
                updated = self._updated(item)
                known = self._known_updates.get(session_id)
                if known is None and find_session_file(self.config, session_id):
                    self._known_updates[session_id] = updated
                    continue
                if known == updated:
                    self._pending.pop(session_id, None)
                    continue
                pending = self._pending.get(session_id)
                if pending is None or pending[0] != updated:
                    self._pending[session_id] = (updated, now)
                    if not force:
                        continue
                first_seen = self._pending[session_id][1]
                if force or now - first_seen >= self.settle_seconds:
                    self._sync_session(session_id, updated)
                    self._pending.pop(session_id, None)
                    synced += 1
            self._set_status(
                last_checked=datetime.now(timezone.utc).isoformat(),
                syncing=False,
            )
            return {"synced": synced, **self.status()}
        except Exception as exc:
            self._set_status(
                syncing=False,
                last_checked=datetime.now(timezone.utc).isoformat(),
                last_error=str(exc),
            )
            return {"synced": synced, **self.status()}

    def _run(self) -> None:
        self._set_status(running=True)
        while not self._stop.is_set():
            self.scan()
            self._wake.wait(self.interval)
            self._wake.clear()
        self._set_status(running=False, syncing=False)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="secall-opencode-session-sync",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)
