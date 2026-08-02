from __future__ import annotations

import json
from pathlib import Path

from secall_opencode.converter import convert_export
from secall_opencode.knowledge import store_knowledge
from secall_opencode.structured_knowledge import (
    normalize_session_knowledge,
    read_structured_knowledge,
)


FIXTURE = Path(__file__).parent / "fixtures" / "opencode_session.json"


def test_conversion_writes_evidence_event_sidecar(tmp_path: Path) -> None:
    result = convert_export(json.loads(FIXTURE.read_text(encoding="utf-8")), tmp_path)

    assert result.event_count == 3
    assert result.events_path is not None and result.events_path.exists()
    payload = json.loads(result.events_path.read_text(encoding="utf-8"))
    assert [item["event_id"] for item in payload["events"]] == [
        "evt-0001",
        "evt-0002",
        "evt-0003",
    ]
    assert payload["events"][2]["tool"] == "grep"


def test_structured_output_is_validated_stored_and_scored(tmp_path: Path) -> None:
    converted = convert_export(
        json.loads(FIXTURE.read_text(encoding="utf-8")), tmp_path
    )
    generated = """<!-- SESSION_KNOWLEDGE_JSON_START -->
{
  "context": {"branch": "main"},
  "symptoms": [{"type": "timeout", "evidence_event_ids": ["evt-0001"]}],
  "timeline": [{"description": "检查状态", "evidence_event_ids": ["evt-0003"]}],
  "state_transitions": [],
  "message_flows": [],
  "parameter_changes": [],
  "hypotheses": [{"conclusion": "状态未清零", "status": "confirmed", "evidence_event_ids": ["evt-0003"]}],
  "troubleshooting_steps": [{"action": "grep harq_state", "evidence_event_ids": ["evt-0003"]}],
  "root_cause": {"conclusion": "HARQ 状态未清零", "confidence": "high", "evidence_event_ids": ["evt-0003"]},
  "fix": {"final_fix": "修改 src/mac/scheduler.c 中 reset_harq()"},
  "verification": {"results": "测试通过", "test_cases": ["TC-HARQ-01"]},
  "lessons": {"diagnostic_rules": ["先检查状态清理"]},
  "code_entities": {"modules": ["Scheduler"], "files": ["src/mac/scheduler.c"], "functions": ["reset_harq"], "commits": []},
  "candidate_qa": []
}
<!-- SESSION_KNOWLEDGE_JSON_END -->
---
title: "HARQ timeout"
type: issue
source_session: "ses_test_001"
project: "wireless-baseband"
confidence: high
review_status: pending
---
# HARQ timeout
## 问题现象
发生 timeout。
<!-- QA_JSON_START -->
[]
<!-- QA_JSON_END -->"""

    result = store_knowledge(
        generated,
        converted.markdown,
        tmp_path,
        "wiki/issues",
        "knowledge/qa/candidates.jsonl",
    )

    structured = read_structured_knowledge(tmp_path, "ses_test_001")
    assert structured is not None
    assert result.structured_path is not None and result.structured_path.exists()
    assert structured["root_cause"]["evidence_event_ids"] == ["evt-0003"]
    assert structured["code_entities"]["functions"] == ["reset_harq"]
    assert structured["quality"]["overall"] > 0.7


def test_invalid_evidence_is_removed_and_reported() -> None:
    value = normalize_session_knowledge(
        {
            "context": {},
            "symptoms": [
                {"type": "error", "evidence_event_ids": ["evt-9999"]}
            ],
            "root_cause": {},
        },
        session_id="session-1",
        project="demo",
        events=[{"event_id": "evt-0001"}],
    )

    assert value["symptoms"][0]["evidence_event_ids"] == []
    assert any("evt-9999" in item for item in value["quality"]["warnings"])
