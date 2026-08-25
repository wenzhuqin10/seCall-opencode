from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .config import Config
from .structured_knowledge import (
    read_session_events,
    read_structured_knowledge,
    score_session_knowledge,
    store_structured_knowledge,
    structured_path,
)


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
    source_session = metadata.get("source_session") or ""
    structured = (
        read_structured_knowledge(config.vault, source_session)
        if source_session
        else None
    )
    return {
        "id": path.stem,
        "title": metadata.get("title") or heading,
        "heading": heading,
        "project": metadata.get("project") or "unknown",
        "source_session": source_session,
        "confidence": metadata.get("confidence") or "unknown",
        "review_status": metadata.get("review_status") or "pending",
        "type": metadata.get("type") or "issue",
        "intro": intro,
        "sections": sections,
        "markdown": markdown,
        "version": _document_version(markdown),
        "updated": int(path.stat().st_mtime * 1000),
        "structured": structured or {},
        "quality": dict((structured or {}).get("quality") or {}),
        "events": (
            read_session_events(config.vault, source_session)
            if source_session
            else []
        ),
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
                "quality": document["quality"],
            }
        )
    return result


def export_knowledge_markdown(config: Config, knowledge_id: str) -> Tuple[str, bytes]:
    """Return one formal knowledge card exactly as stored in the Vault."""

    path = _find_knowledge_path(config, knowledge_id)
    return f"{path.stem}.md", path.read_bytes()


def export_knowledge_bundle(
    config: Config, knowledge_ids: Iterable[str] | None = None
) -> Tuple[str, bytes]:
    """Create an in-memory Markdown-only archive of formal knowledge cards."""

    requested = [str(item) for item in (knowledge_ids or []) if str(item).strip()]
    if requested:
        seen: set[str] = set()
        paths = []
        for knowledge_id in requested:
            if knowledge_id in seen:
                continue
            seen.add(knowledge_id)
            paths.append(_find_knowledge_path(config, knowledge_id))
    else:
        root = _knowledge_root(config)
        paths = sorted(root.glob("*.md"), key=lambda item: item.name) if root.exists() else []
    if not paths:
        raise ValueError("当前没有可导出的正式知识卡片。")

    index_lines = [
        "# 知识中心 Markdown 导出",
        "",
        f"共导出 {len(paths)} 张正式知识卡片。",
        "",
        "## 文件目录",
        "",
    ]
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in paths:
            markdown = path.read_bytes()
            document = read_knowledge_document(config, path.stem)
            index_lines.append(f"- [{document['title']}]({path.name})")
            bundle.writestr(path.name, markdown)
        bundle.writestr("README.md", "\n".join(index_lines) + "\n")
    return "knowledge-center-markdown.zip", archive.getvalue()


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
    structured = read_structured_knowledge(
        config.vault, existing["source_session"]
    )
    if structured:
        section_map = {
            str(item.get("heading") or ""): str(item.get("content") or "")
            for item in payload.get("sections", [])
            if isinstance(item, dict)
        }

        def sync_record_list(field: str, section: str) -> None:
            if section not in section_map:
                return
            records = structured.get(field)
            if isinstance(records, list) and records and isinstance(records[0], dict):
                records[0]["description"] = section_map[section]
            elif section_map[section]:
                structured[field] = [
                    {"description": section_map[section], "evidence_event_ids": []}
                ]

        sync_record_list("symptoms", "问题现象")
        sync_record_list("timeline", "事件时间线")
        sync_record_list("troubleshooting_steps", "定位过程")
        root_cause = structured.setdefault("root_cause", {})
        if isinstance(root_cause, dict) and "根因分析" in section_map:
            root_cause["conclusion"] = section_map["根因分析"]
        fix = structured.setdefault("fix", {})
        if isinstance(fix, dict):
            if "修复方案" in section_map:
                fix["final_fix"] = section_map["修复方案"]
            if "代码变更" in section_map:
                fix["code_changes"] = section_map["代码变更"]
        verification = structured.setdefault("verification", {})
        if isinstance(verification, dict) and "验证方法" in section_map:
            verification["results"] = section_map["验证方法"]
        lessons = structured.setdefault("lessons", {})
        if isinstance(lessons, dict) and "经验总结" in section_map:
            lessons["diagnostic_rules"] = section_map["经验总结"]
        structured["project"] = str(payload.get("project") or existing["project"])
        structured["quality"] = score_session_knowledge(
            structured,
            read_session_events(config.vault, existing["source_session"]),
        )
        store_structured_knowledge(config.vault, structured)
    updated = read_knowledge_document(config, knowledge_id)
    if markdown != existing["markdown"]:
        mark_qa_stale_for_knowledge(
            config,
            knowledge_id,
            updated["version"],
            source_session=updated["source_session"],
        )
    return updated


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


def mark_qa_stale_for_knowledge(
    config: Config,
    knowledge_id: str,
    current_version: str,
    *,
    source_session: str = "",
) -> Dict[str, int]:
    """Invalidate QA derived from a changed knowledge card.

    QA is a derived representation of a card.  It must not remain searchable
    after the card body changes until a reviewer confirms the new wording.
    """

    path = config.vault / config.qa_file
    items = _read_qa_records(path)
    changed = 0
    for item in items:
        item_knowledge_id = str(item.get("knowledge_id") or "")
        # A populated knowledge_id is authoritative.  Only legacy records
        # without that field may fall back to the source session; otherwise
        # two historical cards created from one session would invalidate each
        # other's QA when one card changes.
        linked = item_knowledge_id == knowledge_id if item_knowledge_id else False
        if not item_knowledge_id and source_session:
            linked = str(item.get("source_session") or "") == source_session
        if not linked or str(item.get("review_status") or "pending") == "stale":
            continue
        status = str(item.get("review_status") or "pending")
        if status not in {"pending", "approved"}:
            continue
        item["previous_review_status"] = status
        item["review_status"] = "stale"
        item["stale_reason"] = "knowledge_updated"
        item["current_knowledge_version"] = current_version
        changed += 1
    if changed:
        _write_qa_records(path, items)
    return {"changed": changed, "total": len(items)}


def backfill_qa_metadata(config: Config) -> Dict[str, int]:
    """Link legacy QA records to cards and versions without changing answers."""

    path = config.vault / config.qa_file
    items = _read_qa_records(path)
    if not items:
        return {"updated": 0, "stale": 0, "total": 0}
    cards = list_knowledge_documents(config, limit=10000)
    by_id = {str(item.get("id")): item for item in cards}
    by_session: Dict[str, List[Dict[str, Any]]] = {}
    for item in cards:
        source = str(item.get("source_session") or "")
        if source:
            by_session.setdefault(source, []).append(item)
    updated = 0
    stale = 0
    for item in items:
        knowledge_id = str(item.get("knowledge_id") or "")
        card = by_id.get(knowledge_id)
        if card is None:
            matches = by_session.get(str(item.get("source_session") or ""), [])
            card = matches[0] if len(matches) == 1 else None
            if card is not None:
                item["knowledge_id"] = str(card.get("id") or "")
        if card is None:
            if item.get("review_status") in {"pending", "approved"}:
                item["previous_review_status"] = item.get("review_status")
                item["review_status"] = "stale"
                item["stale_reason"] = "knowledge_missing"
                stale += 1
                updated += 1
            continue
        detail = read_knowledge_document(config, str(card["id"]))
        version = str(detail.get("version") or "")
        if item.get("knowledge_version") != version:
            item["knowledge_version"] = version
            updated += 1
        item.setdefault("review_origin", "legacy")
        item.setdefault("source_session", detail.get("source_session", ""))
    if updated:
        _write_qa_records(path, items)
    return {"updated": updated, "stale": stale, "total": len(items)}


def _session_aliases(value: str) -> set[str]:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return set()
    aliases = {normalized}
    for token in re.findall(r"[0-9a-f]{8,}", normalized):
        aliases.add(token)
        aliases.add(token[:8])
    return aliases


def _qa_matches_knowledge(
    item: Dict[str, Any],
    *,
    knowledge_id: str,
    source_session: str,
) -> bool:
    item_knowledge_id = str(item.get("knowledge_id") or "")
    if item_knowledge_id:
        return item_knowledge_id == knowledge_id
    qa_source = str(item.get("source_session") or item.get("source") or "")
    return bool(_session_aliases(qa_source) & _session_aliases(source_session))


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
        if _qa_matches_knowledge(
            item,
            knowledge_id=knowledge_id,
            source_session=document["source_session"],
        )
    ]
    kept = [item for item in records if item not in linked]
    shutil.copy2(path, trash_dir / "document.md")
    structured = structured_path(config.vault, document["source_session"])
    if document["source_session"] and structured.exists():
        shutil.copy2(structured, trash_dir / "structured.json")
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
        "has_structured": (trash_dir / "structured.json").exists(),
    }
    atomic_write_text(
        trash_dir / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    if qa_path.exists():
        _write_qa_records(qa_path, kept)
    path.unlink()
    if document["source_session"] and structured.exists():
        structured.unlink()
    return manifest


def reconcile_qa_with_knowledge_trash(config: Config) -> Dict[str, Any]:
    """Move QA left behind by legacy session IDs into the matching knowledge trash."""

    qa_path = config.vault / config.qa_file
    records = _read_qa_records(qa_path)
    if not records:
        return {"moved": 0, "remaining": 0}
    manifests = list_knowledge_trash(config)
    if not manifests:
        return {"moved": 0, "remaining": len(records)}

    moved = 0
    remaining: List[Dict[str, Any]] = []
    for item in records:
        matched = next(
            (
                manifest
                for manifest in manifests
                if _qa_matches_knowledge(
                    item,
                    knowledge_id=str(manifest.get("knowledge_id") or ""),
                    source_session=str(manifest.get("source_session") or ""),
                )
            ),
            None,
        )
        if not matched:
            remaining.append(item)
            continue
        trash_dir = (
            config.vault
            / ".trash"
            / "knowledge"
            / str(matched["trash_id"])
        )
        trash_qa = trash_dir / "qa.jsonl"
        archived = _read_qa_records(trash_qa)
        archived_ids = {
            str(record.get("id"))
            for record in archived
            if record.get("id")
        }
        if not item.get("id") or str(item.get("id")) not in archived_ids:
            archived.append(item)
            _write_qa_records(trash_qa, archived)
        manifest_path = trash_dir / "manifest.json"
        matched["qa_count"] = len(archived)
        atomic_write_text(
            manifest_path,
            json.dumps(matched, ensure_ascii=False, indent=2) + "\n",
        )
        moved += 1
    if moved:
        _write_qa_records(qa_path, remaining)
    return {"moved": moved, "remaining": len(remaining)}


def purge_all_knowledge_derivatives(config: Config) -> Dict[str, Any]:
    """Permanently remove generated knowledge while preserving source sessions.

    The raw, staging and rejected session trees are deliberately outside the
    removal set. Search databases are rebuilt by the API layer after this
    function returns, so stale keyword and semantic entries are removed too.
    """

    vault = config.vault.resolve()

    def safe_target(path: Path) -> Path:
        resolved = path.resolve()
        if resolved == vault or vault not in resolved.parents:
            raise ValueError(f"拒绝清理 Vault 之外的路径：{resolved}")
        return resolved

    def inventory(path: Path) -> Tuple[int, int]:
        if not path.exists():
            return 0, 0
        if path.is_file():
            return 1, path.stat().st_size
        files = [item for item in path.rglob("*") if item.is_file()]
        return len(files), sum(item.stat().st_size for item in files)

    targets = [
        vault / "wiki",
        vault / "graph" / "graph.json",
        vault / config.qa_file,
        vault / "knowledge" / "events",
        vault / "knowledge" / "structured",
        vault / ".trash" / "wiki",
        vault / ".trash" / "knowledge",
    ]
    # A custom knowledge directory may live outside the default wiki/issues path.
    targets.append(vault / config.knowledge_dir)

    unique_targets: List[Path] = []
    for raw_target in targets:
        target = safe_target(raw_target)
        if any(target == known or known in target.parents for known in unique_targets):
            continue
        unique_targets = [
            known for known in unique_targets if target not in known.parents
        ]
        unique_targets.append(target)

    removed_files = 0
    removed_bytes = 0
    removed_paths: List[str] = []
    for target in unique_targets:
        files, size = inventory(target)
        if not target.exists():
            continue
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        removed_files += files
        removed_bytes += size
        removed_paths.append(str(target.relative_to(vault)).replace("\\", "/"))

    raw_root = vault / "raw" / ".sessions"
    preserved_sessions = (
        sum(1 for path in raw_root.rglob("*.md")) if raw_root.exists() else 0
    )
    return {
        "purged": True,
        "removed_files": removed_files,
        "removed_bytes": removed_bytes,
        "removed_paths": removed_paths,
        "preserved_sessions": preserved_sessions,
    }


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
    structured_trash = trash_dir / "structured.json"
    source_session = str(manifest.get("source_session") or "")
    structured_target = (
        structured_path(config.vault, source_session) if source_session else None
    )
    if structured_trash.exists() and structured_target and structured_target.exists():
        raise FileExistsError(
            f"结构化知识已存在，无法覆盖恢复：{source_session}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(document_path), str(target))

    if structured_trash.exists() and structured_target:
        structured_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(structured_trash), str(structured_target))

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
