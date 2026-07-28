import json
from pathlib import Path

import pytest

from secall_opencode.config import Config
from secall_opencode.knowledge_store import (
    delete_knowledge_document,
    list_knowledge_trash,
    read_knowledge_document,
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
