from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


STRUCTURED_START = "<!-- SESSION_KNOWLEDGE_JSON_START -->"
STRUCTURED_END = "<!-- SESSION_KNOWLEDGE_JSON_END -->"

KNOWLEDGE_FIELDS = (
    "symptoms",
    "timeline",
    "state_transitions",
    "message_flows",
    "parameter_changes",
    "hypotheses",
    "troubleshooting_steps",
)

CODE_TOKEN = re.compile(
    r"(?P<path>(?:[A-Za-z]:[\\/])?(?:[\w.+-]+[\\/])+[\w.+-]+\."
    r"(?:c|cc|cpp|cxx|h|hpp|py|rs|go|java|kt|js|jsx|ts|tsx|vue|md|json|ya?ml|toml))"
)
FUNCTION_TOKEN = re.compile(
    r"(?<![\w.])(?P<function>[A-Za-z_][A-Za-z0-9_]{2,})\s*\("
)
COMMIT_TOKEN = re.compile(r"(?<![0-9a-f])(?P<commit>[0-9a-f]{7,40})(?![0-9a-f])", re.I)
MODULE_TOKEN = re.compile(
    r"\b(?P<module>HARQ|Scheduler|MAC|PHY|RLC|PDCP|RRC|NAS|MCP|RAG|Wiki|"
    r"OpenCode|seCall|BGE-M3)\b",
    re.I,
)


def _dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _timestamp_ms(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).astimezone().isoformat(
        timespec="milliseconds"
    )


def _event_type(actor: str, content: str) -> str:
    lowered = content.lower()
    if any(token in lowered for token in ("error", "exception", "failed", "失败", "报错")):
        return "error"
    if any(token in lowered for token in ("warning", "warn", "警告")):
        return "warning"
    if any(token in lowered for token in ("验证", "测试通过", "pass", "passed", "成功")):
        return "verification"
    if any(token in lowered for token in ("根因", "原因是", "定位到", "结论")):
        return "diagnosis"
    if actor == "user":
        return "question"
    if actor == "assistant":
        return "answer"
    return "message"


def build_session_events(data: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Convert an OpenCode-compatible export into stable, evidence-addressable events."""
    events: List[Dict[str, Any]] = []
    sequence = 0
    for turn_index, raw_message in enumerate(_list(data.get("messages")), 1):
        message = _dict(raw_message)
        info = _dict(message.get("info"))
        actor = str(info.get("role") or "system")
        timestamp = _timestamp_ms(_dict(info.get("time")).get("created"))
        for raw_part in _list(message.get("parts")):
            part = _dict(raw_part)
            part_type = str(part.get("type") or "")
            if part_type == "text" and part.get("text"):
                sequence += 1
                content = _text(part.get("text"))
                events.append(
                    {
                        "event_id": f"evt-{sequence:04d}",
                        "sequence": sequence,
                        "timestamp": timestamp,
                        "actor": actor,
                        "type": _event_type(actor, content),
                        "content": content,
                        "tool": "",
                        "input": "",
                        "output": "",
                        "status": "",
                        "source_turn": turn_index,
                    }
                )
            elif part_type == "tool":
                sequence += 1
                state = _dict(part.get("state"))
                tool_input = _text(state.get("input"))
                tool_output = _text(state.get("output"))
                status = str(state.get("status") or "")
                combined = f"{tool_input}\n{tool_output}".lower()
                event_type = (
                    "error"
                    if any(token in combined for token in ("error", "failed", "失败", "报错"))
                    else "tool_call"
                )
                events.append(
                    {
                        "event_id": f"evt-{sequence:04d}",
                        "sequence": sequence,
                        "timestamp": timestamp,
                        "actor": actor,
                        "type": event_type,
                        "content": str(part.get("tool") or "unknown"),
                        "tool": str(part.get("tool") or "unknown"),
                        "call_id": str(part.get("callID") or ""),
                        "input": tool_input,
                        "output": tool_output,
                        "status": status,
                        "source_turn": turn_index,
                    }
                )
    return events


def build_events_from_markdown(markdown: str) -> List[Dict[str, Any]]:
    """Backfill evidence events for sessions created before event sidecars existed."""
    turn_pattern = re.compile(
        r"(?m)^##\s+Turn\s+(?P<number>\d+)\s+—\s+(?P<label>[^\r\n(]+)"
        r"(?:\s+\((?P<time>[^)]+)\))?\s*$"
    )
    matches = list(turn_pattern.finditer(markdown))
    events: List[Dict[str, Any]] = []
    sequence = 0
    role_map = {"用户": "user", "助手": "assistant", "系统": "system"}
    tool_pattern = re.compile(r"(?m)^>\s*\[!tool\]-\s*(?P<tool>[^\r\n]+)\s*$")
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[match.end() : end].strip()
        tools = list(tool_pattern.finditer(body))
        message_end = tools[0].start() if tools else len(body)
        content = body[:message_end].strip()
        actor = role_map.get(match.group("label").strip(), match.group("label").strip())
        if content:
            sequence += 1
            events.append(
                {
                    "event_id": f"evt-{sequence:04d}",
                    "sequence": sequence,
                    "timestamp": match.group("time") or "",
                    "actor": actor,
                    "type": _event_type(actor, content),
                    "content": content,
                    "tool": "",
                    "input": "",
                    "output": "",
                    "status": "",
                    "source_turn": int(match.group("number")),
                }
            )
        for tool_index, tool_match in enumerate(tools):
            tool_end = tools[tool_index + 1].start() if tool_index + 1 < len(tools) else len(body)
            tool_body = body[tool_match.end() : tool_end].strip()
            input_match = re.search(r"```json\s*(.*?)\s*```", tool_body, re.DOTALL)
            output_match = re.search(r">\s*\*\*输出\*\*\s*(.*)$", tool_body, re.DOTALL)
            sequence += 1
            events.append(
                {
                    "event_id": f"evt-{sequence:04d}",
                    "sequence": sequence,
                    "timestamp": match.group("time") or "",
                    "actor": actor,
                    "type": "tool_call",
                    "content": tool_match.group("tool").strip(),
                    "tool": tool_match.group("tool").strip(),
                    "input": (input_match.group(1).replace("> ", "").strip() if input_match else ""),
                    "output": (
                        output_match.group(1).replace("> ", "").strip()
                        if output_match
                        else ""
                    ),
                    "status": "",
                    "source_turn": int(match.group("number")),
                }
            )
    return events


def events_path(vault: Path, session_id: str) -> Path:
    return vault / "knowledge" / "events" / f"{session_id}.json"


def structured_path(vault: Path, session_id: str) -> Path:
    return vault / "knowledge" / "structured" / f"{session_id}.json"


def write_json_atomic(path: Path, value: Any) -> None:
    # os.replace is deliberately kept local to avoid importing the editable
    # knowledge store and creating a circular dependency.
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def store_session_events(
    vault: Path, session_id: str, events: Sequence[Mapping[str, Any]]
) -> Path:
    path = events_path(vault, session_id)
    write_json_atomic(
        path,
        {
            "schema_version": 1,
            "session_id": session_id,
            "event_count": len(events),
            "events": [dict(item) for item in events],
        },
    )
    return path


def read_session_events(vault: Path, session_id: str) -> List[Dict[str, Any]]:
    path = events_path(vault, session_id)
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    events = value.get("events") if isinstance(value, dict) else []
    return [dict(item) for item in events if isinstance(item, dict)]


def split_structured_payload(text: str) -> Tuple[str, Dict[str, Any] | None]:
    if STRUCTURED_START not in text or STRUCTURED_END not in text:
        return text, None
    before, rest = text.split(STRUCTURED_START, 1)
    raw, after = rest.split(STRUCTURED_END, 1)
    try:
        value = json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"SessionKnowledge JSON 无效：{exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("SessionKnowledge 必须是 JSON 对象。")
    return (before + after).strip() + "\n", value


def _unique(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        normalized = value.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def extract_code_entities(*values: str) -> Dict[str, List[str]]:
    text = "\n".join(value for value in values if value)
    files = _unique(match.group("path").replace("\\", "/") for match in CODE_TOKEN.finditer(text))
    functions = _unique(match.group("function") for match in FUNCTION_TOKEN.finditer(text))
    commits = _unique(match.group("commit") for match in COMMIT_TOKEN.finditer(text))
    modules = _unique(match.group("module") for match in MODULE_TOKEN.finditer(text))
    return {
        "modules": modules,
        "files": files,
        "functions": functions,
        "commits": commits,
    }


def _evidence_ids(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _normalize_records(
    value: Any, valid_event_ids: set[str], warnings: List[str], field: str
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for raw in _list(value):
        if isinstance(raw, str):
            item: Dict[str, Any] = {"description": raw}
        elif isinstance(raw, Mapping):
            item = dict(raw)
        else:
            continue
        evidence = _evidence_ids(item.get("evidence_event_ids"))
        invalid = [event_id for event_id in evidence if event_id not in valid_event_ids]
        if invalid:
            warnings.append(f"{field} 引用了不存在的事件：{', '.join(invalid)}")
        item["evidence_event_ids"] = [
            event_id for event_id in evidence if event_id in valid_event_ids
        ]
        result.append(item)
    return result


def normalize_session_knowledge(
    value: Mapping[str, Any],
    *,
    session_id: str,
    project: str,
    events: Sequence[Mapping[str, Any]],
    source_text: str = "",
) -> Dict[str, Any]:
    warnings: List[str] = []
    event_ids = {
        str(item.get("event_id"))
        for item in events
        if isinstance(item, Mapping) and item.get("event_id")
    }
    result: Dict[str, Any] = {
        "schema_version": 1,
        "session_id": session_id,
        "source_session": session_id,
        "project": project,
        "context": _dict(value.get("context")),
    }
    for field in KNOWLEDGE_FIELDS:
        result[field] = _normalize_records(value.get(field), event_ids, warnings, field)

    root_cause = _dict(value.get("root_cause"))
    root_cause["evidence_event_ids"] = [
        event_id
        for event_id in _evidence_ids(root_cause.get("evidence_event_ids"))
        if event_id in event_ids
    ]
    result["root_cause"] = root_cause
    result["fix"] = _dict(value.get("fix"))
    result["verification"] = _dict(value.get("verification"))
    result["lessons"] = _dict(value.get("lessons"))

    supplied_entities = _dict(value.get("code_entities"))
    detected = extract_code_entities(
        source_text,
        json.dumps(result.get("fix"), ensure_ascii=False),
        json.dumps(result.get("troubleshooting_steps"), ensure_ascii=False),
    )
    result["code_entities"] = {
        key: _unique(
            [str(item) for item in _list(supplied_entities.get(key))] + detected[key]
        )
        for key in ("modules", "files", "functions", "commits")
    }
    result["candidate_qa"] = [
        dict(item) for item in _list(value.get("candidate_qa")) if isinstance(item, Mapping)
    ]
    result["quality"] = score_session_knowledge(result, events, warnings)
    return result


def score_session_knowledge(
    value: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    warnings: Sequence[str] = (),
) -> Dict[str, Any]:
    checks = {
        "context": bool(_dict(value.get("context"))),
        "symptoms": bool(_list(value.get("symptoms"))),
        "timeline": bool(_list(value.get("timeline"))),
        "troubleshooting": bool(_list(value.get("troubleshooting_steps"))),
        "root_cause": bool(_text(_dict(value.get("root_cause")).get("conclusion"))),
        "fix": bool(_dict(value.get("fix"))),
        "verification": bool(_dict(value.get("verification"))),
        "code_linkage": any(
            _list(_dict(value.get("code_entities")).get(key))
            for key in ("modules", "files", "functions", "commits")
        ),
    }
    evidence_records: List[Mapping[str, Any]] = []
    for field in KNOWLEDGE_FIELDS:
        evidence_records.extend(
            item for item in _list(value.get(field)) if isinstance(item, Mapping)
        )
    root_cause = _dict(value.get("root_cause"))
    if root_cause:
        evidence_records.append(root_cause)
    grounded = sum(
        bool(_evidence_ids(item.get("evidence_event_ids"))) for item in evidence_records
    )
    evidence_coverage = grounded / len(evidence_records) if evidence_records else 0.0
    completeness = sum(checks.values()) / len(checks)
    event_coverage = min(1.0, len(events) / 8) if events else 0.0
    overall = round(
        completeness * 0.5 + evidence_coverage * 0.35 + event_coverage * 0.15, 3
    )
    generated_warnings = list(warnings)
    if not checks["root_cause"]:
        generated_warnings.append("未形成明确根因")
    elif not _evidence_ids(root_cause.get("evidence_event_ids")):
        generated_warnings.append("根因缺少事件证据")
    if not checks["verification"]:
        generated_warnings.append("缺少验证结果")
    if not checks["code_linkage"]:
        generated_warnings.append("缺少代码实体关联")
    return {
        "overall": overall,
        "level": "high" if overall >= 0.8 else "medium" if overall >= 0.55 else "low",
        "completeness": round(completeness, 3),
        "evidence_coverage": round(evidence_coverage, 3),
        "event_coverage": round(event_coverage, 3),
        "checks": checks,
        "warnings": _unique(generated_warnings),
    }


def derive_legacy_structure(
    document: str,
    qa: Sequence[Mapping[str, Any]],
    *,
    session_id: str,
    project: str,
    events: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Build a safe minimum record when an older model returns only Markdown."""

    sections: Dict[str, str] = {}
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", document))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(document)
        sections[match.group(1).strip()] = document[match.end() : end].strip()

    def record(section: str) -> List[Dict[str, Any]]:
        content = sections.get(section, "")
        return [{"description": content, "evidence_event_ids": []}] if content else []

    value = {
        "context": {},
        "symptoms": record("问题现象"),
        "timeline": record("定位过程"),
        "state_transitions": [],
        "message_flows": [],
        "parameter_changes": [],
        "hypotheses": [],
        "troubleshooting_steps": record("定位过程"),
        "root_cause": {
            "conclusion": sections.get("根因分析", ""),
            "confidence": "low" if sections.get("根因分析") else "unknown",
            "evidence_event_ids": [],
        },
        "fix": {
            "final_fix": sections.get("修复方案", ""),
            "code_changes": sections.get("代码变更", ""),
        },
        "verification": {"results": sections.get("验证方法", "")},
        "lessons": {"diagnostic_rules": sections.get("经验总结", "")},
        "candidate_qa": [dict(item) for item in qa],
    }
    normalized = normalize_session_knowledge(
        value,
        session_id=session_id,
        project=project,
        events=events,
        source_text=document,
    )
    normalized["quality"]["warnings"] = _unique(
        ["模型返回旧格式，已生成兼容结构化记录"]
        + normalized["quality"]["warnings"]
    )
    return normalized


def store_structured_knowledge(vault: Path, value: Mapping[str, Any]) -> Path:
    session_id = str(value.get("source_session") or value.get("session_id") or "")
    if not session_id:
        raise ValueError("结构化知识缺少 source_session。")
    path = structured_path(vault, session_id)
    write_json_atomic(path, dict(value))
    return path


def read_structured_knowledge(vault: Path, session_id: str) -> Dict[str, Any] | None:
    path = structured_path(vault, session_id)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, dict) else None


def structured_search_text(value: Mapping[str, Any]) -> str:
    lines: List[str] = []
    labels = {
        "symptoms": "问题现象",
        "timeline": "事件时间线",
        "state_transitions": "状态转换",
        "message_flows": "消息调用链",
        "parameter_changes": "参数变化",
        "hypotheses": "诊断假设",
        "troubleshooting_steps": "排查步骤",
    }
    context = _dict(value.get("context"))
    if context:
        lines.append("运行上下文 " + json.dumps(context, ensure_ascii=False))
    for field, label in labels.items():
        records = _list(value.get(field))
        if records:
            lines.append(f"{label} " + json.dumps(records, ensure_ascii=False))
    for field, label in (
        ("root_cause", "根因"),
        ("fix", "修复方案"),
        ("verification", "验证结果"),
        ("lessons", "经验规则"),
        ("code_entities", "代码实体"),
    ):
        item = _dict(value.get(field))
        if item:
            lines.append(f"{label} " + json.dumps(item, ensure_ascii=False))
    return "\n".join(lines)
