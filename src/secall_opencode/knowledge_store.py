from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .config import Config


SAFE_ID = re.compile(r"^[0-9A-Za-z\u4e00-\u9fff._+-]+$")
SECTION_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")


def parse_frontmatter(markdown: str) -> Tuple[Dict[str, str], str]:
    if not markdown.startswith("---"):
        return {}, markdown
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", markdown, re.DOTALL)
    if not match:
        return {}, markdown
    metadata: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("\"'")
    return metadata, markdown[match.end() :]


def _document_version(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _knowledge_root(config: Config) -> Path:
    return config.vault / config.knowledge_dir


def _validate_id(value: str) -> str:
    if not value or not SAFE_ID.fullmatch(value):
        raise ValueError("知识 ID 包含非法字符。")
    return value


def _find_knowledge_path(config: Config, knowledge_id: str) -> Path:
    knowledge_id = _validate_id(knowledge_id)
    path = _knowledge_root(config) / f"{knowledge_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"知识卡片不存在：{knowledge_id}")
    return path


def _sections(body: str) -> Tuple[str, List[Dict[str, str]]]:
    matches = list(SECTION_RE.finditer(body))
    before = body[: matches[0].start()].strip() if matches else body.strip()
    result: List[Dict[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        result.append(
            {
                "heading": match.group(1).strip(),
                "content": body[match.end() : end].strip(),
            }
        )
    return before, result


def read_knowledge_document(config: Config, knowledge_id: str) -> Dict[str, Any]:
    path = _find_knowledge_path(config, knowledge_id)
    markdown = path.read_text(encoding="utf-8", errors="replace")
    metadata, body = parse_frontmatter(markdown)
    intro, sections = _sections(body)
    heading_match = re.search(r"(?m)^#\s+(.+?)\s*$", intro)
    heading = heading_match.group(1).strip() if heading_match else metadata.get("title", path.stem)
    return {
        "id": path.stem,
        "title": metadata.get("title") or heading,
        "heading": heading,
        "project": metadata.get("project") or "unknown",
        "source_session": metadata.get("source_session") or "",
        "confidence": metadata.get("confidence") or "unknown",
        "review_status": metadata.get("review_status") or "pending",
        "type": metadata.get("type") or "issue",
        "intro": intro,
        "sections": sections,
        "markdown": markdown,
        "version": _document_version(markdown),
        "updated": int(path.stat().st_mtime * 1000),
    }


def list_knowledge_documents(config: Config, limit: int = 200) -> List[Dict[str, Any]]:
    root = _knowledge_root(config)
    if not root.exists():
        return []
    files = sorted(root.glob("*.md"), key=lambda item: item.stat().st_mtime, reverse=True)
    result = []
    for path in files[: max(1, min(limit, 1000))]:
        document = read_knowledge_document(config, path.stem)
        summary = next(
            (
                section["content"].replace("\n", " ")[:240]
                for section in document["sections"]
                if section["content"]
            ),
            document["intro"].replace("\n", " ")[:240],
        )
        result.append(
            {
                "id": document["id"],
                "title": document["title"],
                "project": document["project"],
                "source_session": document["source_session"],
                "confidence": document["confidence"],
                "review_status": document["review_status"],
                "summary": summary,
                "updated": document["updated"],
            }
        )
    return result


def _yaml_value(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _render_document(existing: Dict[str, Any], payload: Dict[str, Any]) -> str:
    title = str(payload.get("title") or "").strip()
    project = str(payload.get("project") or "").strip()
    confidence = str(payload.get("confidence") or "").strip()
    review_status = str(payload.get("review_status") or "").strip()
    if not title or not project:
        raise ValueError("标题和项目不能为空。")
    if confidence not in {"high", "medium", "low", "unknown"}:
        raise ValueError("confidence 必须是 high、medium、low 或 unknown。")
    if review_status not in {"pending", "approved", "rejected"}:
        raise ValueError("review_status 无效。")
    source_session = str(payload.get("source_session") or "")
    if source_session != existing["source_session"]:
        raise ValueError("source_session 不允许修改。")
    raw_sections = payload.get("sections")
    if not isinstance(raw_sections, list):
        raise ValueError("sections 必须是数组。")
    sections: List[Tuple[str, str]] = []
    for item in raw_sections:
        if not isinstance(item, dict):
            raise ValueError("章节格式无效。")
        heading = str(item.get("heading") or "").strip()
        content = str(item.get("content") or "").strip()
        if not heading or "\n" in heading:
            raise ValueError("章节标题不能为空或包含换行。")
        sections.append((heading, content))

    lines = [
        "---",
        f"title: {_yaml_value(title)}",
        f"type: {_yaml_value(existing['type'])}",
        f"source_session: {_yaml_value(existing['source_session'])}",
        f"project: {_yaml_value(project)}",
        f"confidence: {confidence}",
        f"review_status: {review_status}",
        "---",
        "",
        f"# {title}",
        "",
    ]
    for heading, content in sections:
        lines.extend([f"## {heading}", "", content, ""])
    return "\n".join(lines).rstrip() + "\n"


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def update_knowledge_document(
    config: Config,
    knowledge_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    existing = read_knowledge_document(config, knowledge_id)
    expected = str(payload.get("version") or "")
    if not expected or expected != existing["version"]:
        raise RuntimeError("知识卡片已被其他操作修改，请刷新后重试。")
    markdown = _render_document(existing, payload)
    atomic_write_text(_find_knowledge_path(config, knowledge_id), markdown)
    return read_knowledge_document(config, knowledge_id)


def _read_qa_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    result: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            result.append(item)
    return result


def _write_qa_records(path: Path, items: Iterable[Dict[str, Any]]) -> None:
    payload = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items)
    atomic_write_text(path, payload)


def delete_knowledge_document(config: Config, knowledge_id: str) -> Dict[str, Any]:
    document = read_knowledge_document(config, knowledge_id)
    path = _find_knowledge_path(config, knowledge_id)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    trash_id = f"{timestamp}-{knowledge_id}-{uuid.uuid4().hex[:6]}"
    trash_dir = config.vault / ".trash" / "knowledge" / trash_id
    trash_dir.mkdir(parents=True, exist_ok=False)

    qa_path = config.vault / config.qa_file
    records = _read_qa_records(qa_path)
    linked = [
        item
        for item in records
        if document["source_session"]
        and str(item.get("source_session") or "") == document["source_session"]
    ]
    kept = [item for item in records if item not in linked]
    shutil.copy2(path, trash_dir / "document.md")
    if linked:
        _write_qa_records(trash_dir / "qa.jsonl", linked)
    manifest = {
        "trash_id": trash_id,
        "knowledge_id": knowledge_id,
        "original_path": str(path.relative_to(config.vault)).replace("\\", "/"),
        "source_session": document["source_session"],
        "title": document["title"],
        "project": document["project"],
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "qa_count": len(linked),
    }
    atomic_write_text(
        trash_dir / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    if qa_path.exists():
        _write_qa_records(qa_path, kept)
    path.unlink()
    return manifest


def list_knowledge_trash(config: Config) -> List[Dict[str, Any]]:
    root = config.vault / ".trash" / "knowledge"
    if not root.exists():
        return []
    result = []
    for manifest_path in root.glob("*/manifest.json"):
        try:
            item = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(item, dict):
            result.append(item)
    return sorted(result, key=lambda item: str(item.get("deleted_at") or ""), reverse=True)


def restore_knowledge_document(config: Config, trash_id: str) -> Dict[str, Any]:
    _validate_id(trash_id)
    trash_dir = config.vault / ".trash" / "knowledge" / trash_id
    manifest_path = trash_dir / "manifest.json"
    document_path = trash_dir / "document.md"
    if not manifest_path.exists() or not document_path.exists():
        raise FileNotFoundError(f"回收站记录不存在：{trash_id}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = config.vault / str(manifest["original_path"])
    if target.exists():
        raise FileExistsError(f"知识卡片已存在，无法覆盖恢复：{target.stem}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(document_path), str(target))

    qa_trash = trash_dir / "qa.jsonl"
    if qa_trash.exists():
        qa_path = config.vault / config.qa_file
        existing = _read_qa_records(qa_path)
        existing_ids = {str(item.get("id")) for item in existing if item.get("id")}
        restored = [
            item
            for item in _read_qa_records(qa_trash)
            if not item.get("id") or str(item.get("id")) not in existing_ids
        ]
        _write_qa_records(qa_path, [*existing, *restored])
    shutil.rmtree(trash_dir)
    return read_knowledge_document(config, str(manifest["knowledge_id"]))
