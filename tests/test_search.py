import json
from pathlib import Path

from secall_opencode.config import Config
from secall_opencode.search import (
    HybridSearchService,
    KeywordSearchBackend,
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
