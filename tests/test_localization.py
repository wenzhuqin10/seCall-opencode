from pathlib import Path

from secall_opencode.config import Config
from secall_opencode.server import (
    list_vault_sessions,
    localize_display_text,
    read_vault_session,
)


def test_localize_legacy_korean_session_title() -> None:
    assert localize_display_text("codex 세션: secall") == "Codex 会话：secall"
    assert localize_display_text("프로젝트 | 브랜치 | 시간") == "项目 | 分支 | 时间"
    assert (
        localize_display_text("embedding = none (벡터 검색 비활성화)")
        == "embedding = none (向量检索已禁用)"
    )


def test_list_vault_sessions_localizes_title(tmp_path: Path) -> None:
    session_dir = tmp_path / "raw" / ".sessions" / "2026-07-23"
    session_dir.mkdir(parents=True)
    (session_dir / "codex_secall.md").write_text(
        """---
session_id: test-session
project: secall
agent: codex
turns: 16
---

# codex 세션: secall
""",
        encoding="utf-8",
    )

    sessions = list_vault_sessions(Config(vault=tmp_path))

    assert sessions[0]["title"] == "Codex 会话：secall"
    assert not any("\uac00" <= char <= "\ud7a3" for char in sessions[0]["title"])


def test_read_vault_session_returns_read_only_preview_and_quality(tmp_path: Path) -> None:
    session_dir = tmp_path / "raw" / ".sessions" / "2026-07-23"
    session_dir.mkdir(parents=True)
    path = session_dir / "codex_preview.md"
    original = """---
session_id: preview-session
project: secall
agent: codex
turns: 4
---

# codex 세션: secall

## Turn 1 — User

请定位问题。

## Turn 2 — Assistant

> [!tool]- exec

问题已经修复并验证成功。
"""
    path.write_text(original, encoding="utf-8")

    detail = read_vault_session(Config(vault=tmp_path), "preview-session")

    assert detail["title"] == "Codex 会话：secall"
    assert "# Codex 会话：secall" in detail["markdown"]
    assert detail["quality"]["tool_calls"] == 1
    assert detail["quality"]["has_conclusion"] is True
    assert path.read_text(encoding="utf-8") == original
