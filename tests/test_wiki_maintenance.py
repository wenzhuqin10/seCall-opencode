from pathlib import Path

import pytest

from secall_opencode.config import Config
from secall_opencode.knowledge_store import delete_knowledge_document, restore_knowledge_document
from secall_opencode.structured_knowledge import store_structured_knowledge
from secall_opencode.wiki_maintenance import (
    apply_wiki_plan,
    create_wiki_plan,
    deterministic_reconcile,
    ensure_wiki_schema,
    lint_wiki,
    read_wiki_plan,
    reject_wiki_plan,
)


def _config(tmp_path: Path) -> Config:
    return Config(vault=tmp_path)


def _knowledge(tmp_path: Path) -> None:
    issues = tmp_path / "wiki" / "issues"
    issues.mkdir(parents=True, exist_ok=True)
    (issues / "harq.md").write_text(
        "---\n"
        "title: HARQ timeout 定位\n"
        "type: issue\n"
        "source_session: session-harq\n"
        "project: radio\n"
        "confidence: high\n"
        "review_status: approved\n"
        "---\n\n# HARQ timeout 定位\n\n## 根因分析\n\n状态未清零。\n",
        encoding="utf-8",
    )
    store_structured_knowledge(
        tmp_path,
        {
            "source_session": "session-harq",
            "project": "radio",
            "code_entities": {"modules": ["Scheduler"]},
            "topics": [
                {
                    "name": "HARQ 超时诊断",
                    "description": "先核对反馈映射，再检查定时器。",
                    "source_session": "session-harq",
                    "evidence_event_ids": ["evt-0003"],
                    "scope": "NR Scheduler",
                    "confidence": "high",
                }
            ],
            "decisions": [
                {
                    "name": "缺少影响范围的伪决策",
                    "options": ["A", "B"],
                    "rationale": "会话提到 A",
                }
            ],
            "runbook": [
                {
                    "name": "HARQ 超时排查",
                    "steps": ["检查 process id", "检查 timer"],
                    "evidence_event_ids": ["evt-0003"],
                }
            ],
            "test_knowledge": [
                {
                    "name": "TC-HARQ-01",
                    "description": "连续运行 100 次无超时",
                    "evidence_event_ids": ["evt-0005"],
                }
            ],
        },
    )


def test_plan_creates_reviewable_multi_page_wiki_and_metadata(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _knowledge(tmp_path)

    plan = create_wiki_plan(config, reason="test")
    page_ids = {item["page_id"] for item in plan["changes"]}

    assert plan["status"] == "pending"
    assert plan["requires_review"] is True
    assert {
        "overview/overview",
        "projects/radio",
        "modules/scheduler",
        "topics/harq-超时诊断",
        "runbooks/harq-超时排查",
        "tests/tc-harq-01",
    } <= page_ids
    assert not any(page_id.startswith("decisions/") for page_id in page_ids)
    assert not (tmp_path / "wiki" / "overview.md").exists()

    result = apply_wiki_plan(config, plan["plan_id"])

    assert result["status"] == "applied"
    assert (tmp_path / "wiki" / "overview.md").exists()
    assert (tmp_path / "wiki" / "index.md").exists()
    assert (tmp_path / "wiki" / "log.md").exists()
    assert (tmp_path / "wiki" / ".meta" / "page-registry.json").exists()
    assert create_wiki_plan(config, reason="idempotent")["changes"] == []


def test_plan_detects_page_changed_during_review(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _knowledge(tmp_path)
    plan = create_wiki_plan(config)
    change = next(item for item in plan["changes"] if item["page_id"] == "projects/radio")
    path = tmp_path / change["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 审核期间的人工修改\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="审核期间已变化"):
        apply_wiki_plan(config, plan["plan_id"])

    assert read_wiki_plan(config, plan["plan_id"])["status"] == "conflict"


def test_reject_and_lint_do_not_modify_pages(tmp_path: Path) -> None:
    config = _config(tmp_path)
    ensure_wiki_schema(config)
    _knowledge(tmp_path)
    plan = create_wiki_plan(config)

    rejected = reject_wiki_plan(config, plan["plan_id"], "证据不足")
    report = lint_wiki(config)

    assert rejected["status"] == "rejected"
    assert rejected["rejection_reason"] == "证据不足"
    assert report["finding_count"] >= 1
    assert not (tmp_path / "wiki" / "overview.md").exists()


def test_delete_and_restore_reconcile_applied_wiki_without_model(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _knowledge(tmp_path)
    plan = create_wiki_plan(config)
    apply_wiki_plan(config, plan["plan_id"])

    deleted = delete_knowledge_document(config, "harq")
    after_delete = deterministic_reconcile(config)

    assert "overview/overview" in after_delete["removed_pages"]
    assert not (tmp_path / "wiki" / "overview.md").exists()

    restore_knowledge_document(config, deleted["trash_id"])
    after_restore = deterministic_reconcile(config, allow_create=True)

    assert "overview/overview" in after_restore["updated_pages"]
    assert (tmp_path / "wiki" / "overview.md").exists()
    assert (tmp_path / "wiki" / "topics" / "harq-超时诊断.md").exists()


def test_explicit_conflicting_claim_is_exposed_in_plan(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _knowledge(tmp_path)
    structured = {
        "source_session": "session-harq",
        "project": "radio",
        "code_entities": {"modules": ["Scheduler"]},
        "topics": [{"name": "HARQ 超时诊断"}],
        "claims": [{
            "claim": "应增大 HARQ 定时器",
            "topic": "HARQ 超时诊断",
            "contradicts": "不应在确认反馈映射前增大定时器",
            "source_session": "session-harq",
            "evidence_event_ids": ["evt-0004"],
        }],
    }
    store_structured_knowledge(tmp_path, structured)

    plan = create_wiki_plan(config)
    topic = next(item for item in plan["changes"] if item["page_id"] == "topics/harq-超时诊断")

    assert topic["conflicts"]
    assert "冲突主张" in topic["markdown"]


def test_scalar_module_and_test_summary_do_not_create_character_pages(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _knowledge(tmp_path)
    store_structured_knowledge(
        tmp_path,
        {
            "source_session": "session-harq",
            "project": "radio",
            "code_entities": {"modules": "Scheduler"},
            "verification": {"test_cases": "Python tests passed; API health passed"},
        },
    )

    page_ids = {item["page_id"] for item in create_wiki_plan(config)["changes"]}

    assert "modules/scheduler" in page_ids
    assert not any(page_id.startswith("tests/") for page_id in page_ids)
    assert not any(page_id in {"modules/s", "modules/c"} for page_id in page_ids)
