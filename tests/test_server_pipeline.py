from pathlib import Path

from secall_opencode.config import Config
from secall_opencode.opencode_client import Runner
from secall_opencode.server import run_session_pipeline


def test_pipeline_reuses_existing_knowledge_without_calling_model(
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

    assert result["reused"] is True
    assert result["knowledge"]["qa_count"] == 1
    assert result["knowledge"]["new_qa_count"] == 0
    assert len(result["stages"]) == 5
    assert result["requires_review"] is True
    assert result["wiki_plan_id"].startswith("wiki-")
