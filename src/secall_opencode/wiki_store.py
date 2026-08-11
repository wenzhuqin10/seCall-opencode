from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List

from .config import Config
from .knowledge_store import (
    atomic_write_text,
    list_knowledge_documents,
    parse_frontmatter,
)
from .opencode_client import Runner
from .structured_knowledge import read_structured_knowledge


WIKI_CATEGORIES = (
    "overview",
    "projects",
    "modules",
    "topics",
    "decisions",
    "runbooks",
    "tests",
    "issues",
)
CORE_GRAPH_TYPES = {"issue", "project", "module", "session", "topic", "wiki_page"}
CATEGORY_LABELS = {
    "overview": "知识总览",
    "projects": "项目",
    "modules": "模块",
    "topics": "技术主题",
    "decisions": "设计决策",
    "runbooks": "运行手册",
    "tests": "测试知识",
    "issues": "问题定位",
}
SAFE_SLUG = re.compile(r"^[^/\\\x00]+$")
HEADING = re.compile(r"(?m)^#\s+(.+?)\s*$")
SECTION = re.compile(r"(?m)^##\s+(.+?)\s*$")
WIKI_LINK = re.compile(r"\[\[([^\]|#]+)")
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+\.md)(?:#[^)]+)?\)")
DERIVED_START = "<!-- SECALL:KNOWLEDGE-DERIVED:START -->"
DERIVED_END = "<!-- SECALL:KNOWLEDGE-DERIVED:END -->"
DERIVED_BLOCK = re.compile(
    rf"(?ms)^[ \t]*{re.escape(DERIVED_START)}.*?"
    rf"{re.escape(DERIVED_END)}[ \t]*(?:\r?\n)?"
)
DISPLAY_TRANSLATIONS = {
    "codex 세션": "Codex 会话",
    "opencode 세션": "OpenCode 会话",
    "chatgpt 세션": "ChatGPT 会话",
    "세션": "会话",
    "턴": "轮",
    "프로젝트": "项目",
    "사용자": "用户",
    "어시스턴트": "助手",
    "도구": "工具",
    "요약": "摘要",
    "알 수 없음": "未知",
}


def _localize_display_text(value: str) -> str:
    result = value
    for source, target in DISPLAY_TRANSLATIONS.items():
        result = result.replace(source, target)
    result = re.sub(r"(?i)^codex\s+会话\s*[:：]\s*", "Codex 会话：", result)
    result = re.sub(r"(?i)^opencode\s+会话\s*[:：]\s*", "OpenCode 会话：", result)
    result = re.sub(r"(?i)^chatgpt\s+会话\s*[:：]\s*", "ChatGPT 会话：", result)
    return result


def _wiki_root(config: Config) -> Path:
    return config.vault / "wiki"


def _entity_slug(value: str) -> str:
    value = value.strip().lower().replace("_", "-")
    value = re.sub(r"[\\/:*?\"<>|#\[\]]+", "-", value)
    value = re.sub(r"\s+", "-", value)
    return re.sub(r"-+", "-", value).strip("-.")[:96] or "untitled"


def _replace_derived_block(markdown: str, block: str) -> str:
    replacement = block.strip()
    if DERIVED_BLOCK.search(markdown):
        return DERIVED_BLOCK.sub(replacement + "\n\n", markdown).rstrip() + "\n"
    heading = re.search(r"(?m)^#\s+.+?\s*$", markdown)
    if heading:
        insert_at = heading.end()
        return (
            markdown[:insert_at].rstrip()
            + "\n\n"
            + replacement
            + "\n\n"
            + markdown[insert_at:].lstrip()
        ).rstrip() + "\n"
    return (markdown.rstrip() + "\n\n" + replacement + "\n").lstrip()


def _project_matches(card_project: str, page: Dict[str, Any]) -> bool:
    card = re.sub(r"[\s_→>\-/]+", "", card_project).lower()
    values = {
        str(page.get("project") or ""),
        str(page.get("slug") or ""),
        str(page.get("title") or ""),
    }
    for value in values:
        normalized = re.sub(r"[\s_→>\-/]+", "", value).lower()
        if normalized and (normalized in card or card in normalized):
            return True
    return False


def _knowledge_summary_block(
    cards: List[Dict[str, Any]],
    *,
    title: str,
    empty_text: str,
) -> str:
    lines = [
        DERIVED_START,
        f"## {title}",
        "",
        "> 此区域由 seCall OpenCode Studio 自动同步，请在知识库中修改来源卡片。",
        "",
    ]
    if cards:
        lines.append(f"当前关联 **{len(cards)}** 张知识卡片：")
        lines.append("")
        for card in sorted(cards, key=lambda item: str(item.get("title") or "")):
            slug = str(card.get("id") or "")
            title_text = str(card.get("title") or slug)
            project = str(card.get("project") or "未分类")
            review_status = str(card.get("review_status") or "pending")
            lines.append(
                f"- [[issues/{slug}|{title_text}]] · {project} · {review_status}"
            )
    else:
        lines.append(empty_text)
    lines.extend(["", DERIVED_END])
    return "\n".join(lines)


def sync_wiki_knowledge_views(config: Config, *, allow_create: bool = False) -> Dict[str, Any]:
    """Synchronize marker-managed Wiki summaries from active knowledge cards."""

    cards = list_knowledge_documents(config, limit=1000)
    root = _wiki_root(config)
    root.mkdir(parents=True, exist_ok=True)
    updated_pages: List[str] = []

    overview = root / "overview.md"
    if overview.exists():
        overview_markdown = overview.read_text(encoding="utf-8", errors="replace")
        overview_block = _knowledge_summary_block(
            cards,
            title="知识卡片索引",
            empty_text="当前没有已入库的知识卡片。",
        )
        next_overview = _replace_derived_block(overview_markdown, overview_block)
        if next_overview != overview_markdown:
            atomic_write_text(overview, next_overview)
            updated_pages.append("overview/overview")

    project_root = root / "projects"
    if project_root.exists():
        for path in sorted(project_root.glob("*.md")):
            markdown = path.read_text(encoding="utf-8", errors="replace")
            metadata, _ = parse_frontmatter(markdown)
            page = {
                "slug": path.stem,
                "title": _page_title(markdown, metadata, path.stem),
                "project": metadata.get("project") or path.stem,
            }
            related = [
                card
                for card in cards
                if _project_matches(str(card.get("project") or ""), page)
            ]
            if not related and DERIVED_START not in markdown:
                continue
            block = _knowledge_summary_block(
                related,
                title="关联知识卡片",
                empty_text="当前没有关联的知识卡片。",
            )
            next_markdown = _replace_derived_block(markdown, block)
            if next_markdown != markdown:
                atomic_write_text(path, next_markdown)
                updated_pages.append(f"projects/{path.stem}")

    # Lifecycle changes must immediately remove stale aggregate pages and
    # dependency records. New cross-page content is still created through a
    # reviewable Wiki plan.
    from .wiki_maintenance import deterministic_reconcile, ensure_wiki_schema

    ensure_wiki_schema(config)
    reconcile = deterministic_reconcile(config, allow_create=allow_create)
    snapshot = list_wiki_pages(config, limit=2000)
    return {
        "knowledge_count": len(cards),
        "updated_pages": updated_pages,
        "wiki_count": snapshot["count"],
        "counts": snapshot["counts"],
        "reconcile": reconcile,
    }


def _validate_category(category: str) -> str:
    if category not in WIKI_CATEGORIES:
        raise ValueError(f"未知 Wiki 分类：{category}")
    return category


def _validate_slug(slug: str) -> str:
    if not slug or slug in {".", ".."} or not SAFE_SLUG.fullmatch(slug):
        raise ValueError("Wiki 页面 ID 包含非法字符。")
    return slug


def _wiki_path(config: Config, category: str, slug: str) -> Path:
    category = _validate_category(category)
    slug = _validate_slug(slug)
    if category == "overview":
        if slug != "overview":
            raise FileNotFoundError(f"Wiki 页面不存在：{category}/{slug}")
        path = _wiki_root(config) / "overview.md"
    else:
        path = _wiki_root(config) / category / f"{slug}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Wiki 页面不存在：{category}/{slug}")
    return path


def _page_title(markdown: str, metadata: Dict[str, str], fallback: str) -> str:
    match = HEADING.search(markdown)
    return metadata.get("title") or (match.group(1).strip() if match else fallback)


def _summary(markdown: str) -> str:
    _, body = parse_frontmatter(markdown)
    lines = []
    in_code = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if (
            in_code
            or not stripped
            or stripped.startswith("#")
            or stripped.startswith("<!--")
            or stripped.endswith("-->")
        ):
            continue
        cleaned = re.sub(r"[*_`>\[\]]", "", stripped)
        if cleaned:
            lines.append(cleaned)
        if len(" ".join(lines)) >= 260:
            break
    return " ".join(lines)[:260]


def iter_wiki_pages(config: Config, include_issues: bool = True) -> Iterator[Dict[str, Any]]:
    root = _wiki_root(config)
    paths: List[tuple[str, Path]] = []
    overview = root / "overview.md"
    if overview.is_file():
        paths.append(("overview", overview))
    for category in WIKI_CATEGORIES[1:]:
        if category == "issues" and not include_issues:
            continue
        category_root = root / category
        if category_root.exists():
            paths.extend((category, path) for path in category_root.glob("*.md"))
    for category, path in paths:
        markdown = path.read_text(encoding="utf-8", errors="replace")
        metadata, _ = parse_frontmatter(markdown)
        slug = "overview" if category == "overview" else path.stem
        yield {
            "id": f"{category}/{slug}",
            "slug": slug,
            "category": category,
            "category_label": CATEGORY_LABELS[category],
            "title": _page_title(markdown, metadata, path.stem),
            "project": metadata.get("project") or (
                path.stem if category == "projects" else "全部项目"
            ),
            "source_session": metadata.get("source_session") or "",
            "summary": _summary(markdown),
            "updated": int(path.stat().st_mtime * 1000),
            "word_count": len(markdown),
            "path": str(path.relative_to(config.vault)).replace("\\", "/"),
        }


def list_wiki_pages(
    config: Config,
    category: str = "all",
    query: str = "",
    limit: int = 500,
) -> Dict[str, Any]:
    if category != "all":
        _validate_category(category)
    pages = list(iter_wiki_pages(config))
    if category != "all":
        pages = [item for item in pages if item["category"] == category]
    normalized = query.strip().lower()
    if normalized:
        pages = [
            item
            for item in pages
            if normalized in str(item["title"]).lower()
            or normalized in str(item["summary"]).lower()
            or normalized in str(item["project"]).lower()
        ]
    pages.sort(key=lambda item: (WIKI_CATEGORIES.index(item["category"]), item["title"]))
    counts = {
        key: sum(item["category"] == key for item in pages)
        for key in WIKI_CATEGORIES
    }
    return {
        "count": len(pages),
        "counts": counts,
        "pages": pages[: max(1, min(limit, 2000))],
    }


def read_wiki_page(config: Config, category: str, slug: str) -> Dict[str, Any]:
    path = _wiki_path(config, category, slug)
    markdown = path.read_text(encoding="utf-8", errors="replace")
    metadata, body = parse_frontmatter(markdown)
    matches = list(SECTION.finditer(body))
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append(
            {
                "heading": match.group(1).strip(),
                "content": body[match.end() : end].strip(),
            }
        )
    references = set(WIKI_LINK.findall(markdown))
    references.update(Path(item).stem for item in MARKDOWN_LINK.findall(markdown))
    backlinks = []
    for page in iter_wiki_pages(config):
        if page["id"] == f"{category}/{slug}":
            continue
        other_path = config.vault / page["path"]
        other = other_path.read_text(encoding="utf-8", errors="replace")
        if slug in other or path.name in other:
            backlinks.append(
                {"id": page["id"], "title": page["title"], "category": page["category"]}
            )
    return {
        "id": f"{category}/{slug}",
        "slug": slug,
        "category": category,
        "category_label": CATEGORY_LABELS[category],
        "title": _page_title(markdown, metadata, path.stem),
        "project": metadata.get("project") or (
            slug if category == "projects" else "全部项目"
        ),
        "source_session": metadata.get("source_session") or "",
        "summary": _summary(markdown),
        "markdown": markdown,
        "sections": sections,
        "references": sorted(references),
        "backlinks": backlinks,
        "updated": int(path.stat().st_mtime * 1000),
        "word_count": len(markdown),
        "path": str(path.relative_to(config.vault)).replace("\\", "/"),
    }


def archive_wiki_page(config: Config, category: str, slug: str) -> Dict[str, Any]:
    category = _validate_category(category)
    slug = _validate_slug(slug)
    if category == "issues":
        raise ValueError("问题定位页由知识卡片管理，请在知识库中删除对应卡片。")
    path = _wiki_path(config, category, slug)
    detail = read_wiki_page(config, category, slug)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    trash_id = f"{timestamp}-{category}-{slug}-{uuid.uuid4().hex[:6]}"
    trash_dir = config.vault / ".trash" / "wiki" / trash_id
    trash_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(path, trash_dir / "document.md")
    manifest = {
        "trash_id": trash_id,
        "wiki_id": detail["id"],
        "category": category,
        "category_label": detail["category_label"],
        "slug": slug,
        "title": detail["title"],
        "project": detail["project"],
        "source_session": detail["source_session"],
        "original_path": str(path.relative_to(config.vault)).replace("\\", "/"),
        "archived_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_text(
        trash_dir / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    path.unlink()
    from .wiki_maintenance import mark_wiki_tombstone

    mark_wiki_tombstone(config, detail["id"], archived_at=manifest["archived_at"])
    return manifest


def list_wiki_archive(config: Config) -> List[Dict[str, Any]]:
    root = config.vault / ".trash" / "wiki"
    if not root.exists():
        return []
    items: List[Dict[str, Any]] = []
    for manifest_path in root.glob("*/manifest.json"):
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            items.append(value)
    return sorted(
        items,
        key=lambda item: str(item.get("archived_at") or ""),
        reverse=True,
    )


def restore_wiki_page(config: Config, trash_id: str) -> Dict[str, Any]:
    trash_id = _validate_slug(trash_id)
    trash_dir = config.vault / ".trash" / "wiki" / trash_id
    manifest_path = trash_dir / "manifest.json"
    document_path = trash_dir / "document.md"
    if not manifest_path.exists() or not document_path.exists():
        raise FileNotFoundError(f"Wiki 归档记录不存在：{trash_id}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    category = _validate_category(str(manifest.get("category") or ""))
    slug = _validate_slug(str(manifest.get("slug") or ""))
    if category == "issues":
        raise ValueError("该 Wiki 分类不能通过独立归档恢复。")
    target = (
        _wiki_root(config) / "overview.md"
        if category == "overview"
        else _wiki_root(config) / category / f"{slug}.md"
    )
    if target.exists():
        raise FileExistsError(f"同名 Wiki 页面已存在，无法覆盖恢复：{category}/{slug}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(document_path), str(target))
    shutil.rmtree(trash_dir)
    from .wiki_maintenance import clear_wiki_tombstone

    clear_wiki_tombstone(config, f"{category}/{slug}")
    return read_wiki_page(config, category, slug)


def purge_wiki_archive(config: Config, trash_id: str) -> Dict[str, Any]:
    trash_id = _validate_slug(trash_id)
    trash_dir = config.vault / ".trash" / "wiki" / trash_id
    manifest_path = trash_dir / "manifest.json"
    document_path = trash_dir / "document.md"
    if not manifest_path.exists() or not document_path.exists():
        raise FileNotFoundError(f"Wiki 归档记录不存在：{trash_id}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or str(manifest.get("trash_id") or "") != trash_id:
        raise ValueError("Wiki 归档记录损坏，拒绝永久删除。")
    result = {
        **manifest,
        "purged": True,
        "purged_at": datetime.now(timezone.utc).isoformat(),
    }
    shutil.rmtree(trash_dir)
    return result


def purge_all_wiki_archive(config: Config) -> Dict[str, Any]:
    purged: List[Dict[str, Any]] = []
    for item in list_wiki_archive(config):
        trash_id = str(item.get("trash_id") or "")
        if trash_id:
            purged.append(purge_wiki_archive(config, trash_id))
    return {
        "purged": len(purged),
        "items": [
            {
                "trash_id": item.get("trash_id"),
                "wiki_id": item.get("wiki_id"),
                "title": item.get("title"),
            }
            for item in purged
        ],
    }


def graph_snapshot(config: Config) -> Dict[str, Any]:
    path = config.vault / "graph" / "graph.json"
    if not path.exists():
        return {
            "directed": True,
            "multigraph": False,
            "nodes": [],
            "links": [],
            "stats": {
                "nodes": 0,
                "links": 0,
                "types": {
                    node_type: 0
                    for node_type in (
                        "issue", "project", "module", "session", "topic", "wiki_page"
                    )
                },
                "evidence": {
                    key: 0
                    for key in (
                        "files", "functions", "commits", "root_causes", "test_cases"
                    )
                },
            },
        }
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(value, dict):
        raise ValueError("知识图谱快照格式无效。")
    nodes = value.get("nodes") if isinstance(value.get("nodes"), list) else []
    raw_links = value.get("links") if isinstance(value.get("links"), list) else []
    links = [dict(item) for item in raw_links if isinstance(item, dict)]

    session_meta: Dict[str, Dict[str, str]] = {}
    session_root = config.vault / "raw" / ".sessions"
    if session_root.exists():
        for session_path in session_root.rglob("*.md"):
            markdown = session_path.read_text(encoding="utf-8", errors="replace")
            metadata, _ = parse_frontmatter(markdown)
            session_id = metadata.get("session_id") or session_path.stem
            heading = HEADING.search(markdown)
            session_meta[session_id] = {
                "title": _localize_display_text(
                    heading.group(1).strip() if heading else session_path.stem
                ),
                "project": _localize_display_text(metadata.get("project") or "unknown"),
            }

    node_map = {
        str(node.get("id")): dict(node)
        for node in nodes
        if isinstance(node, dict) and node.get("id")
    }
    for node_id, node in node_map.items():
        node["label"] = _localize_display_text(str(node.get("label") or node_id))
        if node.get("project"):
            node["project"] = _localize_display_text(str(node["project"]))
        if node.get("type") == "session":
            session_id = node_id.removeprefix("session:")
            metadata = session_meta.get(session_id)
            if metadata:
                node["label"] = metadata["title"]
                node["project"] = metadata["project"]
    for link in links:
        if link.get("relation") != "belongs_to":
            continue
        source = str(link.get("source") or "")
        target = str(link.get("target") or "")
        session_id = source.removeprefix("session:")
        metadata = session_meta.get(session_id)
        if metadata and target in node_map:
            canonical_target = f"project:{metadata['project']}"
            if canonical_target not in node_map:
                node_map[canonical_target] = {
                    **node_map[target],
                    "id": canonical_target,
                    "label": metadata["project"],
                    "type": "project",
                }
            link["target"] = canonical_target

    existing_links = {
        (
            str(link.get("source") or ""),
            str(link.get("target") or ""),
            str(link.get("relation") or ""),
        )
        for link in links
    }
    wiki_by_source: Dict[str, Dict[str, List[str]]] = {}
    for page in iter_wiki_pages(config, include_issues=False):
        wiki_node_id = f"wiki:{page['id']}"
        node_map[wiki_node_id] = {
            "id": wiki_node_id,
            "label": page["title"],
            "type": "wiki_page",
            "category": page["category"],
            "category_label": page["category_label"],
            "project": page["project"],
            "wiki_id": page["id"],
        }
        derived_edges: List[tuple[str, str, str]] = []
        page_markdown = (config.vault / page["path"]).read_text(
            encoding="utf-8", errors="replace"
        )
        sources_match = re.search(r"(?m)^sources:\s*(.+)$", page_markdown)
        try:
            page_sources = json.loads(sources_match.group(1)) if sources_match else []
        except json.JSONDecodeError:
            page_sources = []
        if page["source_session"]:
            page_sources = list(dict.fromkeys([*page_sources, page["source_session"]]))
        for source_session in page_sources:
            wiki_by_source.setdefault(str(source_session), {}).setdefault(
                page["category"], []
            ).append(wiki_node_id)
        if page["project"] and page["project"] != "全部项目":
            project_id = f"project:{page['project']}"
            if project_id not in node_map:
                node_map[project_id] = {
                    "id": project_id,
                    "label": page["project"],
                    "type": "project",
                }
            derived_edges.append((wiki_node_id, project_id, "documents"))
        session_id = f"session:{page['source_session']}"
        if page["source_session"] and session_id in node_map:
            derived_edges.append((wiki_node_id, session_id, "derived_from"))
        if page["category"] == "topics":
            topic_id = f"topic:{page['slug']}"
            node_map[topic_id] = {
                "id": topic_id,
                "label": page["title"],
                "type": "topic",
                "project": page["project"],
                "wiki_id": page["id"],
            }
            derived_edges.append((topic_id, wiki_node_id, "documented_by"))
        elif page["category"] == "modules":
            module_id = f"module:{page['slug']}"
            node_map[module_id] = {
                "id": module_id,
                "label": page["title"],
                "type": "module",
                "project": page["project"],
                "wiki_id": page["id"],
            }
            derived_edges.append((module_id, wiki_node_id, "documented_by"))
        for source, target, relation in derived_edges:
            if (source, target, relation) in existing_links:
                continue
            links.append(
                {
                    "source": source,
                    "target": target,
                    "relation": relation,
                    "confidence": "DERIVED",
                    "weight": 1.0,
                }
            )
            existing_links.add((source, target, relation))

    issue_pages = [page for page in iter_wiki_pages(config) if page["category"] == "issues"]
    issue_by_session = {
        str(page["source_session"]): f"issue:{page['slug']}"
        for page in issue_pages
        if page["source_session"]
    }
    for page in issue_pages:
        issue_id = f"issue:{page['slug']}"
        project_id = f"project:{page['project']}"
        node_map[issue_id] = {
            "id": issue_id,
            "label": page["title"],
            "type": "issue",
            "project": page["project"],
            "source_session": page["source_session"],
            "wiki_id": page["id"],
        }
        if project_id not in node_map:
            node_map[project_id] = {
                "id": project_id,
                "label": page["project"],
                "type": "project",
            }
        derived_edges = [
            (issue_id, project_id, "belongs_to"),
        ]
        session_id = f"session:{page['source_session']}"
        if page["source_session"]:
            session = session_meta.get(page["source_session"], {})
            node_map[session_id] = {
                "id": session_id,
                "label": session.get("title") or page["source_session"],
                "type": "session",
                "project": session.get("project") or page["project"],
            }
            derived_edges.append((issue_id, session_id, "derived_from"))

        structured = (
            read_structured_knowledge(config.vault, page["source_session"])
            if page["source_session"]
            else None
        ) or {}
        entities = (
            structured.get("code_entities")
            if isinstance(structured.get("code_entities"), dict)
            else {}
        )

        def add_entity(
            entity_type: str,
            label: str,
            relation: str,
            *,
            node_suffix: str | None = None,
        ) -> None:
            clean = str(label or "").strip()
            if not clean:
                return
            suffix = node_suffix or clean
            entity_id = f"{entity_type}:{suffix}"
            if entity_id not in node_map:
                node_map[entity_id] = {
                    "id": entity_id,
                    "label": clean[:180],
                    "type": entity_type,
                    "project": page["project"],
                }
            derived_edges.append((issue_id, entity_id, relation))

        for module in entities.get("modules", []) if isinstance(entities, dict) else []:
            add_entity("module", str(module), "affects")

        for raw_topic in structured.get("topics", []) if isinstance(structured.get("topics"), list) else []:
            if isinstance(raw_topic, dict):
                topic_label = str(
                    raw_topic.get("name")
                    or raw_topic.get("title")
                    or raw_topic.get("topic")
                    or raw_topic.get("description")
                    or ""
                ).strip()
            else:
                topic_label = str(raw_topic).strip()
            if not topic_label:
                continue
            topic_suffix = _entity_slug(topic_label)
            add_entity("topic", topic_label, "about_topic", node_suffix=topic_suffix)

        raw_claims = structured.get("claims") if isinstance(structured.get("claims"), list) else []
        for claim in raw_claims:
            if not isinstance(claim, dict):
                continue
            target_session = str(
                claim.get("contradicts_source_session")
                or claim.get("contradicts_session")
                or ""
            ).strip()
            target_issue = issue_by_session.get(target_session)
            if target_issue and target_issue != issue_id:
                derived_edges.append((issue_id, target_issue, "contradicts"))

        source_wiki = wiki_by_source.get(page["source_session"], {})
        for test_page in source_wiki.get("tests", []):
            derived_edges.append((issue_id, test_page, "verified_by"))
        for decision_page in source_wiki.get("decisions", []):
            for module in entities.get("modules", []) if isinstance(entities, dict) else []:
                module_id = f"module:{str(module).strip()}"
                derived_edges.append((module_id, decision_page, "implements_decision"))

        def evidence_values(key: str) -> List[str]:
            raw = entities.get(key, []) if isinstance(entities, dict) else []
            values = raw if isinstance(raw, list) else [raw] if raw else []
            return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))

        root_cause = (
            structured.get("root_cause")
            if isinstance(structured.get("root_cause"), dict)
            else {}
        )
        conclusion = str(root_cause.get("conclusion") or "").strip()

        verification = (
            structured.get("verification")
            if isinstance(structured.get("verification"), dict)
            else {}
        )
        raw_tests = verification.get("test_cases")
        tests = raw_tests if isinstance(raw_tests, list) else [raw_tests] if raw_tests else []
        test_cases = list(
            dict.fromkeys(str(item).strip() for item in tests if str(item).strip())
        )
        evidence = {
            "files": evidence_values("files"),
            "functions": evidence_values("functions"),
            "commits": evidence_values("commits"),
            "root_causes": [conclusion] if conclusion else [],
            "test_cases": test_cases,
        }
        node_map[issue_id]["evidence"] = evidence
        node_map[issue_id]["evidence_counts"] = {
            key: len(values) for key, values in evidence.items()
        }

        for source, target, relation in derived_edges:
            if (source, target, relation) in existing_links:
                continue
            links.append(
                {
                    "source": source,
                    "target": target,
                    "relation": relation,
                    "confidence": "DERIVED",
                    "weight": 1.0,
                }
            )
            existing_links.add((source, target, relation))

    roots = {
        node_id
        for node_id, node in node_map.items()
        if node.get("type") in {"issue", "wiki_page"}
    }
    core_links = [
        link
        for link in links
        if str(link.get("source") or "") in node_map
        and str(link.get("target") or "") in node_map
        and node_map[str(link.get("source") or "")].get("type") in CORE_GRAPH_TYPES
        and node_map[str(link.get("target") or "")].get("type") in CORE_GRAPH_TYPES
    ]
    adjacency: Dict[str, set[str]] = {}
    for link in core_links:
        source = str(link.get("source") or "")
        target = str(link.get("target") or "")
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)
    visible = set(roots)
    frontier = list(roots)
    while frontier:
        current = frontier.pop()
        for neighbor in adjacency.get(current, set()):
            if neighbor not in visible:
                visible.add(neighbor)
                frontier.append(neighbor)

    node_map = {
        node_id: node
        for node_id, node in node_map.items()
        if node_id in visible and node.get("type") in CORE_GRAPH_TYPES
    }
    links = [
        link
        for link in core_links
        if str(link.get("source") or "") in node_map
        and str(link.get("target") or "") in node_map
    ]
    baseline_types = ("issue", "project", "module", "session", "topic", "wiki_page")
    type_counts = {
        node_type: sum(node.get("type") == node_type for node in node_map.values())
        for node_type in baseline_types
    }
    evidence_counts = {
        key: sum(
            int(dict(node.get("evidence_counts") or {}).get(key) or 0)
            for node in node_map.values()
            if node.get("type") == "issue"
        )
        for key in ("files", "functions", "commits", "root_causes", "test_cases")
    }
    return {
        "directed": bool(value.get("directed", True)),
        "multigraph": bool(value.get("multigraph", False)),
        "nodes": list(node_map.values()),
        "links": links,
        "stats": {
            "nodes": len(node_map),
            "links": len(links),
            "types": type_counts,
            "evidence": evidence_counts,
        },
    }


def rebuild_graph(config: Config) -> Dict[str, Any]:
    runner = Runner(config.secall_command)
    build = runner.run("graph", "build", "--force", timeout=600)
    export = runner.run("graph", "export", timeout=120)
    return {
        "build_output": build.stdout.strip(),
        "export_output": export.stdout.strip(),
        "graph": graph_snapshot(config),
    }
