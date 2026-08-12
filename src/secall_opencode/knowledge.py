from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from .structured_knowledge import (
    build_events_from_markdown,
    derive_legacy_structure,
    normalize_session_knowledge,
    read_session_events,
    split_structured_payload,
    store_session_events,
    store_structured_knowledge,
)


QA_START = "<!-- QA_JSON_START -->"
QA_END = "<!-- QA_JSON_END -->"


@dataclass(frozen=True)
class KnowledgeResult:
    issue_path: Path
    qa_path: Path
    qa_count: int
    structured_path: Path | None = None
    quality: Dict[str, Any] | None = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "issue_path": str(self.issue_path),
            "qa_path": str(self.qa_path),
            "qa_count": self.qa_count,
            "structured_path": str(self.structured_path) if self.structured_path else "",
            "quality": self.quality or {},
        }


def _frontmatter_value(markdown: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*[\"']?(.+?)[\"']?\s*$", markdown)
    return match.group(1).strip("\"'") if match else ""


def split_generated_output(
    text: str,
) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any] | None]:
    text, structured = split_structured_payload(text)
    if QA_START not in text or QA_END not in text:
        return text.strip() + "\n", [], structured
    before, rest = text.split(QA_START, 1)
    raw_qa, after = rest.split(QA_END, 1)
    try:
        value = json.loads(raw_qa.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"候选 QA JSON 无效：{exc}") from exc
    if not isinstance(value, list):
        raise ValueError("候选 QA 必须是 JSON 数组。")
    qa = [item for item in value if isinstance(item, dict)]
    document = (before + after).strip() + "\n"
    return document, qa, structured


def split_document_and_qa(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    document, qa, _ = split_generated_output(text)
    return document, qa


def store_knowledge(
    generated: str,
    source_markdown: str,
    vault: Path,
    knowledge_dir: str,
    qa_file: str,
    overwrite: bool = False,
    include_qa: bool = True,
) -> KnowledgeResult:
    document, candidates, structured_payload = split_generated_output(generated)
    session_id = _frontmatter_value(source_markdown, "session_id")
    project = _frontmatter_value(source_markdown, "project") or "unknown"
    if not session_id:
        raise ValueError("源 Session Markdown 缺少 session_id。")

    events = read_session_events(vault, session_id)
    if not events:
        events = build_events_from_markdown(source_markdown)
        if events:
            store_session_events(vault, session_id, events)
    if structured_payload is not None:
        structured = normalize_session_knowledge(
            structured_payload,
            session_id=session_id,
            project=project,
            events=events,
            source_text=source_markdown + "\n" + document,
        )
        if not candidates:
            candidates = [
                dict(item)
                for item in structured.get("candidate_qa", [])
                if isinstance(item, Mapping)
            ]
    else:
        structured = derive_legacy_structure(
            document,
            candidates,
            session_id=session_id,
            project=project,
            events=events,
        )
    valid_event_ids = {
        str(event.get("event_id"))
        for event in events
        if isinstance(event, Mapping) and event.get("event_id")
    }
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff-]+", "-", project).strip("-").lower()
    issue_path = vault / knowledge_dir / f"{slug}-{session_id[:12]}.md"
    knowledge_id = issue_path.stem
    for item in candidates:
        item.setdefault("source_session", session_id)
        item.setdefault("knowledge_id", knowledge_id)
        item.setdefault("project", project)
        item.setdefault("review_status", "pending")
        item.setdefault("evidence_event_ids", [])
        item.setdefault("related_files", [])
        item.setdefault("related_functions", [])
        evidence_ids = item.get("evidence_event_ids")
        if not isinstance(evidence_ids, list):
            evidence_ids = [evidence_ids] if evidence_ids else []
        item["evidence_event_ids"] = [
            str(event_id)
            for event_id in evidence_ids
            if str(event_id) in valid_event_ids
        ]

    qa_path = vault / qa_file
    if issue_path.exists() and not overwrite:
        existing = issue_path.read_text(encoding="utf-8")
        if existing != document:
            raise FileExistsError(
                f"Issue Card 已存在且内容不同：{issue_path}；使用 --overwrite 覆盖。"
            )

    structured_file = store_structured_knowledge(vault, structured)
    issue_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite or not issue_path.exists():
        issue_path.write_text(document, encoding="utf-8")
    qa_path.parent.mkdir(parents=True, exist_ok=True)

    # Draft-first publishing may persist the Issue Card before its candidate QA
    # has been approved.  In that case do not create a visible QA queue entry.
    if not include_qa:
        return KnowledgeResult(
            issue_path=issue_path,
            qa_path=qa_path,
            qa_count=0,
            structured_path=structured_file,
            quality=dict(structured.get("quality") or {}),
        )

    existing_ids = set()
    if qa_path.exists():
        for line in qa_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("id"):
                existing_ids.add(str(record["id"]))

    new_lines = []
    for index, item in enumerate(candidates, 1):
        item.setdefault("id", f"{session_id}-qa-{index:02d}")
        if str(item["id"]) not in existing_ids:
            new_lines.append(json.dumps(item, ensure_ascii=False))
    if new_lines:
        with qa_path.open("a", encoding="utf-8", newline="\n") as handle:
            for line in new_lines:
                handle.write(line + "\n")
    return KnowledgeResult(
        issue_path,
        qa_path,
        len(new_lines),
        structured_path=structured_file,
        quality=dict(structured.get("quality") or {}),
    )
