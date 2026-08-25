from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .config import Config
from .knowledge_store import (
    atomic_write_text,
    list_knowledge_documents,
    read_knowledge_document,
)
from .structured_knowledge import read_structured_knowledge, write_json_atomic


WIKI_SCHEMA_VERSION = 2
WIKI_PLAN_VERSION = 1
PAGE_CATEGORIES = (
    "overview",
    "projects",
    "modules",
    "topics",
    "issues",
    "decisions",
    "runbooks",
    "tests",
)
PURPOSE_TEMPLATE = """# seCall 持续演化知识库目标

本 Wiki 用于沉淀基带研发会话中可追溯、可复用的工程知识。它不是原始会话的副本，
而是由已审核知识卡片持续维护的共识层。

## 基本原则

- 每条工程主张必须能够追溯到来源 Session 和证据事件。
- 新知识先形成更新计划和 Markdown Diff，经审核后写入。
- 发生冲突时保留不同版本或场景下的双方主张，不静默覆盖。
- 文件、函数、提交、根因和测试用例默认作为 Issue 证据属性，不扩展为图谱实体。
- Wiki Markdown 是事实来源；索引、图谱和缓存均可重建。
"""
SCHEMA_TEMPLATE = """# Wiki Schema

## 页面类型

`overview`、`projects`、`modules`、`topics`、`issues`、`decisions`、`runbooks`、`tests`。

## 页面元数据

每页必须包含稳定的 `id`、`type`、`sources`、`source_count`、`updated_at`、
`review_status`、`content_hash` 和 `schema_version`。

## 关系与命名

- 页面 ID 使用分类与规范化名称组成，创建后保持稳定。
- Issue 链接到项目、模块、主题和来源会话。
- Topic 链接到 Issue、Runbook 和 Test；Decision 链接到影响模块和来源。
- 设计决策只有在存在方案比较、选择理由和影响范围时才能创建。

## 生命周期

- 模型生成的跨页面变更必须先审核。
- 知识卡片删除、恢复和永久删除触发确定性派生同步。
- 页面归档会写入 tombstone，普通重建不得自动复活；显式重新生成可以创建替代页。
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    value = value.strip().lower().replace("_", "-")
    value = re.sub(r"[\\/:*?\"<>|#\[\]]+", "-", value)
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-.")
    return value[:96] or "untitled"


def _unique(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _wiki_root(config: Config) -> Path:
    return config.vault / "wiki"


def _meta_root(config: Config) -> Path:
    return _wiki_root(config) / ".meta"


def _plans_root(config: Config) -> Path:
    return config.vault / "knowledge" / "wiki-plans"


def _page_path(config: Config, page_id: str) -> Path:
    category, slug = page_id.split("/", 1)
    if category not in PAGE_CATEGORIES:
        raise ValueError(f"未知 Wiki 页面类型：{category}")
    return (
        _wiki_root(config) / "overview.md"
        if category == "overview"
        else _wiki_root(config) / category / f"{slug}.md"
    )


def ensure_wiki_schema(config: Config) -> Dict[str, Any]:
    root = _wiki_root(config)
    root.mkdir(parents=True, exist_ok=True)
    for category in PAGE_CATEGORIES[1:]:
        (root / category).mkdir(parents=True, exist_ok=True)
    meta = _meta_root(config)
    meta.mkdir(parents=True, exist_ok=True)
    created: List[str] = []
    defaults = {
        root / "purpose.md": PURPOSE_TEMPLATE,
        root / "schema.md": SCHEMA_TEMPLATE,
        meta / "page-registry.json": {
            "schema_version": WIKI_SCHEMA_VERSION,
            "pages": {},
            "tombstones": {},
            "updated_at": _now(),
        },
        meta / "source-dependencies.json": {
            "schema_version": WIKI_SCHEMA_VERSION,
            "sources": {},
            "updated_at": _now(),
        },
        meta / "ingest-cache.json": {
            "schema_version": WIKI_SCHEMA_VERSION,
            "sources": {},
            "updated_at": _now(),
        },
    }
    for path, value in defaults.items():
        if path.exists():
            continue
        if isinstance(value, str):
            atomic_write_text(path, value.rstrip() + "\n")
        else:
            write_json_atomic(path, value)
        created.append(str(path.relative_to(config.vault)).replace("\\", "/"))
    return {"created": created, "schema_version": WIKI_SCHEMA_VERSION}


def get_wiki_config(config: Config) -> Dict[str, Any]:
    ensure_wiki_schema(config)
    root = _wiki_root(config)
    return {
        "schema_version": WIKI_SCHEMA_VERSION,
        "categories": list(PAGE_CATEGORIES),
        "purpose": (root / "purpose.md").read_text(encoding="utf-8"),
        "schema": (root / "schema.md").read_text(encoding="utf-8"),
        "review_before_write": True,
    }


def build_wiki_analysis_prompt(config: Config, base_prompt: Path) -> Path:
    """Compose the extractor prompt with the active purpose and schema."""
    ensure_wiki_schema(config)
    root = _wiki_root(config)
    destination = config.vault / "knowledge" / ".runtime" / "wiki-analysis-prompt.md"
    content = (
        base_prompt.read_text(encoding="utf-8").rstrip()
        + "\n\n# 当前 Wiki 目标\n\n"
        + (root / "purpose.md").read_text(encoding="utf-8")
        + "\n\n# 当前 Wiki Schema\n\n"
        + (root / "schema.md").read_text(encoding="utf-8")
    )
    atomic_write_text(destination, content.rstrip() + "\n")
    return destination


def update_wiki_config(config: Config, payload: Mapping[str, Any]) -> Dict[str, Any]:
    ensure_wiki_schema(config)
    root = _wiki_root(config)
    changed: List[str] = []
    for key in ("purpose", "schema"):
        if key not in payload:
            continue
        value = str(payload[key]).strip()
        if not value:
            raise ValueError(f"{key} 不能为空。")
        atomic_write_text(root / f"{key}.md", value + "\n")
        changed.append(f"wiki/{key}.md")
    return {**get_wiki_config(config), "changed": changed}


def _records(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)] if value else []
    if not isinstance(value, list):
        return []
    return [dict(item) if isinstance(item, Mapping) else {"description": str(item)} for item in value]


def _string_values(value: Any) -> List[str]:
    """Normalize an entity field without iterating a string by character."""
    raw = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    return _unique(str(item) for item in raw if not isinstance(item, Mapping))


def _valid_page_name(value: str) -> bool:
    """Reject character fragments and malformed model output as Wiki entities."""
    clean = value.strip()
    return len(clean) >= 2 and "�" not in clean and any(char.isalnum() for char in clean)


def _stable_module_name(value: str) -> str:
    """Accept explicit business module names, not paths or source files."""

    clean = str(value or "").strip()
    if not _valid_page_name(clean):
        return ""
    if any(separator in clean for separator in ("/", "\\")):
        return ""
    if re.search(r"\.(?:c|cc|cpp|h|hpp|py|js|ts|tsx|java|rs|go)$", clean, re.IGNORECASE):
        return ""
    if len(clean) > 64 or re.fullmatch(r"[A-Za-z]", clean):
        return ""
    return clean


def _explicit_wiki_request(enriched: Mapping[str, Any], category: str, name: str) -> bool:
    """Check the structured extractor's explicit page request, if present."""

    structured = enriched.get("structured") or {}
    if category == "modules":
        # A stable module emitted in code_entities is an explicit business
        # boundary.  Paths and leaf directories were filtered by
        # _stable_module_name before reaching this function.
        raw_modules = (structured.get("code_entities") or {}).get("modules", [])
        if name.casefold() in {_stable_module_name(value).casefold() for value in _string_values(raw_modules)}:
            return True
    if category == "topics":
        # A topic with both a description and event evidence is already a
        # confirmed structured claim, even when older sidecars predate
        # wiki_actions.
        for topic in _records(structured.get("topics")):
            if _record_text(topic).casefold() == name.casefold() and (
                topic.get("description") and topic.get("evidence_event_ids")
            ):
                return True
    for raw in _records(structured.get("wiki_actions")):
        action = str(raw.get("action") or raw.get("operation") or "").casefold()
        if action and action in {"ignore", "skip", "archive", "delete"}:
            continue
        raw_category = str(raw.get("category") or raw.get("page_type") or raw.get("type") or "").casefold()
        raw_name = _record_text(raw) or str(raw.get("target") or raw.get("page") or "").strip()
        normalized_category = {"project": "projects", "module": "modules", "topic": "topics"}.get(raw_category, raw_category)
        if normalized_category == category and raw_name.casefold() == name.casefold():
            return True
    return False


def _distinct_card_ids(items: Sequence[Mapping[str, Any]]) -> set[str]:
    return {
        str(item.get("id") or item.get("detail", {}).get("id") or item.get("source_session") or "")
        for item in items
        if str(item.get("id") or item.get("detail", {}).get("id") or item.get("source_session") or "")
    }


def _has_runbook_evidence(item: Mapping[str, Any]) -> bool:
    record = item.get("record") or {}
    steps = record.get("steps") or record.get("procedure")
    if not isinstance(steps, (list, tuple)) or not steps:
        return False
    has_scope = any(record.get(key) for key in ("preconditions", "conditions", "scope", "applicable_when"))
    has_verification = any(record.get(key) for key in ("verification", "completion", "expected", "result", "outcome"))
    grounded = bool(record.get("evidence_event_ids"))
    return (has_scope and has_verification) or grounded


def _has_test_evidence(item: Mapping[str, Any]) -> bool:
    record = item.get("record") or {}
    has_input = any(record.get(key) for key in ("input", "inputs", "environment", "test_input", "description"))
    has_process = any(record.get(key) for key in ("steps", "procedure", "process", "command"))
    has_result = any(record.get(key) for key in ("result", "results", "actual", "outcome", "expected"))
    grounded = bool(record.get("evidence_event_ids"))
    return (has_input and has_process and has_result) or (grounded and has_input)


def _record_text(item: Mapping[str, Any]) -> str:
    for key in ("name", "title", "topic", "claim", "description", "conclusion", "question"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _record_sources(item: Mapping[str, Any], session_id: str) -> Dict[str, Any]:
    return {
        "source_session": str(item.get("source_session") or session_id),
        "evidence_event_ids": _unique(item.get("evidence_event_ids") or []),
        "scope": str(item.get("scope") or item.get("scenario") or ""),
        "version": str(item.get("version") or item.get("applicable_version") or ""),
        "confidence": str(item.get("confidence") or "unknown"),
    }


def _page_markdown(
    *,
    page_id: str,
    page_type: str,
    title: str,
    sources: Sequence[str],
    project: str,
    body: str,
    review_status: str = "approved",
) -> str:
    updated_at = _now()
    source_values = _unique(sources)
    content_hash = _hash(body.strip())
    frontmatter = [
        "---",
        f"id: {json.dumps(page_id, ensure_ascii=False)}",
        f"type: {page_type}",
        f"title: {json.dumps(title, ensure_ascii=False)}",
        f"project: {json.dumps(project, ensure_ascii=False)}",
        f"sources: {json.dumps(source_values, ensure_ascii=False)}",
        f"source_count: {len(source_values)}",
        f"updated_at: {updated_at}",
        f"review_status: {review_status}",
        f"content_hash: {content_hash}",
        f"schema_version: {WIKI_SCHEMA_VERSION}",
        "---",
        "",
    ]
    return "\n".join(frontmatter) + body.strip() + "\n"


def _claim_lines(records: Sequence[Mapping[str, Any]], session_id: str) -> List[str]:
    lines: List[str] = []
    for item in records:
        text = _record_text(item)
        if not text:
            continue
        evidence = _unique(item.get("evidence_event_ids") or [])
        suffix = f"（来源：`{session_id}`"
        if evidence:
            suffix += f"；证据：{', '.join(f'`{item}`' for item in evidence)}"
        scope = str(item.get("scope") or item.get("scenario") or "").strip()
        if scope:
            suffix += f"；范围：{scope}"
        suffix += "）"
        lines.append(f"- {text} {suffix}")
    return lines


def _desired_pages(config: Config) -> Dict[str, Dict[str, Any]]:
    cards = list_knowledge_documents(config, limit=1000)
    desired: Dict[str, Dict[str, Any]] = {}
    if not cards:
        return desired
    projects: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    modules: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    topics: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    decisions: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    runbooks: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    tests: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for card in cards:
        detail = read_knowledge_document(config, str(card["id"]))
        session_id = str(detail.get("source_session") or "")
        structured = read_structured_knowledge(config.vault, session_id) or {}
        enriched = {**card, "detail": detail, "structured": structured}
        projects[str(card.get("project") or "未分类")].append(enriched)
        raw_modules = (structured.get("code_entities") or {}).get("modules", [])
        for module in _string_values(raw_modules):
            stable_module = _stable_module_name(module)
            if stable_module:
                modules[stable_module].append(enriched)
        for item in _records(structured.get("topics")):
            name = _record_text(item)
            if name:
                topics[name].append({**enriched, "record": item, "record_kind": "topic"})
        topic_names = [_record_text(item) for item in _records(structured.get("topics"))]
        for item in _records(structured.get("claims")):
            target_topic = str(item.get("topic") or item.get("subject") or "").strip()
            if not target_topic and len([name for name in topic_names if name]) == 1:
                target_topic = next(name for name in topic_names if name)
            if target_topic and _record_text(item):
                topics[target_topic].append({**enriched, "record": item, "record_kind": "claim"})
        for item in _records(structured.get("decisions")):
            options = item.get("options") or item.get("alternatives")
            rationale = item.get("rationale") or item.get("reason")
            impact = item.get("impact") or item.get("scope")
            name = _record_text(item)
            if name and options and rationale and impact:
                decisions[name].append({**enriched, "record": item})
        for item in _records(structured.get("runbook")):
            steps = item.get("steps") or item.get("procedure")
            name = _record_text(item) or str(detail.get("title") or "")
            if name and steps and _has_runbook_evidence({**enriched, "record": item}):
                runbooks[name].append({**enriched, "record": item})
        test_records = _records(structured.get("test_knowledge"))
        verification = structured.get("verification") or {}
        raw_cases = verification.get("test_cases", []) if isinstance(verification, Mapping) else []
        if isinstance(raw_cases, list):
            for case in raw_cases:
                if isinstance(case, Mapping):
                    test_records.append(dict(case))
                elif _valid_page_name(str(case)):
                    test_records.append({"name": str(case), "description": str(case)})
        for item in test_records:
            name = _record_text(item)
            if name and _valid_page_name(name) and _has_test_evidence({**enriched, "record": item}):
                tests[name].append({**enriched, "record": item})

    # Aggregates are intentionally conservative.  A single card is the
    # canonical source, not enough evidence for a new module/topic page unless
    # the extractor recorded an explicit Wiki action.
    modules = {
        name: items
        for name, items in modules.items()
        if len(_distinct_card_ids(items)) >= 2
        or any(_explicit_wiki_request(item, "modules", name) for item in items)
    }
    topics = {
        name: items
        for name, items in topics.items()
        if len(items) >= 2
        or any(_explicit_wiki_request(item, "topics", name) for item in items)
    }

    overview_sources = _unique(str(card.get("source_session") or "") for card in cards)
    overview_lines = [
        "# 知识库总览",
        "",
        "## 当前共识",
        "",
        f"当前持续维护 **{len(cards)}** 张有效知识卡片，覆盖 **{len(projects)}** 个项目、"
        f"**{len(modules)}** 个模块和 **{len(topics)}** 个技术主题。",
        "",
        "## 知识目录",
        "",
    ]
    overview_lines.extend(f"- [[projects/{_slug(name)}|{name}]]" for name in sorted(projects))
    if modules:
        overview_lines.extend(["", "### 模块", ""])
        overview_lines.extend(f"- [[modules/{_slug(name)}|{name}]]" for name in sorted(modules))
    if topics:
        overview_lines.extend(["", "### 技术主题", ""])
        overview_lines.extend(f"- [[topics/{_slug(name)}|{name}]]" for name in sorted(topics))
    desired["overview/overview"] = {
        "title": "知识库总览", "type": "overview", "project": "全部项目",
        "sources": overview_sources, "body": "\n".join(overview_lines),
    }

    for project, items in projects.items():
        sources = _unique(str(item.get("source_session") or "") for item in items)
        issue_lines = [f"- [[issues/{item['id']}|{item['title']}]]" for item in items]
        body = "\n".join([
            f"# {project}", "", "## 当前共识", "",
            f"本项目当前沉淀 {len(items)} 张有效知识卡片。", "",
            "## 相关问题", "", *issue_lines, "", "## 未解决项", "",
            "- 由后续会话和冲突审核持续补充。",
        ])
        desired[f"projects/{_slug(project)}"] = {
            "title": project, "type": "project", "project": project,
            "sources": sources, "body": body,
        }

    for module, items in modules.items():
        sources = _unique(str(item.get("source_session") or "") for item in items)
        body = "\n".join([
            f"# {module} 模块", "", "## 当前共识", "",
            f"该模块与 {len(items)} 个已审核问题相关。", "", "## 相关问题", "",
            *[f"- [[issues/{item['id']}|{item['title']}]]" for item in items],
            "", "## 来源", "", *[f"- `{source}`" for source in sources],
        ])
        desired[f"modules/{_slug(module)}"] = {
            "title": f"{module} 模块", "type": "module", "project": "多项目",
            "sources": sources, "body": body,
        }

    for topic, items in topics.items():
        sources = _unique(str(item.get("source_session") or "") for item in items)
        claims: List[str] = []
        for item in items:
            claims.extend(_claim_lines([item["record"]], str(item.get("source_session") or "")))
        conflicts = [
            {
                "claim": _record_text(item["record"]),
                "contradicts": item["record"].get("contradicts"),
                "source_session": item.get("source_session"),
            }
            for item in items
            if item["record"].get("contradicts")
        ]
        body = "\n".join([
            f"# {topic}", "", "## 当前共识", "", *(claims or ["- 尚无可直接引用的主张。"]),
            "", "## 相关问题", "",
            *[f"- [[issues/{item['id']}|{item['title']}]]" for item in items],
            "", "## 未解决项", "", "- 新旧主张冲突时在审核计划中处理。",
            *(
                ["", "## 冲突主张", ""]
                + [f"- {item['claim']} ↔ {item['contradicts']}（来源：`{item['source_session']}`）" for item in conflicts]
                if conflicts else []
            ),
        ])
        desired[f"topics/{_slug(topic)}"] = {
            "title": topic, "type": "topic", "project": "多项目",
            "sources": sources, "body": body,
            "conflicts": conflicts,
        }

    for collection, category, page_type, heading in (
        (decisions, "decisions", "decision", "设计决策"),
        (runbooks, "runbooks", "runbook", "运行手册"),
        (tests, "tests", "test", "测试知识"),
    ):
        for name, items in collection.items():
            sources = _unique(str(item.get("source_session") or "") for item in items)
            descriptions = _claim_lines([item["record"] for item in items], sources[0] if sources else "")
            body = "\n".join([
                f"# {name}", "", f"## {heading}", "", *(descriptions or ["- 待补充。"]),
                "", "## 来源", "", *[f"- `{source}`" for source in sources],
            ])
            desired[f"{category}/{_slug(name)}"] = {
                "title": name, "type": page_type, "project": "多项目",
                "sources": sources, "body": body,
            }
    return desired


def _render_desired_pages(config: Config) -> Dict[str, Dict[str, Any]]:
    pages = _desired_pages(config)
    for page_id, page in pages.items():
        page["markdown"] = _page_markdown(
            page_id=page_id,
            page_type=str(page["type"]),
            title=str(page["title"]),
            sources=list(page["sources"]),
            project=str(page["project"]),
            body=str(page["body"]),
        )
    return pages


def _diff(old: str, new: str, path: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}",
    ))


def _same_page_content(old: str, new: str) -> bool:
    if old == new:
        return True
    old_content = re.search(r"(?m)^content_hash:\s*(\S+)\s*$", old)
    new_content = re.search(r"(?m)^content_hash:\s*(\S+)\s*$", new)
    old_sources = re.search(r"(?m)^sources:\s*(.+)$", old)
    new_sources = re.search(r"(?m)^sources:\s*(.+)$", new)
    return bool(
        old_content
        and new_content
        and old_content.group(1) == new_content.group(1)
        and (old_sources.group(1) if old_sources else "[]")
        == (new_sources.group(1) if new_sources else "[]")
    )


def create_wiki_plan(config: Config, *, reason: str = "pipeline", regenerate: bool = False) -> Dict[str, Any]:
    ensure_wiki_schema(config)
    desired = _render_desired_pages(config)
    registry = _json(_meta_root(config) / "page-registry.json", {"pages": {}, "tombstones": {}})
    tombstones = registry.get("tombstones") if isinstance(registry, Mapping) else {}
    changes: List[Dict[str, Any]] = []
    input_parts: List[str] = []
    for page_id, page in sorted(desired.items()):
        if page_id in (tombstones or {}) and not regenerate:
            continue
        path = _page_path(config, page_id)
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        new = str(page["markdown"])
        input_parts.append(f"{page_id}:{_hash(new)}")
        if _same_page_content(old, new):
            continue
        relative = str(path.relative_to(config.vault)).replace("\\", "/")
        changes.append({
            "change_id": uuid.uuid4().hex[:12],
            "page_id": page_id,
            "category": page_id.split("/", 1)[0],
            "title": page["title"],
            "action": "update" if old else "create",
            "path": relative,
            "sources": page["sources"],
            "base_hash": _hash(old) if old else "",
            "new_hash": _hash(new),
            "markdown": new,
            "diff": _diff(old, new, relative),
            "conflicts": list(page.get("conflicts") or []),
        })
    for page_id, registered in sorted((registry.get("pages") or {}).items()):
        if page_id in desired or page_id.split("/", 1)[0] == "issues":
            continue
        path = config.vault / str(registered.get("path") or "")
        if not path.is_file():
            continue
        old = path.read_text(encoding="utf-8")
        if not re.search(r"(?m)^schema_version:\s*2\s*$", old):
            continue
        relative = str(path.relative_to(config.vault)).replace("\\", "/")
        changes.append({
            "change_id": uuid.uuid4().hex[:12],
            "page_id": page_id,
            "category": page_id.split("/", 1)[0],
            "title": page_id.split("/", 1)[1],
            "action": "archive",
            "path": relative,
            "sources": list(registered.get("sources") or []),
            "base_hash": _hash(old),
            "new_hash": "",
            "markdown": "",
            "diff": _diff(old, "", relative),
            "conflicts": [],
        })
    plan_id = f"wiki-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    plan = {
        "schema_version": WIKI_PLAN_VERSION,
        "plan_id": plan_id,
        "status": "pending",
        "reason": reason,
        "created_at": _now(),
        "updated_at": _now(),
        "input_hash": _hash("\n".join(input_parts)),
        "requires_review": bool(changes),
        "changes": changes,
        "summary": {
            "total": len(changes),
            "create": sum(item["action"] == "create" for item in changes),
            "update": sum(item["action"] == "update" for item in changes),
            "archive": sum(item["action"] == "archive" for item in changes),
        },
    }
    path = _plans_root(config) / f"{plan_id}.json"
    write_json_atomic(path, plan)
    return plan


def list_wiki_plans(config: Config, status: str = "all") -> List[Dict[str, Any]]:
    root = _plans_root(config)
    if not root.exists():
        return []
    result: List[Dict[str, Any]] = []
    for path in root.glob("*.json"):
        value = _json(path, {})
        if not isinstance(value, Mapping):
            continue
        if status != "all" and value.get("status") != status:
            continue
        result.append({
            "plan_id": value.get("plan_id"), "status": value.get("status"),
            "reason": value.get("reason"), "created_at": value.get("created_at"),
            "updated_at": value.get("updated_at"), "requires_review": value.get("requires_review"),
            "summary": value.get("summary") or {},
        })
    return sorted(result, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def read_wiki_plan(config: Config, plan_id: str) -> Dict[str, Any]:
    if not re.fullmatch(r"[0-9A-Za-z._-]+", plan_id):
        raise ValueError("Wiki 计划 ID 无效。")
    path = _plans_root(config) / f"{plan_id}.json"
    value = _json(path, None)
    if not isinstance(value, dict):
        raise FileNotFoundError(f"Wiki 更新计划不存在：{plan_id}")
    return value


def _registry_from_disk(config: Config) -> Dict[str, Any]:
    registry = _json(_meta_root(config) / "page-registry.json", {})
    if not isinstance(registry, dict):
        registry = {}
    registry.setdefault("schema_version", WIKI_SCHEMA_VERSION)
    registry.setdefault("pages", {})
    registry.setdefault("tombstones", {})
    return registry


def _rebuild_registry_documents(config: Config, registry: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    pages: Dict[str, Any] = {}
    dependencies: Dict[str, List[str]] = defaultdict(list)
    for category in PAGE_CATEGORIES:
        paths = [(_wiki_root(config) / "overview.md")] if category == "overview" else list((_wiki_root(config) / category).glob("*.md"))
        for path in paths:
            if not path.is_file():
                continue
            slug = "overview" if category == "overview" else path.stem
            page_id = f"{category}/{slug}"
            markdown = path.read_text(encoding="utf-8")
            match = re.search(r"(?m)^sources:\s*(.+)$", markdown)
            try:
                sources = json.loads(match.group(1)) if match else []
            except json.JSONDecodeError:
                sources = []
            if not sources:
                source_match = re.search(r"(?m)^source_session:\s*[\"']?([^\n\"']+)", markdown)
                if source_match and source_match.group(1).strip():
                    sources = [source_match.group(1).strip()]
            pages[page_id] = {
                "id": page_id, "type": category.rstrip("s"),
                "path": str(path.relative_to(config.vault)).replace("\\", "/"),
                "content_hash": _hash(markdown), "sources": sources,
                "source_count": len(sources), "updated_at": _now(), "tombstone": False,
            }
            for source in sources:
                dependencies[str(source)].append(page_id)
    registry["pages"] = pages
    registry["updated_at"] = _now()
    dependency_doc = {
        "schema_version": WIKI_SCHEMA_VERSION,
        "sources": {key: sorted(_unique(value)) for key, value in dependencies.items()},
        "updated_at": _now(),
    }
    return registry, dependency_doc


def _render_index(registry: Mapping[str, Any]) -> str:
    grouped: Dict[str, List[str]] = defaultdict(list)
    for page_id in (registry.get("pages") or {}):
        category, slug = str(page_id).split("/", 1)
        grouped[category].append(f"- [[{page_id}|{slug}]]")
    labels = {
        "overview": "知识总览", "projects": "项目", "modules": "模块",
        "topics": "技术主题", "issues": "问题定位", "decisions": "设计决策",
        "runbooks": "运行手册", "tests": "测试知识",
    }
    lines = ["# Wiki 知识目录", "", "> 此页面由已应用的 Wiki 更新计划自动维护。", ""]
    for category in PAGE_CATEGORIES:
        items = grouped.get(category, [])
        if items:
            lines.extend([f"## {labels[category]}", "", *sorted(items), ""])
    return "\n".join(lines).rstrip() + "\n"


def apply_wiki_plan(config: Config, plan_id: str, selected: Sequence[str] | None = None) -> Dict[str, Any]:
    plan = read_wiki_plan(config, plan_id)
    if plan.get("status") != "pending":
        raise ValueError("只有 pending 状态的 Wiki 计划可以应用。")
    selected_set = set(selected or [item["change_id"] for item in plan.get("changes", [])])
    changes = [item for item in plan.get("changes", []) if item.get("change_id") in selected_set]
    for item in changes:
        path = config.vault / str(item["path"])
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        current_hash = _hash(current) if current else ""
        if current_hash != str(item.get("base_hash") or ""):
            plan["status"] = "conflict"
            plan["updated_at"] = _now()
            plan["conflict_page"] = item["page_id"]
            write_json_atomic(_plans_root(config) / f"{plan_id}.json", plan)
            raise RuntimeError(f"Wiki 页面在审核期间已变化：{item['page_id']}")

    backup_root = Path(tempfile.mkdtemp(prefix="secall-wiki-transaction-"))
    written: List[Path] = []
    backups: Dict[Path, Path | None] = {}

    def transaction_write(path: Path, content: str) -> None:
        if path not in backups:
            if path.exists():
                backup = backup_root / f"{len(backups)}.bak"
                shutil.copy2(path, backup)
                backups[path] = backup
            else:
                backups[path] = None
            written.append(path)
        atomic_write_text(path, content)

    def transaction_delete(path: Path) -> None:
        if path not in backups:
            if not path.exists():
                return
            backup = backup_root / f"{len(backups)}.bak"
            shutil.copy2(path, backup)
            backups[path] = backup
            written.append(path)
        path.unlink(missing_ok=True)

    try:
        for item in changes:
            path = config.vault / str(item["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            if item.get("action") == "archive":
                archived_at = _now()
                trash_id = (
                    f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-"
                    f"{item['category']}-{item['page_id'].split('/', 1)[1]}-{uuid.uuid4().hex[:6]}"
                )
                trash_dir = config.vault / ".trash" / "wiki" / trash_id
                old_markdown = path.read_text(encoding="utf-8")
                manifest = {
                    "trash_id": trash_id,
                    "wiki_id": item["page_id"],
                    "category": item["category"],
                    "category_label": item["category"],
                    "slug": item["page_id"].split("/", 1)[1],
                    "title": item["title"],
                    "project": "",
                    "source_session": "",
                    "original_path": item["path"],
                    "archived_at": archived_at,
                    "plan_id": plan_id,
                }
                transaction_write(trash_dir / "document.md", old_markdown)
                transaction_write(
                    trash_dir / "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                )
                transaction_delete(path)
                item["trash_id"] = trash_id
            else:
                transaction_write(path, str(item.get("markdown") or ""))
        registry = _registry_from_disk(config)
        for item in changes:
            page_id = str(item.get("page_id") or "")
            if item.get("action") == "archive":
                previous = (registry.get("pages") or {}).pop(page_id, None)
                registry.setdefault("tombstones", {})[page_id] = {
                    "page_id": page_id,
                    "archived_at": _now(),
                    "previous": previous or {},
                    "trash_id": item.get("trash_id"),
                }
            else:
                (registry.get("tombstones") or {}).pop(page_id, None)
        registry, dependencies = _rebuild_registry_documents(config, registry)
        transaction_write(_wiki_root(config) / "index.md", _render_index(registry))
        log_path = _wiki_root(config) / "log.md"
        old_log = log_path.read_text(encoding="utf-8") if log_path.exists() else "# Wiki 变更日志\n"
        entry = ["", f"## {_now()} · {plan_id}", "", f"- 原因：{plan.get('reason')}"]
        entry.extend(f"- {item['action']} `{item['page_id']}`" for item in changes)
        transaction_write(log_path, old_log.rstrip() + "\n" + "\n".join(entry) + "\n")
        transaction_write(
            _meta_root(config) / "page-registry.json",
            json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        )
        transaction_write(
            _meta_root(config) / "source-dependencies.json",
            json.dumps(dependencies, ensure_ascii=False, indent=2) + "\n",
        )
        cache = {
            "schema_version": WIKI_SCHEMA_VERSION,
            "sources": {
                source: {"page_ids": page_ids, "processed_at": _now(), "plan_id": plan_id}
                for source, page_ids in dependencies["sources"].items()
            },
            "updated_at": _now(),
        }
        transaction_write(
            _meta_root(config) / "ingest-cache.json",
            json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
        )
    except Exception:
        for path in reversed(written):
            backup = backups.get(path)
            if backup and backup.exists():
                shutil.copy2(backup, path)
            elif path.exists():
                path.unlink()
        for directory in sorted(
            {path.parent for path in written if ".trash" in path.parts},
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        raise
    finally:
        shutil.rmtree(backup_root, ignore_errors=True)
    plan["status"] = "applied"
    plan["updated_at"] = _now()
    plan["applied_change_ids"] = sorted(selected_set)
    write_json_atomic(_plans_root(config) / f"{plan_id}.json", plan)
    return {"plan_id": plan_id, "status": "applied", "applied": len(changes), "changes": changes}


def reject_wiki_plan(config: Config, plan_id: str, reason: str = "") -> Dict[str, Any]:
    plan = read_wiki_plan(config, plan_id)
    if plan.get("status") != "pending":
        raise ValueError("只有 pending 状态的 Wiki 计划可以拒绝。")
    plan["status"] = "rejected"
    plan["rejection_reason"] = reason.strip()
    plan["updated_at"] = _now()
    write_json_atomic(_plans_root(config) / f"{plan_id}.json", plan)
    return plan


def mark_wiki_tombstone(config: Config, page_id: str, *, archived_at: str | None = None) -> None:
    ensure_wiki_schema(config)
    registry = _registry_from_disk(config)
    page = (registry.get("pages") or {}).pop(page_id, None)
    registry.setdefault("tombstones", {})[page_id] = {
        "page_id": page_id, "archived_at": archived_at or _now(), "previous": page or {},
    }
    registry["updated_at"] = _now()
    write_json_atomic(_meta_root(config) / "page-registry.json", registry)


def clear_wiki_tombstone(config: Config, page_id: str) -> None:
    registry = _registry_from_disk(config)
    (registry.get("tombstones") or {}).pop(page_id, None)
    registry["updated_at"] = _now()
    write_json_atomic(_meta_root(config) / "page-registry.json", registry)


def deterministic_reconcile(config: Config, *, allow_create: bool = False) -> Dict[str, Any]:
    """Immediately remove stale derived references after source lifecycle changes."""
    ensure_wiki_schema(config)
    valid_sources = {
        str(item.get("source_session") or "")
        for item in list_knowledge_documents(config, limit=1000)
    }
    registry = _registry_from_disk(config)
    removed: List[str] = []
    updated: List[str] = []
    desired = _render_desired_pages(config)
    tombstones = registry.get("tombstones") or {}
    for page_id, page in list((registry.get("pages") or {}).items()):
        sources = set(str(item) for item in page.get("sources", []))
        category = page_id.split("/", 1)[0]
        if category == "issues":
            continue
        replacement = desired.get(page_id)
        if replacement is not None:
            path = config.vault / str(page.get("path") or "")
            markdown = str(replacement["markdown"])
            current = path.read_text(encoding="utf-8") if path.is_file() else ""
            managed_v2 = bool(re.search(r"(?m)^schema_version:\s*2\s*$", current))
            if managed_v2 and not _same_page_content(current, markdown):
                atomic_write_text(path, markdown)
                updated.append(page_id)
        elif sources and not (sources & valid_sources):
            path = config.vault / str(page.get("path") or "")
            if path.is_file():
                path.unlink()
            registry["pages"].pop(page_id, None)
            removed.append(page_id)
    if allow_create:
        active_page_ids = set((registry.get("pages") or {}).keys())
        for page_id, replacement in desired.items():
            if page_id in active_page_ids or page_id in tombstones:
                continue
            path = _page_path(config, page_id)
            atomic_write_text(path, str(replacement["markdown"]))
            updated.append(page_id)
    registry, dependencies = _rebuild_registry_documents(config, registry)
    atomic_write_text(_wiki_root(config) / "index.md", _render_index(registry))
    write_json_atomic(_meta_root(config) / "page-registry.json", registry)
    write_json_atomic(_meta_root(config) / "source-dependencies.json", dependencies)
    return {
        "removed_pages": removed,
        "updated_pages": updated,
        "active_sources": len(valid_sources),
    }


def lint_wiki(config: Config) -> Dict[str, Any]:
    ensure_wiki_schema(config)
    registry = _registry_from_disk(config)
    pages = registry.get("pages") or {}
    active_sessions = {
        str(item.get("source_session") or "")
        for item in list_knowledge_documents(config, limit=1000)
    }
    findings: List[Dict[str, Any]] = []
    referenced: set[str] = set()
    title_map: Dict[str, List[str]] = defaultdict(list)
    for page_id, page in pages.items():
        path = config.vault / str(page.get("path") or "")
        if not path.is_file():
            findings.append({"type": "missing_file", "severity": "error", "page_id": page_id})
            continue
        markdown = path.read_text(encoding="utf-8")
        title = re.search(r"(?m)^#\s+(.+)$", markdown)
        if title:
            title_map[title.group(1).strip().casefold()].append(page_id)
        for target in re.findall(r"\[\[([^\]|#]+)", markdown):
            referenced.add(target)
            if target not in pages and not (config.vault / "wiki" / f"{target}.md").exists():
                findings.append({"type": "broken_link", "severity": "warning", "page_id": page_id, "target": target})
        for source in page.get("sources", []):
            if str(source) not in active_sessions:
                findings.append({"type": "stale_source", "severity": "error", "page_id": page_id, "source_session": source})
        if page.get("source_count", 0) < 1:
            findings.append({"type": "low_evidence", "severity": "warning", "page_id": page_id})
    for _, duplicate_ids in title_map.items():
        if len(duplicate_ids) > 1:
            findings.append({"type": "duplicate_topic", "severity": "warning", "pages": duplicate_ids})
    for page_id in pages:
        if page_id != "overview/overview" and page_id not in referenced:
            findings.append({"type": "orphan_page", "severity": "info", "page_id": page_id})
    for category in ("overview", "projects"):
        if not any(str(page_id).startswith(f"{category}/") for page_id in pages):
            findings.append({"type": "missing_aggregate", "severity": "error", "category": category})
    report = {
        "checked_at": _now(), "page_count": len(pages), "finding_count": len(findings),
        "healthy": not any(item["severity"] == "error" for item in findings),
        "findings": findings,
    }
    write_json_atomic(_meta_root(config) / "lint-latest.json", report)
    return report


def latest_wiki_lint(config: Config) -> Dict[str, Any]:
    value = _json(_meta_root(config) / "lint-latest.json", None)
    if not isinstance(value, dict):
        return {"checked_at": "", "page_count": 0, "finding_count": 0, "healthy": True, "findings": []}
    return value
