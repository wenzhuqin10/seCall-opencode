import json
from pathlib import Path

import pytest

from secall_opencode.config import Config
from secall_opencode.knowledge_store import (
    delete_knowledge_document,
    list_knowledge_trash,
    purge_all_knowledge_derivatives,
    read_knowledge_document,
    reconcile_qa_with_knowledge_trash,
    restore_knowledge_document,
    update_knowledge_document,
)


DOCUMENT = """---
title: "下载失败排查"
type: issue
source_session: "session-001"
project: "secall"
confidence: high
review_status: pending
---

# 下载失败排查

## 问题现象

GitHub 大文件下载中断。

## 修复方案

使用支持断点续传的下载工具。
"""


def _config(tmp_path: Path) -> Config:
    issue_dir = tmp_path / "wiki" / "issues"
    issue_dir.mkdir(parents=True)
    (issue_dir / "download-session-001.md").write_text(DOCUMENT, encoding="utf-8")
    qa_path = tmp_path / "knowledge" / "qa" / "candidates.jsonl"
    qa_path.parent.mkdir(parents=True)
    qa_path.write_text(
        json.dumps(
            {
                "id": "qa-001",
                "question": "下载中断怎么办？",
                "answer": "使用断点续传。",
                "source_session": "session-001",
                "review_status": "approved",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return Config(vault=tmp_path)


def test_update_rejects_stale_version_and_immutable_source(tmp_path: Path) -> None:
    config = _config(tmp_path)
    detail = read_knowledge_document(config, "download-session-001")
    detail["title"] = "断点续传排查"
    detail["sections"][1]["content"] = "使用 BITS 或 curl 断点续传。"

    updated = update_knowledge_document(config, detail["id"], detail)

    assert updated["title"] == "断点续传排查"
    assert "BITS" in updated["sections"][1]["content"]
    with pytest.raises(RuntimeError):
        update_knowledge_document(config, detail["id"], detail)
    updated["source_session"] = "changed"
    with pytest.raises(ValueError):
        update_knowledge_document(config, updated["id"], updated)


def test_delete_and_restore_moves_linked_qa(tmp_path: Path) -> None:
    config = _config(tmp_path)

    deleted = delete_knowledge_document(config, "download-session-001")

    assert deleted["qa_count"] == 1
    assert len(list_knowledge_trash(config)) == 1
    assert not (tmp_path / "wiki" / "issues" / "download-session-001.md").exists()
    assert (tmp_path / "knowledge" / "qa" / "candidates.jsonl").read_text(
        encoding="utf-8"
    ) == ""

    restored = restore_knowledge_document(config, deleted["trash_id"])

    assert restored["id"] == "download-session-001"
    assert len(list_knowledge_trash(config)) == 0
    qa = (tmp_path / "knowledge" / "qa" / "candidates.jsonl").read_text(
        encoding="utf-8"
    )
    assert "qa-001" in qa


def test_delete_matches_legacy_truncated_session_id(tmp_path: Path) -> None:
    config = _config(tmp_path)
    issue = tmp_path / "wiki" / "issues" / "download-session-001.md"
    issue.write_text(
        DOCUMENT.replace("session-001", "codex_deepwiki_019f87e7"),
        encoding="utf-8",
    )
    qa_path = tmp_path / "knowledge" / "qa" / "candidates.jsonl"
    qa_path.write_text(
        json.dumps(
            {
                "id": "019f87e7-qa-01",
                "source_session": "019f87e7-7fdd-79d3-ab4e-4e65c49e4b5a",
                "review_status": "approved",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    deleted = delete_knowledge_document(config, "download-session-001")

    assert deleted["qa_count"] == 1
    assert qa_path.read_text(encoding="utf-8") == ""


def test_reconcile_moves_legacy_orphan_qa_into_knowledge_trash(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    qa_path = tmp_path / "knowledge" / "qa" / "candidates.jsonl"
    qa_path.write_text("", encoding="utf-8")
    deleted = delete_knowledge_document(config, "download-session-001")
    qa_path.write_text(
        json.dumps(
            {
                "id": "legacy-qa",
                "source_session": "session-001",
                "review_status": "approved",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = reconcile_qa_with_knowledge_trash(config)

    assert result == {"moved": 1, "remaining": 0}
    assert qa_path.read_text(encoding="utf-8") == ""
    trash_qa = (
        tmp_path
        / ".trash"
        / "knowledge"
        / deleted["trash_id"]
        / "qa.jsonl"
    )
    assert "legacy-qa" in trash_qa.read_text(encoding="utf-8")


def test_purge_all_knowledge_derivatives_preserves_source_sessions(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    raw = tmp_path / "raw" / ".sessions" / "2026-08-01"
    staging = tmp_path / "staging" / "sessions" / "2026-08-01"
    raw.mkdir(parents=True)
    staging.mkdir(parents=True)
    (raw / "session-001.md").write_text("# Source session\n", encoding="utf-8")
    (staging / "pending.md").write_text("# Pending session\n", encoding="utf-8")
    (tmp_path / "wiki" / "overview.md").write_text("# Overview\n", encoding="utf-8")
    graph = tmp_path / "graph"
    graph.mkdir()
    (graph / "graph.json").write_text('{"nodes": [], "links": []}', encoding="utf-8")
    structured = tmp_path / "knowledge" / "structured"
    events = tmp_path / "knowledge" / "events"
    structured.mkdir(parents=True)
    events.mkdir(parents=True)
    (structured / "session-001.json").write_text("{}", encoding="utf-8")
    (events / "session-001.json").write_text("[]", encoding="utf-8")
    delete_knowledge_document(config, "download-session-001")
    wiki_trash = tmp_path / ".trash" / "wiki" / "archived"
    wiki_trash.mkdir(parents=True)
    (wiki_trash / "document.md").write_text("# Old Wiki\n", encoding="utf-8")

    result = purge_all_knowledge_derivatives(config)

    assert result["purged"] is True
    assert result["preserved_sessions"] == 1
    assert (raw / "session-001.md").exists()
    assert (staging / "pending.md").exists()
    assert not (tmp_path / "wiki").exists()
    assert not (tmp_path / "graph" / "graph.json").exists()
    assert not (tmp_path / "knowledge" / "structured").exists()
    assert not (tmp_path / "knowledge" / "events").exists()
    assert not (tmp_path / "knowledge" / "qa" / "candidates.jsonl").exists()
    assert not (tmp_path / ".trash" / "knowledge").exists()
    assert not (tmp_path / ".trash" / "wiki").exists()
