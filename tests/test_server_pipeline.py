from pathlib import Path

from secall_opencode.config import Config
from secall_opencode.knowledge_planning import read_plan
from secall_opencode.opencode_client import OpenCodeClient, Runner
from secall_opencode.server import run_session_pipeline


def test_pipeline_starts_isolated_planning_without_changing_formal_knowledge(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_id = "session-approved-001"
    session_dir = tmp_path / "raw" / ".sessions"
    session_dir.mkdir(parents=True)
    (session_dir / f"{session_id}.md").write_text(
        "---\n"
        f"session_id: {session_id}\n"
        "project: demo\n"
        "turns: 4\n"
        "---\n"
        "# 已审核会话\n",
        encoding="utf-8",
    )
    issue_dir = tmp_path / "wiki" / "issues"
    issue_dir.mkdir(parents=True)
    issue_path = issue_dir / "demo-session-appr.md"
    issue_path.write_text(
        "---\n"
        f"source_session: {session_id}\n"
        "project: demo\n"
        "---\n"
        "# 已有知识\n",
        encoding="utf-8",
    )
    qa_path = tmp_path / "knowledge" / "qa" / "candidates.jsonl"
    qa_path.parent.mkdir(parents=True)
    qa_path.write_text(
        f'{{"id":"qa-1","source_session":"{session_id}"}}\n',
        encoding="utf-8",
    )
    config = Config(vault=tmp_path)
    monkeypatch.setattr(Runner, "run", lambda *args, **kwargs: None)

    result = run_session_pipeline(config, session_id, overwrite=False)

    assert result["reused"] is False
    assert result["knowledge"]["qa_count"] == 0
    assert result["knowledge"]["new_qa_count"] == 0
    assert result["planning_plan_id"].startswith("plan-")
    assert result["planning_status"] == "candidate_selection"
    assert len(result["stages"]) == 3
    assert result["requires_review"] is True
    assert result["wiki_plan_id"] == ""
    assert issue_path.read_text(encoding="utf-8").endswith("# 已有知识\n")
    assert qa_path.read_text(encoding="utf-8").count("qa-1") == 1


def test_pipeline_persists_developer_intent_without_turning_it_into_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_id = "session-approved-intent"
    session_dir = tmp_path / "raw" / ".sessions"
    session_dir.mkdir(parents=True)
    (session_dir / f"{session_id}.md").write_text(
        "---\n"
        f"session_id: {session_id}\n"
        "project: demo\n"
        "turns: 2\n"
        "---\n"
        "# Session\n\n用户：检查超时。\n",
        encoding="utf-8",
    )
    captured: dict[str, str] = {}

    def fake_analysis(self, *args, **kwargs):
        captured["intent"] = kwargs["developer_intent"]
        return {
            "candidates": [{
                "id": "candidate-1", "title": "超时定位", "type": "issue",
                "value": "检查超时的定位路径", "evidence_event_ids": [],
            }],
        }

    monkeypatch.setattr(OpenCodeClient, "run_planning_analysis", fake_analysis)
    config = Config(vault=tmp_path)
    intent = "重点沉淀超时定位路径与验证方法"

    result = run_session_pipeline(config, session_id, knowledge_intent=intent)
    plan = read_plan(config, result["planning_plan_id"])

    assert captured["intent"] == intent
    assert plan["developer_intent"] == intent
    assert all(intent not in event["content"] for event in plan["events"])
    assert not (tmp_path / "wiki" / "issues").exists()
