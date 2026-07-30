from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List

from .config import Config
from .knowledge_store import parse_frontmatter
from .opencode_client import Runner


WIKI_CATEGORIES = ("overview", "projects", "topics", "decisions", "issues")
CATEGORY_LABELS = {
    "overview": "知识总览",
    "projects": "项目",
    "topics": "技术主题",
    "decisions": "设计决策",
    "issues": "问题定位",
}
SAFE_SLUG = re.compile(r"^[^/\\\x00]+$")
HEADING = re.compile(r"(?m)^#\s+(.+?)\s*$")
SECTION = re.compile(r"(?m)^##\s+(.+?)\s*$")
WIKI_LINK = re.compile(r"\[\[([^\]|#]+)")
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+\.md)(?:#[^)]+)?\)")
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
        if in_code or not stripped or stripped.startswith("#"):
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


def graph_snapshot(config: Config) -> Dict[str, Any]:
    path = config.vault / "graph" / "graph.json"
    if not path.exists():
        return {
            "directed": True,
            "multigraph": False,
            "nodes": [],
            "links": [],
            "stats": {"nodes": 0, "links": 0, "types": {}},
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
            node_map[target]["label"] = metadata["project"]

    existing_links = {
        (
            str(link.get("source") or ""),
            str(link.get("target") or ""),
            str(link.get("relation") or ""),
        )
        for link in links
    }
    for page in iter_wiki_pages(config):
        if page["category"] != "issues":
            continue
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
        if page["source_session"] and session_id in node_map:
            derived_edges.append((issue_id, session_id, "derived_from"))
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

    return {
        "directed": bool(value.get("directed", True)),
        "multigraph": bool(value.get("multigraph", False)),
        "nodes": list(node_map.values()),
        "links": links,
        "stats": {
            "nodes": len(node_map),
            "links": len(links),
            "types": {
                node_type: sum(node.get("type") == node_type for node in node_map.values())
                for node_type in ("session", "project", "agent", "tool", "topic", "file", "issue")
            },
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
