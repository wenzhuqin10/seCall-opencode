from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Protocol, Sequence

from .config import Config
from .knowledge_store import list_knowledge_documents, read_knowledge_document
from .opencode_client import Runner


CJK_RUN = re.compile(r"[\u3400-\u9fff]+")
ASCII_TOKEN = re.compile(r"[0-9a-zA-Z_./:#@+\-]{2,}")


@dataclass(frozen=True)
class SearchResult:
    id: str
    scope: str
    title: str
    snippet: str
    project: str
    source_session: str
    score: float
    match_type: str
    review_status: str

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SemanticSearchBackend(Protocol):
    @property
    def available(self) -> bool: ...

    def status(self) -> Dict[str, Any]: ...

    def search(
        self, query: str, scope: str, limit: int
    ) -> Sequence[SearchResult]: ...

    def rebuild(self) -> Dict[str, Any]: ...

    def remove(self, document_id: str) -> None: ...


class UnavailableSemanticBackend:
    def __init__(self, model_dir: Path | None):
        self.model_dir = model_dir

    @property
    def available(self) -> bool:
        return False

    def status(self) -> Dict[str, Any]:
        return {
            "available": False,
            "backend": "none",
            "model_dir": str(self.model_dir or ""),
            "reason": "本地语义模型尚未就绪，已使用关键词检索。",
        }

    def search(self, query: str, scope: str, limit: int) -> Sequence[SearchResult]:
        return []

    def rebuild(self) -> Dict[str, Any]:
        return self.status()

    def remove(self, document_id: str) -> None:
        return None


class OnnxSemanticBackend(UnavailableSemanticBackend):
    """Reserved extension point for the phase-two ONNX implementation."""

    def status(self) -> Dict[str, Any]:
        status = super().status()
        status["backend"] = "onnx"
        status["reason"] = "ONNX 接口已预留，模型加载将在第二阶段启用。"
        return status


def _search_db_path(config: Config) -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".cache"
    digest = hashlib.sha256(str(config.vault).encode("utf-8")).hexdigest()[:12]
    return base / "secall-opencode" / f"search-{digest}.sqlite"


def _tokens(text: str) -> str:
    lowered = text.lower()
    values = set(ASCII_TOKEN.findall(lowered))
    for run in CJK_RUN.findall(lowered):
        values.update(run)
        values.update(run[index : index + 2] for index in range(max(0, len(run) - 1)))
        values.update(run)
    return " ".join(sorted(value for value in values if value))


def _snippet(text: str, query: str, width: int = 220) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""
    index = compact.lower().find(query.lower())
    if index < 0:
        return compact[:width]
    start = max(0, index - width // 3)
    end = min(len(compact), start + width)
    prefix = "…" if start else ""
    suffix = "…" if end < len(compact) else ""
    return prefix + compact[start:end] + suffix


class KeywordSearchBackend:
    def __init__(self, config: Config):
        self.config = config
        self.db_path = _search_db_path(config)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                project TEXT NOT NULL,
                source_session TEXT NOT NULL,
                review_status TEXT NOT NULL,
                content_hash TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                id UNINDEXED,
                scope UNINDEXED,
                title_tokens,
                body_tokens,
                tokenize='unicode61'
            );
            """
        )
        return connection

    def rebuild(self) -> Dict[str, Any]:
        documents: List[Dict[str, str]] = []
        for item in list_knowledge_documents(self.config, limit=1000):
            detail = read_knowledge_document(self.config, item["id"])
            body = "\n".join(
                [detail["intro"]]
                + [
                    f"{section['heading']}\n{section['content']}"
                    for section in detail["sections"]
                ]
            )
            documents.append(
                {
                    "id": item["id"],
                    "scope": "knowledge",
                    "title": item["title"],
                    "body": body,
                    "project": item["project"],
                    "source_session": item["source_session"],
                    "review_status": item["review_status"],
                }
            )
        qa_path = self.config.vault / self.config.qa_file
        if qa_path.exists():
            for line in qa_path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(item, dict) or item.get("review_status") != "approved":
                    continue
                documents.append(
                    {
                        "id": str(item.get("id") or ""),
                        "scope": "qa",
                        "title": str(item.get("question") or "未命名问答"),
                        "body": str(item.get("answer") or ""),
                        "project": str(item.get("project") or "unknown"),
                        "source_session": str(item.get("source_session") or ""),
                        "review_status": "approved",
                    }
                )

        with self._connect() as connection:
            connection.execute("DELETE FROM documents")
            connection.execute("DELETE FROM documents_fts")
            for item in documents:
                digest = hashlib.sha256(
                    f"{item['title']}\n{item['body']}".encode("utf-8")
                ).hexdigest()
                connection.execute(
                    """
                    INSERT INTO documents
                    (id, scope, title, body, project, source_session, review_status, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["id"],
                        item["scope"],
                        item["title"],
                        item["body"],
                        item["project"],
                        item["source_session"],
                        item["review_status"],
                        digest,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO documents_fts
                    (id, scope, title_tokens, body_tokens) VALUES (?, ?, ?, ?)
                    """,
                    (
                        item["id"],
                        item["scope"],
                        _tokens(item["title"]),
                        _tokens(item["body"]),
                    ),
                )
        return {"indexed": len(documents), "path": str(self.db_path)}

    def remove(self, document_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            connection.execute("DELETE FROM documents_fts WHERE id = ?", (document_id,))

    def _knowledge_search(self, query: str, scope: str, limit: int) -> List[SearchResult]:
        if not self.db_path.exists():
            self.rebuild()
        query_tokens = _tokens(query).split()
        if not query_tokens:
            return []
        match = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in query_tokens)
        conditions = "" if scope == "all" else "AND d.scope = ?"
        parameters: List[Any] = [match]
        if scope != "all":
            parameters.append(scope)
        parameters.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT d.*, bm25(documents_fts, 4.0, 1.0) AS rank
                FROM documents_fts
                JOIN documents d ON d.id = documents_fts.id
                WHERE documents_fts MATCH ? {conditions}
                ORDER BY rank ASC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [
            SearchResult(
                id=str(row["id"]),
                scope=str(row["scope"]),
                title=str(row["title"]),
                snippet=_snippet(str(row["body"]), query),
                project=str(row["project"]),
                source_session=str(row["source_session"]),
                score=round(1.0 / (index + 1), 6),
                match_type="keyword",
                review_status=str(row["review_status"]),
            )
            for index, row in enumerate(rows)
        ]

    def _session_search(self, query: str, limit: int) -> List[SearchResult]:
        raw = Runner(self.config.secall_command).run(
            "--format",
            "json",
            "recall",
            query,
            "--limit",
            str(limit * 3),
            "--lex",
            timeout=120,
        ).stdout
        try:
            value = json.loads(raw or "[]")
        except json.JSONDecodeError:
            start = raw.find("[")
            end = raw.rfind("]")
            if start >= 0 and end > start:
                try:
                    value = json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    value = []
            else:
                value = []
        sessions = {
            item["id"]: item
            for item in _session_catalog(self.config)
        }
        results: List[SearchResult] = []
        seen = set()
        for item in value if isinstance(value, list) else []:
            if not isinstance(item, dict):
                continue
            session_id = str(item.get("session_id") or "")
            if not session_id or session_id in seen:
                continue
            seen.add(session_id)
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            session = sessions.get(session_id, {})
            results.append(
                SearchResult(
                    id=session_id,
                    scope="session",
                    title=str(session.get("title") or f"会话 {session_id[:12]}"),
                    snippet=str(item.get("snippet") or ""),
                    project=str(metadata.get("project") or session.get("project") or "unknown"),
                    source_session=session_id,
                    score=float(item.get("score") or 0.0),
                    match_type="keyword",
                    review_status="ready",
                )
            )
            if len(results) >= limit:
                break
        return results

    def search(self, query: str, scope: str, limit: int) -> List[SearchResult]:
        result: List[SearchResult] = []
        if scope in {"all", "session"}:
            try:
                result.extend(self._session_search(query, limit))
            except Exception:
                if scope == "session":
                    raise
        if scope in {"all", "knowledge", "qa"}:
            result.extend(self._knowledge_search(query, scope, limit))
        result.sort(key=lambda item: item.score, reverse=True)
        return result[:limit]


def _session_catalog(config: Config) -> Iterable[Dict[str, Any]]:
    from .server import list_vault_sessions

    return list_vault_sessions(config, limit=1000)


class HybridSearchService:
    def __init__(
        self,
        keyword: KeywordSearchBackend,
        semantic: SemanticSearchBackend,
    ):
        self.keyword = keyword
        self.semantic = semantic

    def search(
        self,
        query: str,
        scope: str = "all",
        mode: str = "keyword",
        limit: int = 20,
    ) -> Dict[str, Any]:
        query = query.strip()
        if len(query) < 2:
            raise ValueError("搜索内容至少需要两个字符。")
        if scope not in {"all", "session", "knowledge", "qa"}:
            raise ValueError("scope 必须是 all、session、knowledge 或 qa。")
        if mode not in {"keyword", "semantic", "hybrid"}:
            raise ValueError("mode 必须是 keyword、semantic 或 hybrid。")
        limit = max(1, min(limit, 100))
        fallback = None
        effective = mode
        if mode != "keyword" and not self.semantic.available:
            effective = "keyword"
            fallback = str(self.semantic.status().get("reason") or "语义检索不可用。")
        if effective == "keyword":
            results = self.keyword.search(query, scope, limit)
        elif effective == "semantic":
            results = list(self.semantic.search(query, scope, limit))
        else:
            results = _rrf_merge(
                self.keyword.search(query, scope, limit * 2),
                self.semantic.search(query, scope, limit * 2),
                limit,
            )
        return {
            "query": query,
            "scope": scope,
            "requested_mode": mode,
            "effective_mode": effective,
            "semantic_available": self.semantic.available,
            "fallback_reason": fallback,
            "count": len(results),
            "results": [item.as_dict() for item in results],
        }


def _rrf_merge(
    keyword: Sequence[SearchResult],
    semantic: Sequence[SearchResult],
    limit: int,
) -> List[SearchResult]:
    values: Dict[tuple[str, str], SearchResult] = {}
    scores: Dict[tuple[str, str], float] = {}
    for collection in (keyword, semantic):
        for rank, item in enumerate(collection, 1):
            key = (item.scope, item.id)
            values[key] = item
            scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
    return [
        SearchResult(
            **{
                **values[key].as_dict(),
                "score": round(score, 6),
                "match_type": "hybrid",
            }
        )
        for key, score in sorted(scores.items(), key=lambda pair: pair[1], reverse=True)[:limit]
    ]


def build_search_service(config: Config) -> HybridSearchService:
    semantic: SemanticSearchBackend
    if config.semantic_backend == "onnx":
        semantic = OnnxSemanticBackend(config.semantic_model_dir)
    else:
        semantic = UnavailableSemanticBackend(config.semantic_model_dir)
    return HybridSearchService(KeywordSearchBackend(config), semantic)
