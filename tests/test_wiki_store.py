import json
from pathlib import Path

import pytest

from secall_opencode.config import Config
from secall_opencode.knowledge_store import delete_knowledge_document
from secall_opencode.structured_knowledge import store_structured_knowledge
from secall_opencode.wiki_store import (
    DERIVED_END,
    DERIVED_START,
    archive_wiki_page,
    graph_snapshot,
    list_wiki_archive,
    list_wiki_pages,
    purge_all_wiki_archive,
    purge_wiki_archive,
    read_wiki_page,
    restore_wiki_page,
    sync_wiki_knowledge_views,
)


def _config(tmp_path: Path) -> Config:
    return Config(vault=tmp_path, secall_command="secall")


def test_lists_and_reads_wiki_pages_with_backlinks(tmp_path: Path) -> None:
    projects = tmp_path / "wiki" / "projects"
    topics = tmp_path / "wiki" / "topics"
    projects.mkdir(parents=True)
    topics.mkdir(parents=True)
    (projects / "radio.md").write_text(
        "---\nproject: radio\n---\n# 无线项目\n\n项目知识总览。\n\n[[harq]]\n",
        encoding="utf-8",
    )
    (topics / "harq.md").write_text(
        "# HARQ 调试\n\n## 定位方法\n\n检查状态机和超时日志。\n",
        encoding="utf-8",
    )

    listed = list_wiki_pages(_config(tmp_path))
    detail = read_wiki_page(_config(tmp_path), "topics", "harq")

    assert listed["count"] == 2
    assert listed["counts"]["projects"] == 1
    assert detail["title"] == "HARQ 调试"
    assert detail["sections"][0]["heading"] == "定位方法"
    assert detail["backlinks"][0]["id"] == "projects/radio"


def test_graph_snapshot_enriches_session_and_project_labels(tmp_path: Path) -> None:
    graph_dir = tmp_path / "graph"
    session_dir = tmp_path / "raw" / ".sessions"
    issue_dir = tmp_path / "wiki" / "issues"
    graph_dir.mkdir(parents=True)
    session_dir.mkdir(parents=True)
    issue_dir.mkdir(parents=True)
    (session_dir / "session-1.md").write_text(
        "---\nsession_id: session-1\nproject: 无线研发\n---\n# codex 세션: 定位调度异常\n",
        encoding="utf-8",
    )
    (issue_dir / "schedule.md").write_text(
        "---\ntitle: Schedule issue\nproject: 无线研发\n"
        "source_session: session-1\n---\n# Schedule issue\n",
        encoding="utf-8",
    )
    (graph_dir / "graph.json").write_text(
        json.dumps(
            {
                "directed": True,
                "multigraph": False,
                "nodes": [
                    {"id": "session:session-1", "type": "session", "label": "old"},
                    {"id": "project:legacy", "type": "project", "label": "legacy"},
                ],
                "links": [
                    {
                        "source": "session:session-1",
                        "target": "project:legacy",
                        "relation": "belongs_to",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    snapshot = graph_snapshot(_config(tmp_path))
    nodes = {item["id"]: item for item in snapshot["nodes"]}

    assert snapshot["stats"] == {
        "nodes": 3,
        "links": 3,
        "types": {
            "issue": 1,
            "project": 1,
            "module": 0,
            "session": 1,
            "topic": 0,
            "wiki_page": 0,
        },
        "evidence": {
            "files": 0,
            "functions": 0,
            "commits": 0,
            "root_causes": 0,
            "test_cases": 0,
        },
    }
    assert nodes["session:session-1"]["label"] == "Codex 会话：定位调度异常"
    assert nodes["project:无线研发"]["label"] == "无线研发"


def test_graph_snapshot_tracks_current_issue_cards(tmp_path: Path) -> None:
    graph_dir = tmp_path / "graph"
    session_dir = tmp_path / "raw" / ".sessions"
    issue_dir = tmp_path / "wiki" / "issues"
    graph_dir.mkdir(parents=True)
    session_dir.mkdir(parents=True)
    issue_dir.mkdir(parents=True)
    (session_dir / "session-1.md").write_text(
        "---\nsession_id: session-1\nproject: 无线研发\n---\n# 调度会话\n",
        encoding="utf-8",
    )
    (issue_dir / "调度异常.md").write_text(
        "---\n"
        "title: 调度异常定位\n"
        "project: 无线研发\n"
        "source_session: session-1\n"
        "---\n"
        "# 调度异常定位\n",
        encoding="utf-8",
    )
    (graph_dir / "graph.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": "session:session-1", "type": "session", "label": "session-1"},
                    {"id": "project:无线研发", "type": "project", "label": "无线研发"},
                ],
                "links": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    before = graph_snapshot(_config(tmp_path))
    issue = next(item for item in before["nodes"] if item["type"] == "issue")

    assert issue["label"] == "调度异常定位"
    assert before["stats"]["types"]["issue"] == 1
    assert {
        (item["source"], item["target"], item["relation"])
        for item in before["links"]
    } >= {
        ("issue:调度异常", "project:无线研发", "belongs_to"),
        ("issue:调度异常", "session:session-1", "derived_from"),
    }

    (issue_dir / "调度异常.md").unlink()
    after = graph_snapshot(_config(tmp_path))
    assert after["stats"]["types"]["issue"] == 0
    assert all(item["id"] != "issue:调度异常" for item in after["nodes"])


def test_graph_snapshot_keeps_technical_details_as_issue_evidence(
    tmp_path: Path,
) -> None:
    graph_dir = tmp_path / "graph"
    issue_dir = tmp_path / "wiki" / "issues"
    graph_dir.mkdir(parents=True)
    issue_dir.mkdir(parents=True)
    (issue_dir / "harq.md").write_text(
        "---\n"
        "title: HARQ timeout\n"
        "project: radio\n"
        "source_session: session-harq\n"
        "---\n# HARQ timeout\n",
        encoding="utf-8",
    )
    (graph_dir / "graph.json").write_text(
        json.dumps({"nodes": [], "links": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    store_structured_knowledge(
        tmp_path,
        {
            "source_session": "session-harq",
            "code_entities": {
                "modules": ["Scheduler"],
                "files": ["src/mac/scheduler.c"],
                "functions": ["reset_harq"],
                "commits": ["abcdef1"],
            },
            "root_cause": {"conclusion": "HARQ 状态未清零"},
            "verification": {"test_cases": ["TC-HARQ-01"]},
        },
    )

    snapshot = graph_snapshot(_config(tmp_path))
    links = {
        (item["source"], item["target"], item["relation"])
        for item in snapshot["links"]
    }

    assert ("issue:harq", "module:Scheduler", "affects") in links
    assert not any(
        item[1].startswith(("file:", "function:", "commit:", "root_cause:", "test_case:"))
        for item in links
    )
    issue = next(item for item in snapshot["nodes"] if item["id"] == "issue:harq")
    assert issue["evidence"] == {
        "files": ["src/mac/scheduler.c"],
        "functions": ["reset_harq"],
        "commits": ["abcdef1"],
        "root_causes": ["HARQ 状态未清零"],
        "test_cases": ["TC-HARQ-01"],
    }
    assert snapshot["stats"]["evidence"] == {
        "files": 1,
        "functions": 1,
        "commits": 1,
        "root_causes": 1,
        "test_cases": 1,
    }


def test_sync_wiki_knowledge_views_updates_overview_and_project_after_delete(
    tmp_path: Path,
) -> None:
    overview = tmp_path / "wiki" / "overview.md"
    projects = tmp_path / "wiki" / "projects"
    issues = tmp_path / "wiki" / "issues"
    projects.mkdir(parents=True)
    issues.mkdir(parents=True)
    overview.write_text("# 知识库总览\n\n保留的人工说明。\n", encoding="utf-8")
    project = projects / "radio.md"
    project.write_text("# Radio\n\n项目说明。\n", encoding="utf-8")
    issue = issues / "harq.md"
    issue.write_text(
        "---\n"
        "title: HARQ timeout\n"
        "type: issue\n"
        "source_session: session-harq\n"
        "project: radio\n"
        "confidence: high\n"
        "review_status: pending\n"
        "---\n"
        "# HARQ timeout\n\n"
        "## 问题现象\n\n等待反馈超时。\n",
        encoding="utf-8",
    )
    config = _config(tmp_path)

    first = sync_wiki_knowledge_views(config)
    first_overview = overview.read_text(encoding="utf-8")
    first_project = project.read_text(encoding="utf-8")

    assert first["knowledge_count"] == 1
    assert first_overview.count(DERIVED_START) == 1
    assert first_overview.count(DERIVED_END) == 1
    assert "[[issues/harq|HARQ timeout]]" in first_overview
    assert f"{DERIVED_END}\n\n保留的人工说明。" in first_overview
    assert "保留的人工说明。" in first_overview
    assert "[[issues/harq|HARQ timeout]]" in first_project

    # Re-running is idempotent and does not duplicate the managed block.
    sync_wiki_knowledge_views(config)
    assert overview.read_text(encoding="utf-8").count(DERIVED_START) == 1

    delete_knowledge_document(config, "harq")
    second = sync_wiki_knowledge_views(config)
    second_overview = overview.read_text(encoding="utf-8")
    second_project = project.read_text(encoding="utf-8")

    assert second["knowledge_count"] == 0
    assert "当前没有已入库的知识卡片。" in second_overview
    assert "[[issues/harq|HARQ timeout]]" not in second_overview
    assert "当前没有关联的知识卡片。" in second_project
    assert "项目说明。" in second_project


def test_archive_and_restore_wiki_page_without_overwriting(tmp_path: Path) -> None:
    projects = tmp_path / "wiki" / "projects"
    projects.mkdir(parents=True)
    page = projects / "radio.md"
    page.write_text(
        "---\ntitle: Radio\nproject: radio\n---\n# Radio\n\n项目知识。\n",
        encoding="utf-8",
    )
    config = _config(tmp_path)

    archived = archive_wiki_page(config, "projects", "radio")

    assert archived["wiki_id"] == "projects/radio"
    assert not page.exists()
    assert list_wiki_pages(config)["count"] == 0
    assert list_wiki_archive(config)[0]["trash_id"] == archived["trash_id"]

    restored = restore_wiki_page(config, archived["trash_id"])

    assert restored["id"] == "projects/radio"
    assert page.exists()
    assert list_wiki_archive(config) == []

    archived_again = archive_wiki_page(config, "projects", "radio")
    page.write_text("# 新的同名页面\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        restore_wiki_page(config, archived_again["trash_id"])


def test_archive_supports_overview_and_protects_issue_pages(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    issues = wiki / "issues"
    issues.mkdir(parents=True)
    (wiki / "overview.md").write_text("# 总览\n", encoding="utf-8")
    (issues / "harq.md").write_text("# HARQ\n", encoding="utf-8")
    config = _config(tmp_path)

    archived = archive_wiki_page(config, "overview", "overview")
    assert not (wiki / "overview.md").exists()
    sync_wiki_knowledge_views(config)
    assert not (wiki / "overview.md").exists()
    restored = restore_wiki_page(config, archived["trash_id"])
    assert restored["id"] == "overview/overview"
    with pytest.raises(ValueError, match="知识卡片"):
        archive_wiki_page(config, "issues", "harq")


def test_graph_removes_wiki_page_node_when_archived(tmp_path: Path) -> None:
    graph_dir = tmp_path / "graph"
    topics = tmp_path / "wiki" / "topics"
    graph_dir.mkdir(parents=True)
    topics.mkdir(parents=True)
    (graph_dir / "graph.json").write_text(
        json.dumps({"nodes": [], "links": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (topics / "rag.md").write_text("# RAG 检索\n", encoding="utf-8")
    config = _config(tmp_path)

    before = graph_snapshot(config)
    assert before["stats"]["types"]["wiki_page"] == 1
    assert any(item["id"] == "wiki:topics/rag" for item in before["nodes"])

    archive_wiki_page(config, "topics", "rag")
    after = graph_snapshot(config)
    assert after["stats"]["types"]["wiki_page"] == 0
    assert all(item["id"] != "wiki:topics/rag" for item in after["nodes"])


def test_permanently_purge_single_wiki_archive(tmp_path: Path) -> None:
    topics = tmp_path / "wiki" / "topics"
    topics.mkdir(parents=True)
    page = topics / "rag.md"
    page.write_text("# RAG\n\n检索知识。\n", encoding="utf-8")
    config = _config(tmp_path)
    archived = archive_wiki_page(config, "topics", "rag")

    purged = purge_wiki_archive(config, archived["trash_id"])

    assert purged["purged"] is True
    assert purged["wiki_id"] == "topics/rag"
    assert list_wiki_archive(config) == []
    with pytest.raises(FileNotFoundError):
        restore_wiki_page(config, archived["trash_id"])


def test_clear_wiki_archive_only_removes_archived_pages(tmp_path: Path) -> None:
    projects = tmp_path / "wiki" / "projects"
    projects.mkdir(parents=True)
    active = projects / "active.md"
    active.write_text("# Active\n", encoding="utf-8")
    for slug in ("one", "two"):
        page = projects / f"{slug}.md"
        page.write_text(f"# {slug}\n", encoding="utf-8")
    config = _config(tmp_path)
    archive_wiki_page(config, "projects", "one")
    archive_wiki_page(config, "projects", "two")

    result = purge_all_wiki_archive(config)

    assert result["purged"] == 2
    assert active.exists()
    assert list_wiki_archive(config) == []
