import json
from pathlib import Path

import pytest

from secall_opencode.config import Config
from secall_opencode.knowledge_planning import (
    append_dialogue,
    confirm_scope,
    create_plan,
    publish_plan,
    read_draft,
    save_draft,
    save_candidate_revision,
    skip_plan,
    start_review,
    update_scope,
    confirm_candidate,
)


def _create(tmp_path: Path):
    config = Config(vault=tmp_path)
    events = [{"event_id": "evt-0001", "sequence": 1, "actor": "user", "type": "question", "content": "HARQ timeout"}]
    return config, create_plan(config, session_id="session-1", project="demo", source_markdown="---\nsession_id: session-1\n---\n# s\n", events=events, analysis={"candidates": [{"id": "c1", "type": "issue", "title": "HARQ", "value": "问题", "evidence_event_ids": ["evt-0001"]}]})


def _confirm_entry(config: Config, plan_id: str) -> None:
    start_review(config, plan_id)
    save_candidate_revision(
        config, plan_id, "c1",
        {"entries": [{"id": "e1", "type": "root_cause", "content": "HARQ timeout", "evidence_event_ids": ["evt-0001"], "confidence": "high"}]},
    )
    confirm_candidate(config, plan_id, "c1", ["e1"])


def test_planning_isolated_until_scope_confirmed(tmp_path: Path):
    config, plan = _create(tmp_path)
    append_dialogue(config, plan["plan_id"], "只沉淀根因", user_facts=["测试环境为 4T4R"])
    update_scope(config, plan["plan_id"], ["c1"])
    _confirm_entry(config, plan["plan_id"])
    confirmed = confirm_scope(config, plan["plan_id"])
    assert confirmed["status"] == "scope_confirmed"
    assert not (tmp_path / "wiki" / "issues").exists()
    assert not (tmp_path / "knowledge" / "qa" / "candidates.jsonl").exists()


def test_draft_is_not_visible_and_publish_requires_knowledge_dependency(tmp_path: Path):
    config, plan = _create(tmp_path)
    update_scope(config, plan["plan_id"], ["c1"])
    _confirm_entry(config, plan["plan_id"])
    confirm_scope(config, plan["plan_id"])
    generated = """---
title: HARQ
type: issue
source_session: session-1
project: demo
confidence: medium
review_status: pending
---
# HARQ

<!-- QA_JSON_START -->
[{"question":"q","answer":"a","evidence_event_ids":["evt-0001"]}]
<!-- QA_JSON_END -->"""
    save_draft(config, plan["plan_id"], generated)
    assert read_draft(config, plan["plan_id"])["draft"]["qa"]
    with pytest.raises(ValueError, match="必须依赖"):
        publish_plan(config, plan["plan_id"], ["qa"])


def test_skip_requires_reason(tmp_path: Path):
    config, plan = _create(tmp_path)
    with pytest.raises(ValueError):
        skip_plan(config, plan["plan_id"], "")
    assert skip_plan(config, plan["plan_id"], "临时环境排查，不沉淀")["status"] == "skipped"


def test_publish_selected_knowledge_and_qa_only_after_review(tmp_path: Path):
    config, plan = _create(tmp_path)
    source = tmp_path / "raw" / ".sessions" / "session-1.md"
    source.parent.mkdir(parents=True)
    source.write_text("---\nsession_id: session-1\nproject: demo\n---\n# s\n\n用户：HARQ timeout\n", encoding="utf-8")
    update_scope(config, plan["plan_id"], ["c1"])
    _confirm_entry(config, plan["plan_id"])
    confirm_scope(config, plan["plan_id"])
    generated = """---
title: HARQ
type: issue
source_session: session-1
project: demo
confidence: medium
review_status: pending
---
# HARQ

<!-- QA_JSON_START -->
[{"id":"qa-1","question":"q","answer":"a","evidence_event_ids":["evt-0001"]}]
<!-- QA_JSON_END -->"""
    save_draft(config, plan["plan_id"], generated)
    result = publish_plan(config, plan["plan_id"], ["knowledge", "qa"])
    assert result["status"] == "published"
    assert (tmp_path / "wiki" / "issues" / "demo-session-1.md").exists()
    qa = (tmp_path / "knowledge" / "qa" / "candidates.jsonl").read_text(encoding="utf-8")
    assert '"review_status": "approved"' in qa


def test_publish_finds_legacy_session_by_frontmatter_not_file_name(tmp_path: Path):
    config, plan = _create(tmp_path)
    source = tmp_path / "raw" / ".sessions" / "2026-08-12" / "codex_demo_session.md"
    source.parent.mkdir(parents=True)
    source.write_text("---\nsession_id: session-1\nproject: demo\n---\n# session\n", encoding="utf-8")
    update_scope(config, plan["plan_id"], ["c1"])
    _confirm_entry(config, plan["plan_id"])
    confirm_scope(config, plan["plan_id"])
    save_draft(config, plan["plan_id"], "---\ntitle: HARQ\ntype: issue\nsource_session: session-1\nproject: demo\n---\n# HARQ\n")

    result = publish_plan(config, plan["plan_id"], ["knowledge"])

    assert result["status"] == "published"
    assert result["source_path"] == "raw/.sessions/2026-08-12/codex_demo_session.md"
