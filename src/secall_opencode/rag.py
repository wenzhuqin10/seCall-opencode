from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from .config import Config
from .opencode_client import OpenCodeClient
from .search import HybridSearchService


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
    sources = retrieval["results"]
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
