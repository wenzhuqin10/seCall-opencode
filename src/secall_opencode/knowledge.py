from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple


QA_START = "<!-- QA_JSON_START -->"
QA_END = "<!-- QA_JSON_END -->"


@dataclass(frozen=True)
class KnowledgeResult:
    issue_path: Path
    qa_path: Path
    qa_count: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "issue_path": str(self.issue_path),
            "qa_path": str(self.qa_path),
            "qa_count": self.qa_count,
        }


def _frontmatter_value(markdown: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*[\"']?(.+?)[\"']?\s*$", markdown)
    return match.group(1).strip("\"'") if match else ""


def split_document_and_qa(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    if QA_START not in text or QA_END not in text:
        return text.strip() + "\n", []
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
    return document, qa


def store_knowledge(
    generated: str,
    source_markdown: str,
    vault: Path,
    knowledge_dir: str,
    qa_file: str,
    overwrite: bool = False,
) -> KnowledgeResult:
    document, candidates = split_document_and_qa(generated)
    session_id = _frontmatter_value(source_markdown, "session_id")
    project = _frontmatter_value(source_markdown, "project") or "unknown"
    if not session_id:
        raise ValueError("源 Session Markdown 缺少 session_id。")

    for item in candidates:
        item.setdefault("source_session", session_id)
        item.setdefault("project", project)
        item.setdefault("review_status", "pending")

    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff-]+", "-", project).strip("-").lower()
    issue_path = vault / knowledge_dir / f"{slug}-{session_id[:12]}.md"
    qa_path = vault / qa_file
    if issue_path.exists() and not overwrite:
        existing = issue_path.read_text(encoding="utf-8")
        if existing != document:
            raise FileExistsError(
                f"Issue Card 已存在且内容不同：{issue_path}；使用 --overwrite 覆盖。"
            )

    issue_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite or not issue_path.exists():
        issue_path.write_text(document, encoding="utf-8")
    qa_path.parent.mkdir(parents=True, exist_ok=True)

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
    return KnowledgeResult(issue_path, qa_path, len(new_lines))
