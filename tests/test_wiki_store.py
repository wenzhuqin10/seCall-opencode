import json
from pathlib import Path

from secall_opencode.config import Config
from secall_opencode.wiki_store import graph_snapshot, list_wiki_pages, read_wiki_page


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
    graph_dir.mkdir(parents=True)
    session_dir.mkdir(parents=True)
    (session_dir / "session-1.md").write_text(
        "---\nsession_id: session-1\nproject: 无线研发\n---\n# codex 세션: 定位调度异常\n",
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
        "nodes": 2,
        "links": 1,
        "types": {
            "session": 1,
            "project": 1,
            "agent": 0,
            "tool": 0,
            "topic": 0,
            "file": 0,
            "issue": 0,
        },
    }
    assert nodes["session:session-1"]["label"] == "Codex 会话：定位调度异常"
    assert nodes["project:legacy"]["label"] == "无线研发"


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
