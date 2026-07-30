from pathlib import Path

from secall_opencode.config import Config
from secall_opencode.session_review_store import (
    annotate_sessions,
    excluded_session_ids,
    get_session_review,
    hide_session,
    restore_session,
    update_session_review,
)


def _config(tmp_path: Path) -> Config:
    return Config(vault=tmp_path)


def test_session_review_defaults_to_pending_and_can_be_approved(tmp_path: Path) -> None:
    config = _config(tmp_path)

    assert get_session_review(config, "session-1")["review_status"] == "pending"

    result = update_session_review(config, "session-1", "approved", "证据完整")

    assert result["review_status"] == "approved"
    assert result["review_note"] == "证据完整"
    assert excluded_session_ids(config) == set()


def test_hidden_session_is_only_removed_from_frontend_view(tmp_path: Path) -> None:
    config = _config(tmp_path)
    sessions = [{"id": "session-1"}, {"id": "session-2"}]
    hide_session(config, "session-1")

    visible = annotate_sessions(config, sessions)
    all_sessions = annotate_sessions(config, sessions, include_hidden=True)

    assert [item["id"] for item in visible] == ["session-2"]
    assert len(all_sessions) == 2
    assert all_sessions[0]["hidden"] is True
    assert "session-1" in excluded_session_ids(config)

    restored = restore_session(config, "session-1")
    assert restored["hidden"] is False
    assert [item["id"] for item in annotate_sessions(config, sessions)] == [
        "session-1",
        "session-2",
    ]


def test_rejected_session_is_excluded_from_search(tmp_path: Path) -> None:
    config = _config(tmp_path)

    update_session_review(config, "session-1", "rejected", "缺少有效结论")

    assert excluded_session_ids(config) == {"session-1"}
