from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Protocol, Sequence

from .config import Config
from .knowledge_store import list_knowledge_documents, read_knowledge_document
from .opencode_client import Runner
from .wiki_store import iter_wiki_pages, read_wiki_page


CJK_RUN = re.compile(r"[\u3400-\u9fff]+")
ASCII_TOKEN = re.compile(r"[0-9a-zA-Z_./:#@+\-]{2,}")
TITLE_PATTERN = re.compile(r"(?m)^#\s+(.+)$")
DISPLAY_TRANSLATIONS = {
    "codex 세션": "Codex 会话",
    "opencode 세션": "OpenCode 会话",
    "chatgpt 세션": "ChatGPT 会话",
    "세션": "会话",
}


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


@dataclass(frozen=True)
class SearchDocument:
    id: str
    scope: str
    title: str
    body: str
    project: str
    source_session: str
    review_status: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(
            f"{self.title}\n{self.body}".encode("utf-8")
        ).hexdigest()


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
            "indexed_documents": 0,
            "indexed_chunks": 0,
            "reason": "本地语义模型尚未就绪，已使用关键词检索。",
        }

    def search(self, query: str, scope: str, limit: int) -> Sequence[SearchResult]:
        return []

    def rebuild(self) -> Dict[str, Any]:
        return self.status()

    def remove(self, document_id: str) -> None:
        return None


def _search_db_path(config: Config) -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".cache"
    digest = hashlib.sha256(str(config.vault).encode("utf-8")).hexdigest()[:12]
    return base / "secall-opencode" / f"search-{digest}.sqlite"


def _frontmatter(markdown: str) -> Dict[str, str]:
    if not markdown.startswith("---"):
        return {}
    end = markdown.find("\n---", 3)
    if end < 0:
        return {}
    result: Dict[str, str] = {}
    for line in markdown[3:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


def _localize_title(title: str) -> str:
    result = title
    for source, target in DISPLAY_TRANSLATIONS.items():
        result = result.replace(source, target)
    return result


def _session_documents(config: Config) -> Iterator[SearchDocument]:
    root = config.vault / "raw" / ".sessions"
    if not root.exists():
        return
    for path in root.rglob("*.md"):
        body = path.read_text(encoding="utf-8", errors="replace")
        meta = _frontmatter(body)
        title_match = TITLE_PATTERN.search(body)
        session_id = meta.get("session_id") or path.stem
        yield SearchDocument(
            id=session_id,
            scope="session",
            title=_localize_title(
                title_match.group(1).strip() if title_match else path.stem
            ),
            body=body,
            project=meta.get("project") or "unknown",
            source_session=session_id,
            review_status="ready",
        )


def _knowledge_and_qa_documents(config: Config) -> Iterator[SearchDocument]:
    for item in list_knowledge_documents(config, limit=10000):
        detail = read_knowledge_document(config, item["id"])
        body = "\n".join(
            [detail["intro"]]
            + [
                f"{section['heading']}\n{section['content']}"
                for section in detail["sections"]
            ]
        )
        yield SearchDocument(
            id=item["id"],
            scope="knowledge",
            title=item["title"],
            body=body,
            project=item["project"],
            source_session=item["source_session"],
            review_status=item["review_status"],
        )

    qa_path = config.vault / config.qa_file
    if not qa_path.exists():
        return
    for line in qa_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict) or item.get("review_status") != "approved":
            continue
        yield SearchDocument(
            id=str(item.get("id") or ""),
            scope="qa",
            title=str(item.get("question") or "未命名问答"),
            body=str(item.get("answer") or ""),
            project=str(item.get("project") or "unknown"),
            source_session=str(item.get("source_session") or ""),
            review_status="approved",
        )


def _wiki_documents(config: Config) -> Iterator[SearchDocument]:
    # Issue pages are already represented by editable knowledge cards.
    for item in iter_wiki_pages(config, include_issues=False):
        detail = read_wiki_page(config, item["category"], item["slug"])
        yield SearchDocument(
            id=item["id"],
            scope="wiki",
            title=item["title"],
            body=detail["markdown"],
            project=item["project"],
            source_session=item["source_session"],
            review_status="published",
        )


def iter_search_documents(
    config: Config, include_sessions: bool = True
) -> Iterator[SearchDocument]:
    if include_sessions:
        yield from _session_documents(config)
    yield from _knowledge_and_qa_documents(config)
    yield from _wiki_documents(config)


def _tokens(text: str) -> str:
    lowered = text.lower()
    values = set(ASCII_TOKEN.findall(lowered))
    for run in CJK_RUN.findall(lowered):
        values.update(run)
        values.update(run[index : index + 2] for index in range(len(run) - 1))
    return " ".join(sorted(value for value in values if value))


def _snippet(text: str, query: str, width: int = 260) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""
    index = compact.lower().find(query.lower())
    if index < 0:
        return compact[:width] + ("…" if len(compact) > width else "")
    start = max(0, index - width // 3)
    end = min(len(compact), start + width)
    return ("…" if start else "") + compact[start:end] + (
        "…" if end < len(compact) else ""
    )


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
        documents = list(_knowledge_and_qa_documents(self.config))
        documents.extend(_wiki_documents(self.config))
        with self._connect() as connection:
            connection.execute("DELETE FROM documents")
            connection.execute("DELETE FROM documents_fts")
            for item in documents:
                connection.execute(
                    """
                    INSERT INTO documents
                    (id, scope, title, body, project, source_session, review_status, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.scope,
                        item.title,
                        item.body,
                        item.project,
                        item.source_session,
                        item.review_status,
                        item.content_hash,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO documents_fts
                    (id, scope, title_tokens, body_tokens) VALUES (?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.scope,
                        _tokens(item.title),
                        _tokens(item.body),
                    ),
                )
        return {"indexed": len(documents), "path": str(self.db_path)}

    def remove(self, document_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            connection.execute("DELETE FROM documents_fts WHERE id = ?", (document_id,))

    def _knowledge_search(
        self, query: str, scope: str, limit: int
    ) -> List[SearchResult]:
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
            start, end = raw.find("["), raw.rfind("]")
            try:
                value = json.loads(raw[start : end + 1]) if start >= 0 < end else []
            except json.JSONDecodeError:
                value = []
        sessions = {item.id: item for item in _session_documents(self.config)}
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
            session = sessions.get(session_id)
            results.append(
                SearchResult(
                    id=session_id,
                    scope="session",
                    title=session.title if session else f"会话 {session_id[:12]}",
                    snippet=str(item.get("snippet") or ""),
                    project=str(
                        metadata.get("project")
                        or (session.project if session else "unknown")
                    ),
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
        if scope in {"all", "knowledge", "wiki", "qa"}:
            result.extend(self._knowledge_search(query, scope, limit))
        result.sort(key=lambda item: item.score, reverse=True)
        return result[:limit]


def _chunk_text(text: str, size: int, overlap: int) -> List[str]:
    compact = text.strip()
    if not compact:
        return []
    size = max(200, size)
    overlap = max(0, min(overlap, size // 2))
    chunks: List[str] = []
    start = 0
    while start < len(compact):
        end = min(len(compact), start + size)
        if end < len(compact):
            break_at = max(
                compact.rfind("\n", start + size // 2, end),
                compact.rfind("。", start + size // 2, end),
            )
            if break_at > start:
                end = break_at + 1
        chunks.append(compact[start:end].strip())
        if end >= len(compact):
            break
        start = max(start + 1, end - overlap)
    return [chunk for chunk in chunks if chunk]


class OnnxSemanticBackend:
    def __init__(self, config: Config):
        self.config = config
        self.model_dir = config.semantic_model_dir
        self.db_path = _search_db_path(config)
        self._session: Any = None
        self._tokenizer: Any = None
        self._error: str | None = None

    def _model_files(self) -> tuple[Path, Path]:
        if not self.model_dir:
            return Path(), Path()
        onnx_dir = self.model_dir / "onnx"
        model = onnx_dir / "model.onnx"
        tokenizer = onnx_dir / "tokenizer.json"
        if not model.exists():
            model = self.model_dir / "model.onnx"
        if not tokenizer.exists():
            tokenizer = self.model_dir / "tokenizer.json"
        return model, tokenizer

    def _load(self) -> None:
        if self._session is not None and self._tokenizer is not None:
            return
        model, tokenizer_path = self._model_files()
        if not model.is_file() or not tokenizer_path.is_file():
            raise FileNotFoundError(
                f"BGE-M3 模型不完整：需要 {model} 和 {tokenizer_path}"
            )
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise RuntimeError(
                "缺少语义检索依赖，请安装 onnxruntime、tokenizers 和 numpy。"
            ) from exc
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=256)
        self._tokenizer.enable_padding()
        self._session = ort.InferenceSession(
            str(model),
            providers=["CPUExecutionProvider"],
        )

    @property
    def available(self) -> bool:
        try:
            self._load()
            return True
        except Exception as exc:
            self._error = str(exc)
            return False

    def supports_scope(self, scope: str) -> bool:
        return scope in {"all", "knowledge", "wiki", "qa"}

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS semantic_documents (
                id TEXT NOT NULL,
                scope TEXT NOT NULL,
                title TEXT NOT NULL,
                project TEXT NOT NULL,
                source_session TEXT NOT NULL,
                review_status TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                vector BLOB NOT NULL,
                dimensions INTEGER NOT NULL,
                PRIMARY KEY (scope, id, chunk_index)
            );
            CREATE INDEX IF NOT EXISTS semantic_scope_idx
            ON semantic_documents(scope);
            """
        )
        return connection

    def _counts(self) -> tuple[int, int]:
        if not self.db_path.exists():
            return 0, 0
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT COUNT(DISTINCT scope || ':' || id) AS documents,
                           COUNT(*) AS chunks
                    FROM semantic_documents
                    """
                ).fetchone()
            return int(row["documents"] or 0), int(row["chunks"] or 0)
        except sqlite3.Error:
            return 0, 0

    def status(self) -> Dict[str, Any]:
        model, tokenizer = self._model_files()
        documents, chunks = self._counts()
        ready = self.available
        return {
            "available": ready,
            "backend": "onnx",
            "model_dir": str(self.model_dir or ""),
            "model_file": str(model),
            "tokenizer_file": str(tokenizer),
            "dimensions": 1024,
            "indexed_documents": documents,
            "indexed_chunks": chunks,
            "indexed_scopes": ["knowledge", "wiki", "qa"],
            "reason": None if ready else self._error,
        }

    def _embed(self, texts: Sequence[str]) -> Any:
        self._load()
        import numpy as np

        result: List[Any] = []
        batch_size = self.config.semantic_batch_size
        for offset in range(0, len(texts), batch_size):
            batch = list(texts[offset : offset + batch_size])
            encoded = self._tokenizer.encode_batch(batch)
            input_ids = np.asarray([item.ids for item in encoded], dtype=np.int64)
            attention_mask = np.asarray(
                [item.attention_mask for item in encoded], dtype=np.int64
            )
            vectors = self._session.run(
                ["sentence_embedding"],
                {"input_ids": input_ids, "attention_mask": attention_mask},
            )[0].astype(np.float32)
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            vectors = vectors / np.maximum(norms, 1e-12)
            result.append(vectors)
        return np.concatenate(result, axis=0)

    def _write_documents(
        self,
        documents: Sequence[SearchDocument],
        *,
        replace_all: bool,
    ) -> Dict[str, Any]:
        if not self.available:
            raise RuntimeError(self._error or "ONNX 语义模型不可用。")
        with self._connect() as connection:
            existing = {
                (str(row["scope"]), str(row["id"])): str(row["content_hash"])
                for row in connection.execute(
                    """
                    SELECT scope, id, MAX(content_hash) AS content_hash
                    FROM semantic_documents GROUP BY scope, id
                    """
                ).fetchall()
            }
        current = {(item.scope, item.id): item for item in documents}
        changed = list(documents) if replace_all else [
            item
            for key, item in current.items()
            if existing.get(key) != item.content_hash
        ]
        rows: List[tuple[SearchDocument, int, str]] = []
        for document in changed:
            text = f"{document.title}\n{document.body}"
            for index, chunk in enumerate(
                _chunk_text(
                    text,
                    self.config.semantic_chunk_size,
                    self.config.semantic_chunk_overlap,
                )
            ):
                rows.append((document, index, chunk))
        vectors = self._embed([row[2] for row in rows]) if rows else []
        with self._connect() as connection:
            if replace_all:
                connection.execute("DELETE FROM semantic_documents")
            else:
                for scope, document_id in set(existing) - set(current):
                    connection.execute(
                        "DELETE FROM semantic_documents WHERE scope = ? AND id = ?",
                        (scope, document_id),
                    )
                for document in changed:
                    connection.execute(
                        "DELETE FROM semantic_documents WHERE scope = ? AND id = ?",
                        (document.scope, document.id),
                    )
            for row, vector in zip(rows, vectors):
                document, chunk_index, chunk = row
                connection.execute(
                    """
                    INSERT INTO semantic_documents
                    (id, scope, title, project, source_session, review_status,
                     content_hash, chunk_index, chunk_text, vector, dimensions)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document.id,
                        document.scope,
                        document.title,
                        document.project,
                        document.source_session,
                        document.review_status,
                        document.content_hash,
                        chunk_index,
                        chunk,
                        vector.astype("<f4").tobytes(),
                        int(vector.shape[0]),
                    ),
                )
        return {
            **self.status(),
            "indexed_documents": len(documents),
            "updated_documents": len(changed),
            "updated_chunks": len(rows),
        }

    def rebuild(self) -> Dict[str, Any]:
        documents = list(iter_search_documents(self.config, include_sessions=False))
        return self._write_documents(documents, replace_all=True)

    def sync(self) -> Dict[str, Any]:
        documents = list(iter_search_documents(self.config, include_sessions=False))
        return self._write_documents(documents, replace_all=False)

    def remove(self, document_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM semantic_documents WHERE id = ?", (document_id,)
            )

    def search(self, query: str, scope: str, limit: int) -> List[SearchResult]:
        if not self.available:
            raise RuntimeError(self._error or "ONNX 语义模型不可用。")
        import numpy as np

        if not self.db_path.exists():
            self.rebuild()
        conditions = "" if scope == "all" else "WHERE scope = ?"
        parameters: tuple[Any, ...] = () if scope == "all" else (scope,)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM semantic_documents {conditions}", parameters
            ).fetchall()
        if not rows:
            return []
        query_vector = self._embed([query])[0]
        best: Dict[tuple[str, str], tuple[float, sqlite3.Row]] = {}
        for row in rows:
            vector = np.frombuffer(row["vector"], dtype="<f4")
            score = float(np.dot(query_vector, vector))
            key = (str(row["scope"]), str(row["id"]))
            if key not in best or score > best[key][0]:
                best[key] = (score, row)
        ranked = sorted(best.values(), key=lambda item: item[0], reverse=True)[:limit]
        return [
            SearchResult(
                id=str(row["id"]),
                scope=str(row["scope"]),
                title=str(row["title"]),
                snippet=str(row["chunk_text"])[:320],
                project=str(row["project"]),
                source_session=str(row["source_session"]),
                score=round(score, 6),
                match_type="semantic",
                review_status=str(row["review_status"]),
            )
            for score, row in ranked
        ]


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
        if scope == "sessions":
            scope = "session"
        if len(query) < 2:
            raise ValueError("搜索内容至少需要两个字符。")
        if scope not in {"all", "session", "knowledge", "wiki", "qa"}:
            raise ValueError("scope 必须是 all、session、knowledge、wiki 或 qa。")
        if mode not in {"keyword", "semantic", "hybrid"}:
            raise ValueError("mode 必须是 keyword、semantic 或 hybrid。")
        limit = max(1, min(limit, 100))
        fallback = None
        effective = mode
        supports_scope = getattr(self.semantic, "supports_scope", lambda _scope: True)
        if (
            mode != "keyword"
            and (
                not self.semantic.available
                or not bool(supports_scope(scope))
            )
        ):
            effective = "keyword"
            fallback = (
                "原始 Session 当前使用 seCall/BM25 检索；Wiki、知识卡片与已审核 QA "
                "使用 BGE-M3 语义索引。"
                if self.semantic.available
                else str(self.semantic.status().get("reason") or "语义检索不可用。")
            )
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
        for key, score in sorted(
            scores.items(), key=lambda pair: pair[1], reverse=True
        )[:limit]
    ]


def build_search_service(config: Config) -> HybridSearchService:
    semantic: SemanticSearchBackend
    if config.semantic_backend == "onnx":
        semantic = OnnxSemanticBackend(config)
    else:
        semantic = UnavailableSemanticBackend(config.semantic_model_dir)
    return HybridSearchService(KeywordSearchBackend(config), semantic)
