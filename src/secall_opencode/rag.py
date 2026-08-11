from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config
from .opencode_client import OpenCodeClient
from .search import HybridSearchService
from .wiki_store import graph_snapshot, read_wiki_page


def _graph_result_id(item: Dict[str, Any]) -> str:
    scope = str(item.get("scope") or "")
    identifier = str(item.get("id") or "")
    return {
        "session": f"session:{identifier}",
        "knowledge": f"issue:{identifier}",
        "wiki": f"wiki:{identifier}",
    }.get(scope, "")


def _expand_with_wiki_graph(
    config: Config,
    sources: List[Dict[str, Any]],
    *,
    max_extra: int = 4,
    hops: int = 2,
) -> List[Dict[str, Any]]:
    """Expand retrieval with a small, evidence-only Wiki graph neighborhood."""
    snapshot = graph_snapshot(config)
    nodes = {str(item.get("id")): item for item in snapshot.get("nodes", [])}
    adjacency: Dict[str, set[str]] = {}
    for link in snapshot.get("links", []):
        source = str(link.get("source") or "")
        target = str(link.get("target") or "")
        if source and target:
            adjacency.setdefault(source, set()).add(target)
            adjacency.setdefault(target, set()).add(source)
    frontier = {_graph_result_id(item) for item in sources}
    frontier.discard("")
    visited = set(frontier)
    candidates: List[tuple[int, str]] = []
    for distance in range(1, hops + 1):
        next_frontier: set[str] = set()
        for node_id in frontier:
            for neighbor in adjacency.get(node_id, set()):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                next_frontier.add(neighbor)
                node = nodes.get(neighbor) or {}
                if node.get("type") in {"wiki_page", "issue"}:
                    candidates.append((distance, neighbor))
        frontier = next_frontier
    existing = {(str(item.get("scope")), str(item.get("id"))) for item in sources}
    expanded = list(sources)
    for distance, node_id in candidates:
        node = nodes.get(node_id) or {}
        wiki_id = str(node.get("wiki_id") or "")
        if not wiki_id and node_id.startswith("wiki:"):
            wiki_id = node_id.removeprefix("wiki:")
        if not wiki_id or "/" not in wiki_id:
            continue
        category, slug = wiki_id.split("/", 1)
        scope = "knowledge" if category == "issues" else "wiki"
        identifier = slug if scope == "knowledge" else wiki_id
        if (scope, identifier) in existing:
            continue
        try:
            page = read_wiki_page(config, category, slug)
        except (FileNotFoundError, ValueError):
            continue
        expanded.append({
            "id": identifier,
            "scope": scope,
            "title": page["title"],
            "snippet": page["summary"] or page["markdown"][:500],
            "project": page["project"],
            "source_session": page["source_session"],
            "score": round(1.0 / (distance + 2), 6),
            "match_type": f"graph_{distance}hop",
            "review_status": "approved",
        })
        existing.add((scope, identifier))
        if len(expanded) >= len(sources) + max_extra:
            break
    return expanded


def answer_with_rag(
    config: Config,
    search: HybridSearchService,
    question: str,
    *,
    scope: str = "all",
    mode: str = "hybrid",
    limit: int = 6,
    model: Optional[str] = None,
    timeout: int = 600,
) -> Dict[str, Any]:
    question = question.strip()
    if len(question) < 2:
        raise ValueError("问题至少需要两个字符。")
    retrieval = search.search(question, scope=scope, mode=mode, limit=limit)
    sources = _expand_with_wiki_graph(
        config,
        list(retrieval["results"]),
        max_extra=min(4, max(1, limit // 2)),
    )
    if not sources:
        return {
            "question": question,
            "answer": "当前知识库中没有检索到足够的相关证据，暂时无法生成可靠回答。",
            "sources": [],
            "requested_mode": retrieval["requested_mode"],
            "effective_mode": retrieval["effective_mode"],
            "semantic_available": retrieval["semantic_available"],
            "fallback_reason": retrieval["fallback_reason"],
            "grounded": False,
        }

    evidence_blocks = []
    for index, item in enumerate(sources, 1):
        evidence_blocks.append(
            "\n".join(
                [
                    f"## [S{index}] {item['title']}",
                    f"- 类型：{item['scope']}",
                    f"- 项目：{item['project']}",
                    f"- 来源会话：{item['source_session']}",
                    f"- 匹配方式：{item['match_type']}",
                    "",
                    str(item["snippet"]),
                ]
            )
        )
    context = (
        "# seCall RAG 检索证据\n\n"
        "以下内容来自本地知识库。回答时只能使用这些证据，引用格式为 [S1]。\n\n"
        + "\n\n".join(evidence_blocks)
        + "\n"
    )
    prompt = Path(__file__).parent / "prompts" / "rag-answer.md"
    temp_root = config.vault / ".tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rag-", dir=str(temp_root)) as directory:
        context_file = Path(directory) / "retrieved-context.md"
        context_file.write_text(context, encoding="utf-8")
        answer = OpenCodeClient(config.opencode_command).run_rag_answer(
            context_file,
            prompt,
            config.vault,
            question,
            model=model or config.model,
            timeout=timeout,
        )
    return {
        "question": question,
        "answer": answer,
        "sources": [
            {"citation": f"S{index}", **item}
            for index, item in enumerate(sources, 1)
        ],
        "requested_mode": retrieval["requested_mode"],
        "effective_mode": retrieval["effective_mode"],
        "semantic_available": retrieval["semantic_available"],
        "fallback_reason": retrieval["fallback_reason"],
        "grounded": True,
    }
