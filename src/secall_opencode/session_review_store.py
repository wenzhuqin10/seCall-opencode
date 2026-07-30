from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .config import Config
from .knowledge_store import atomic_write_text


SAFE_SESSION_ID = re.compile(r"^[0-9A-Za-z._:+-]+$")
REVIEW_STATUSES = {"pending", "approved", "rejected"}


def _review_path(config: Config) -> Path:
    return config.vault / "knowledge" / "session-reviews.json"


def _validate_session_id(session_id: str) -> str:
    if not session_id or not SAFE_SESSION_ID.fullmatch(session_id):
        raise ValueError("Session ID 包含非法字符。")
    return session_id


def _load(config: Config) -> Dict[str, Dict[str, Any]]:
    path = _review_path(config)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"会话审核记录无法读取：{exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("会话审核记录格式无效。")
    return {
        str(key): dict(item)
        for key, item in value.items()
        if isinstance(item, dict)
    }


def _save(config: Config, records: Dict[str, Dict[str, Any]]) -> None:
    path = _review_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path,
        json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def get_session_review(config: Config, session_id: str) -> Dict[str, Any]:
    session_id = _validate_session_id(session_id)
    item = _load(config).get(session_id, {})
    return {
        "review_status": str(item.get("review_status") or "pending"),
        "review_note": str(item.get("review_note") or ""),
        "hidden": bool(item.get("hidden", False)),
        "reviewed_at": str(item.get("reviewed_at") or ""),
    }


def annotate_sessions(
    config: Config,
    sessions: Iterable[Dict[str, Any]],
    *,
    include_hidden: bool = False,
) -> List[Dict[str, Any]]:
    records = _load(config)
    result: List[Dict[str, Any]] = []
    for session in sessions:
        item = records.get(str(session["id"]), {})
        default_status = {
            "approved": "approved",
            "rejected": "rejected",
        }.get(str(session.get("storage_state") or ""), "pending")
        hidden = bool(item.get("hidden", False))
        if hidden and not include_hidden:
            continue
        result.append(
            {
                **session,
                "review_status": str(item.get("review_status") or default_status),
                "review_note": str(item.get("review_note") or ""),
                "hidden": hidden,
                "reviewed_at": str(item.get("reviewed_at") or ""),
            }
        )
    return result


def update_session_review(
    config: Config,
    session_id: str,
    status: str,
    note: str = "",
) -> Dict[str, Any]:
    session_id = _validate_session_id(session_id)
    if status not in REVIEW_STATUSES:
        raise ValueError("审核状态必须是 pending、approved 或 rejected。")
    records = _load(config)
    current = records.get(session_id, {})
    records[session_id] = {
        **current,
        "review_status": status,
        "review_note": note.strip()[:1000],
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(config, records)
    return {"id": session_id, **get_session_review(config, session_id)}


def hide_session(
    config: Config,
    session_id: str,
    current_status: str = "pending",
) -> Dict[str, Any]:
    session_id = _validate_session_id(session_id)
    records = _load(config)
    current = records.get(session_id, {})
    records[session_id] = {
        **current,
        "review_status": str(current.get("review_status") or current_status),
        "review_note": str(current.get("review_note") or ""),
        "hidden": True,
        "hidden_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(config, records)
    return {"id": session_id, **get_session_review(config, session_id)}


def restore_session(config: Config, session_id: str) -> Dict[str, Any]:
    session_id = _validate_session_id(session_id)
    records = _load(config)
    current = records.get(session_id)
    if not current or not current.get("hidden"):
        raise FileNotFoundError(f"隐藏会话不存在：{session_id}")
    current["hidden"] = False
    current["restored_at"] = datetime.now(timezone.utc).isoformat()
    records[session_id] = current
    _save(config, records)
    return {"id": session_id, **get_session_review(config, session_id)}


def excluded_session_ids(config: Config) -> set[str]:
    return {
        session_id
        for session_id, item in _load(config).items()
        if bool(item.get("hidden")) or item.get("review_status") == "rejected"
    }
