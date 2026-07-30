import json
import os
from pathlib import Path

import pytest

from secall_opencode.config import Config
from secall_opencode.search import (
    HybridSearchService,
    KeywordSearchBackend,
    OnnxSemanticBackend,
    SearchResult,
    UnavailableSemanticBackend,
)


def _search_config(tmp_path: Path, monkeypatch) -> Config:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    issue_dir = tmp_path / "wiki" / "issues"
    issue_dir.mkdir(parents=True)
    (issue_dir / "download-session-001.md").write_text(
        """---
title: "seCall 本地部署"
type: issue
source_session: "session-001"
project: "secall"
confidence: high
review_status: approved
---

# seCall 本地部署

## 修复方案

GitHub 大文件连接中断时使用断点续传工具。
""",
        encoding="utf-8",
    )
    qa_path = tmp_path / "knowledge" / "qa" / "candidates.jsonl"
    qa_path.parent.mkdir(parents=True)
    qa_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "qa-approved",
                        "question": "下载中断如何处理？",
                        "answer": "使用断点续传。",
                        "project": "secall",
                        "source_session": "session-001",
                        "review_status": "approved",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "id": "qa-pending",
                        "question": "未审核问题",
                        "answer": "不可检索",
                        "source_session": "session-001",
                        "review_status": "pending",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return Config(vault=tmp_path, secall_command="missing-secall")


def test_keyword_search_indexes_chinese_and_only_approved_qa(
    tmp_path: Path, monkeypatch
) -> None:
    config = _search_config(tmp_path, monkeypatch)
    backend = KeywordSearchBackend(config)

    rebuilt = backend.rebuild()
    knowledge = backend.search("断点续传", "knowledge", 10)
    qa = backend.search("下载中断", "qa", 10)

    assert rebuilt["indexed"] == 2
    assert knowledge[0].id == "download-session-001"
    assert [item.id for item in qa] == ["qa-approved"]


def test_semantic_mode_falls_back_without_model(tmp_path: Path, monkeypatch) -> None:
    config = _search_config(tmp_path, monkeypatch)
    keyword = KeywordSearchBackend(config)
    keyword.rebuild()
    service = HybridSearchService(
        keyword,
        UnavailableSemanticBackend(tmp_path / "missing-model"),
    )

    result = service.search("断点续传", scope="knowledge", mode="semantic")

    assert result["requested_mode"] == "semantic"
    assert result["effective_mode"] == "keyword"
    assert result["semantic_available"] is False
    assert result["results"][0]["match_type"] == "keyword"


class FakeSemanticBackend:
    available = True

    def status(self):
        return {"available": True}

    def rebuild(self):
        return {"available": True}

    def remove(self, document_id: str):
        return None

    def search(self, query: str, scope: str, limit: int):
        return [
            SearchResult(
                id="semantic-result",
                scope="knowledge",
                title="语义结果",
                snippet="含义相近",
                project="demo",
                source_session="session-002",
                score=0.9,
                match_type="semantic",
                review_status="approved",
            )
        ]


def test_hybrid_interface_accepts_future_semantic_backend(
    tmp_path: Path, monkeypatch
) -> None:
    config = _search_config(tmp_path, monkeypatch)
    keyword = KeywordSearchBackend(config)
    keyword.rebuild()
    service = HybridSearchService(keyword, FakeSemanticBackend())

    result = service.search("断点续传", scope="knowledge", mode="hybrid")

    assert result["effective_mode"] == "hybrid"
    assert {item["id"] for item in result["results"]} == {
        "download-session-001",
        "semantic-result",
    }
    assert all(item["match_type"] == "hybrid" for item in result["results"])


def test_all_scope_keeps_knowledge_when_session_backend_has_no_results(
    tmp_path: Path, monkeypatch
) -> None:
    config = _search_config(tmp_path, monkeypatch)
    keyword = KeywordSearchBackend(config)
    keyword.rebuild()
    monkeypatch.setattr(keyword, "_session_search", lambda query, limit: [])

    results = keyword.search("断点续传", scope="all", limit=10)

    assert "download-session-001" in {item.id for item in results}


def test_wiki_pages_join_keyword_index(tmp_path: Path, monkeypatch) -> None:
    config = _search_config(tmp_path, monkeypatch)
    projects = tmp_path / "wiki" / "projects"
    projects.mkdir(parents=True)
    (projects / "radio.md").write_text(
        "# 无线基带项目\n\n记录 HARQ 状态机与调度器排查方法。\n",
        encoding="utf-8",
    )
    backend = KeywordSearchBackend(config)

    rebuilt = backend.rebuild()
    results = backend.search("状态机", scope="wiki", limit=10)

    assert rebuilt["indexed"] == 3
    assert results[0].id == "projects/radio"
    assert results[0].scope == "wiki"


def test_onnx_backend_builds_normalized_semantic_index(
    tmp_path: Path, monkeypatch
) -> None:
    if os.environ.get("RUN_BGE_INTEGRATION") != "1":
        pytest.skip("set RUN_BGE_INTEGRATION=1 for the 2 GB local model test")
    model_dir = Path(r"D:\Models\bge-m3")
    if not (model_dir / "onnx" / "model.onnx").exists():
        return
    config = _search_config(tmp_path, monkeypatch)
    config = Config(
        **{
            **config.__dict__,
            "semantic_backend": "onnx",
            "semantic_model_dir": model_dir,
            "semantic_batch_size": 2,
        }
    )
    backend = OnnxSemanticBackend(config)

    rebuilt = backend.rebuild()
    results = backend.search(
        "resume an interrupted download",
        scope="knowledge",
        limit=3,
    )

    assert rebuilt["available"] is True
    assert rebuilt["indexed_documents"] == 2
    assert rebuilt["indexed_chunks"] >= 2
    assert results
    assert results[0].match_type == "semantic"
    assert -1.0 <= results[0].score <= 1.0


def test_session_only_semantic_request_falls_back_to_keyword(
    tmp_path: Path, monkeypatch
) -> None:
    config = _search_config(tmp_path, monkeypatch)
    keyword = KeywordSearchBackend(config)
    monkeypatch.setattr(
        keyword,
        "search",
        lambda query, scope, limit: [
            SearchResult(
                id="session-001",
                scope="session",
                title="Session",
                snippet="Evidence",
                project="demo",
                source_session="session-001",
                score=1.0,
                match_type="keyword",
                review_status="ready",
            )
        ],
    )

    class KnowledgeOnlySemantic(FakeSemanticBackend):
        def supports_scope(self, scope: str) -> bool:
            return scope != "session"

    service = HybridSearchService(keyword, KnowledgeOnlySemantic())
    result = service.search("download issue", scope="session", mode="semantic")

    assert result["effective_mode"] == "keyword"
    assert result["results"][0]["scope"] == "session"


def test_semantic_sync_only_rebuilds_changed_documents(
    tmp_path: Path, monkeypatch
) -> None:
    import numpy as np

    config = _search_config(tmp_path, monkeypatch)

    class LightweightOnnx(OnnxSemanticBackend):
        @property
        def available(self) -> bool:
            return True

        def _embed(self, texts):
            vectors = np.zeros((len(texts), 4), dtype=np.float32)
            vectors[:, 0] = 1.0
            return vectors

        def status(self):
            documents, chunks = self._counts()
            return {
                "available": True,
                "backend": "onnx",
                "indexed_documents": documents,
                "indexed_chunks": chunks,
            }

    backend = LightweightOnnx(config)
    first = backend.rebuild()
    unchanged = backend.sync()
    issue = tmp_path / "wiki" / "issues" / "download-session-001.md"
    issue.write_text(
        issue.read_text(encoding="utf-8") + "\n新增验证步骤。\n",
        encoding="utf-8",
    )
    changed = backend.sync()

    assert first["updated_documents"] == 2
    assert unchanged["updated_documents"] == 0
    assert changed["updated_documents"] == 1
