from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .chatgpt import inspect_export, parse_export
from .config import Config
from .converter import convert_export, render_markdown
from .knowledge import store_knowledge
from .knowledge_store import (
    atomic_write_text,
    delete_knowledge_document,
    list_knowledge_documents,
    list_knowledge_trash,
    purge_all_knowledge_derivatives,
    read_knowledge_document,
    reconcile_qa_with_knowledge_trash,
    restore_knowledge_document,
    update_knowledge_document,
)
from .opencode_client import OpenCodeClient, Runner
from .rag import answer_with_rag
from .search import HybridSearchService, build_search_service
from .session_review_store import (
    annotate_sessions,
    hide_session,
    restore_session,
    update_session_review,
)
from .session_lifecycle import iter_session_files, migrate_legacy_sessions, move_session_file
from .session_sync import SessionSyncWorker
from .structured_knowledge import (
    build_events_from_markdown,
    derive_legacy_structure,
    read_session_events,
    read_structured_knowledge,
    store_session_events,
    store_structured_knowledge,
    structured_path,
)
from .wiki_store import (
    archive_wiki_page,
    graph_snapshot,
    list_wiki_archive,
    list_wiki_pages,
    purge_all_wiki_archive,
    purge_wiki_archive,
    read_wiki_page,
    rebuild_graph,
    restore_wiki_page,
    sync_wiki_knowledge_views,
)
from .wiki_maintenance import (
    apply_wiki_plan,
    create_wiki_plan,
    ensure_wiki_schema,
    get_wiki_config,
    latest_wiki_lint,
    lint_wiki,
    list_wiki_plans,
    read_wiki_plan,
    reject_wiki_plan,
    update_wiki_config,
)


MAX_BODY_BYTES = 100 * 1024 * 1024
ALLOWED_ORIGINS = {
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}

DISPLAY_TRANSLATIONS = {
    "세션": "会话",
    "턴": "轮",
    "프로젝트": "项目",
    "브랜치": "分支",
    "시간": "时间",
    "사용자": "用户",
    "어시스턴트": "助手",
    "도구": "工具",
    "요약": "摘要",
    "알 수 없음": "未知",
    "벡터 검색 비활성화": "向量检索已禁用",
}


def localize_display_text(value: str) -> str:
    """Translate known legacy seCall Korean labels for the Chinese UI."""
    result = value
    for source, target in DISPLAY_TRANSLATIONS.items():
        result = result.replace(source, target)
    labels = {
        "codex": "Codex",
        "opencode": "OpenCode",
        "chatgpt": "ChatGPT",
        "claude": "Claude",
        "gemini": "Gemini",
    }
    for source, label in labels.items():
        result = re.sub(
            rf"(?im)^(#{{1,6}}\s*)?{source}\s+会话\s*[:：]\s*",
            lambda match: f"{match.group(1) or ''}{label} 会话：",
            result,
        )
    return result


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


def _safe_vault_path(vault: Path, path: Path) -> Path:
    root = vault.resolve()
    candidate = path.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("请求路径不在配置的 seCall Vault 内。") from exc
    return candidate


def list_vault_sessions(
    config: Config,
    limit: Optional[int] = 200,
    *,
    include_hidden: bool = False,
) -> List[Dict[str, Any]]:
    files_with_state = list(iter_session_files(config))
    if not files_with_state:
        return []
    result: List[Dict[str, Any]] = []
    files = sorted(
        files_with_state,
        key=lambda item: item[1].stat().st_mtime,
        reverse=True,
    )
    for storage_state, path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        meta = _frontmatter(text)
        title_match = re.search(r"(?m)^#\s+(.+)$", text)
        raw_title = title_match.group(1) if title_match else path.stem
        result.append(
            {
                "id": meta.get("session_id") or path.stem,
                "title": localize_display_text(raw_title),
                "project": meta.get("project") or "unknown",
                "source": meta.get("source") or meta.get("agent") or "unknown",
                "model": meta.get("model") or "unknown",
                "turns": int(meta.get("turns") or 0),
                "status": "ready",
                "date": meta.get("date") or "",
                "path": str(path),
                "updated": int(path.stat().st_mtime * 1000),
                "storage_state": storage_state,
            }
        )
    annotated = annotate_sessions(config, result, include_hidden=include_hidden)
    if limit is None:
        return annotated
    return annotated[: max(1, min(limit, 1000))]


def paginate_vault_sessions(
    config: Config,
    *,
    page: int = 1,
    page_size: int = 10,
    review_status: str = "all",
    project: str = "",
    query: str = "",
) -> Dict[str, Any]:
    sessions = list_vault_sessions(config, limit=None, include_hidden=True)
    projects = sorted(
        {
            str(item.get("project") or "unknown")
            for item in sessions
            if not item.get("hidden")
        },
        key=str.lower,
    )
    normalized_project = project.strip()
    normalized_query = query.strip().lower()

    def matches_base(item: Dict[str, Any]) -> bool:
        if normalized_project and str(item.get("project") or "").lower() != normalized_project.lower():
            return False
        if normalized_query:
            searchable = " ".join(
                str(item.get(key) or "")
                for key in ("title", "project", "id", "source", "model")
            ).lower()
            if normalized_query not in searchable:
                return False
        return True

    scoped = [item for item in sessions if matches_base(item)]
    visible = [item for item in scoped if not item.get("hidden")]
    hidden = [item for item in scoped if item.get("hidden")]
    counts = {
        "all": len(visible),
        "pending": sum(item.get("review_status") == "pending" for item in visible),
        "approved": sum(item.get("review_status") == "approved" for item in visible),
        "rejected": sum(item.get("review_status") == "rejected" for item in visible),
        "hidden": len(hidden),
    }
    if review_status == "hidden":
        filtered = hidden
    elif review_status == "all":
        filtered = visible
    elif review_status in {"pending", "approved", "rejected"}:
        filtered = [
            item for item in visible if item.get("review_status") == review_status
        ]
    else:
        raise ValueError("review_status 必须是 all、pending、approved、rejected 或 hidden。")

    page_size = max(1, min(page_size, 1000))
    total = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    return {
        "items": filtered[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_previous": page > 1,
        "has_next": page < total_pages,
        "counts": counts,
        "projects": projects,
    }


def read_vault_session(config: Config, session_id: str) -> Dict[str, Any]:
    sessions = list_vault_sessions(config, limit=None, include_hidden=True)
    match = next((item for item in sessions if item["id"] == session_id), None)
    if not match:
        raise FileNotFoundError(f"Vault 中不存在 Session：{session_id}")
    path = _safe_vault_path(config.vault, Path(match["path"]))
    markdown = path.read_text(encoding="utf-8", errors="replace")
    events = read_session_events(config.vault, session_id)
    if not events:
        events = build_events_from_markdown(markdown)
    metadata = _frontmatter(markdown)
    localized = localize_display_text(markdown)
    full_length = len(localized)
    preview_limit = 180_000
    truncated = full_length > preview_limit
    if truncated:
        localized = (
            localized[:130_000]
            + "\n\n> **预览提示**：中间内容较长，已在前端预览中折叠。"
            + "原始 Session 未被修改。\n\n"
            + localized[-50_000:]
        )

    tool_calls = len(re.findall(r"(?m)^>\s*\[!tool\]", markdown))
    user_turns = len(re.findall(r"(?mi)^#{2,3}\s+Turn\s+\d+.*User", markdown))
    assistant_turns = len(
        re.findall(r"(?mi)^#{2,3}\s+Turn\s+\d+.*Assistant", markdown)
    )
    conclusion_terms = ("完成", "解决", "验证", "结论", "通过", "成功", "修复")
    has_conclusion = any(term in markdown[-8000:] for term in conclusion_terms)
    score = 100
    turns = int(match.get("turns") or 0)
    if turns <= 2:
        score -= 35
    elif turns <= 5:
        score -= 15
    if full_length < 1000:
        score -= 30
    elif full_length < 5000:
        score -= 10
    if tool_calls == 0:
        score -= 10
    if not has_conclusion:
        score -= 20
    score = max(0, min(score, 100))
    flags: List[str] = []
    if turns <= 2:
        flags.append("会话轮次较少")
    if full_length < 1000:
        flags.append("正文内容较短")
    if tool_calls == 0:
        flags.append("未检测到工具调用证据")
    if not has_conclusion:
        flags.append("末尾未检测到明确结论")
    if not flags:
        flags.append("结构和证据要素较完整")

    return {
        **match,
        "metadata": metadata,
        "markdown": localized,
        "full_length": full_length,
        "truncated": truncated,
        "quality": {
            "score": score,
            "level": "high" if score >= 80 else "medium" if score >= 55 else "low",
            "flags": flags,
            "tool_calls": tool_calls,
            "user_turns": user_turns,
            "assistant_turns": assistant_turns,
            "has_conclusion": has_conclusion,
        },
        "events": events,
        "event_count": len(events),
    }


def list_knowledge(config: Config, limit: int = 200) -> List[Dict[str, Any]]:
    return list_knowledge_documents(config, limit)


def read_qa(config: Config) -> List[Dict[str, Any]]:
    path = config.vault / config.qa_file
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


def backfill_structured_knowledge(
    config: Config,
    *,
    source_session: Optional[str] = None,
) -> Dict[str, Any]:
    """Create sidecars for legacy cards without changing their Markdown or QA."""
    sessions = {
        item["id"]: item
        for item in list_vault_sessions(config, limit=None, include_hidden=True)
    }
    qa_by_session: Dict[str, List[Dict[str, Any]]] = {}
    for item in read_qa(config):
        qa_by_session.setdefault(str(item.get("source_session") or ""), []).append(item)
    created = 0
    skipped = 0
    for summary in list_knowledge_documents(config, limit=10000):
        session_id = str(summary.get("source_session") or "")
        if not session_id or (source_session and session_id != source_session):
            continue
        if read_structured_knowledge(config.vault, session_id):
            skipped += 1
            continue
        detail = read_knowledge_document(config, summary["id"])
        events = read_session_events(config.vault, session_id)
        session = sessions.get(session_id)
        source_markdown = ""
        if session:
            source_path = _safe_vault_path(config.vault, Path(session["path"]))
            source_markdown = source_path.read_text(encoding="utf-8", errors="replace")
        if not events and source_markdown:
            events = build_events_from_markdown(source_markdown)
            if events:
                store_session_events(config.vault, session_id, events)
        structured = derive_legacy_structure(
            detail["markdown"],
            qa_by_session.get(session_id, []),
            session_id=session_id,
            project=detail["project"],
            events=events,
        )
        store_structured_knowledge(config.vault, structured)
        created += 1
    return {"created": created, "skipped": skipped}


def write_qa(config: Config, items: List[Dict[str, Any]]) -> None:
    path = config.vault / config.qa_file
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items)
    atomic_write_text(path, payload)


class ChatGPTImportFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        imported: int,
        conversation_id: str,
        conversation_title: str,
        conversation_index: int,
        original: Exception,
    ) -> None:
        super().__init__(message)
        self.imported = imported
        self.conversation_id = conversation_id
        self.conversation_title = conversation_title
        self.conversation_index = conversation_index
        self.original = original


class OpenCodeImportFailure(RuntimeError):
    def __init__(self, message: str, *, session_id: str, original: Exception) -> None:
        super().__init__(message)
        self.session_id = session_id
        self.original = original


def import_chatgpt(
    config: Config,
    payload: Any,
    project: str,
    limit: Optional[int] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    conversations = parse_export(payload, limit=limit)
    results: List[Dict[str, Any]] = []
    for index, conversation in enumerate(conversations):
        try:
            converted = convert_export(
                conversation.as_export(project),
                config.vault,
                overwrite=overwrite,
                destination_dir="staging/sessions",
            )
        except Exception as exc:
            raise ChatGPTImportFailure(
                f"写入会话“{conversation.title}”失败：{exc}",
                imported=len(results),
                conversation_id=conversation.id,
                conversation_title=conversation.title,
                conversation_index=index + 1,
                original=exc,
            ) from exc
        results.append(converted.as_dict())
    return {
        "imported": len(results),
        "project": project,
        "sessions": results,
    }


def inspect_opencode_export(payload: Any, project: str = "") -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("OpenCode 导出必须是一个 JSON 对象。")
    markdown, metadata = render_markdown(payload)
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    return {
        "session_id": metadata["session_id"],
        "title": str(info.get("title") or metadata["project"]),
        "project": project or metadata["project"],
        "message_count": len(payload.get("messages") or []),
        "turns": metadata["turns"],
        "tools": list(metadata["tools"]),
        "rendered_bytes": len(markdown.encode("utf-8")),
    }


def import_opencode_export(
    config: Config,
    payload: Any,
    project: str,
    overwrite: bool = False,
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("OpenCode 导出必须是一个 JSON 对象。")
    # Copy the uploaded JSON: we add local import metadata but never mutate the
    # request payload or the external machine's original export.
    exported = json.loads(json.dumps(payload, ensure_ascii=False))
    info = exported.get("info")
    if not isinstance(info, dict):
        raise ValueError("OpenCode 导出缺少 info 对象。")
    session_id = str(info.get("id") or "")
    try:
        if project:
            info["project"] = project
        info.setdefault("source", "opencode")
        converted = convert_export(
            exported,
            config.vault,
            overwrite=overwrite,
            destination_dir="staging/sessions",
        )
    except Exception as exc:
        raise OpenCodeImportFailure(
            f"写入 OpenCode 会话失败：{exc}",
            session_id=session_id,
            original=exc,
        ) from exc
    return {
        "imported": 1,
        "project": project or converted.project,
        "session": converted.as_dict(),
    }


def run_session_pipeline(
    config: Config,
    session_id: str,
    model: Optional[str] = None,
    reindex: bool = True,
    overwrite: bool = False,
    timeout: int = 1800,
) -> Dict[str, Any]:
    started_at = time.monotonic()
    stages: List[Dict[str, Any]] = []

    def record_stage(name: str, stage_started: float, detail: str) -> None:
        stages.append(
            {
                "name": name,
                "duration_seconds": round(time.monotonic() - stage_started, 2),
                "detail": detail,
            }
        )

    stage_started = time.monotonic()
    sessions = list_vault_sessions(config, limit=None, include_hidden=True)
    match = next((item for item in sessions if item["id"] == session_id), None)
    if not match:
        raise FileNotFoundError(f"Vault 中不存在 Session：{session_id}")
    if match["hidden"]:
        raise ValueError("该会话已在前端隐藏，请先恢复后再运行流水线。")
    if match["review_status"] != "approved" or match["storage_state"] != "approved":
        raise ValueError("该会话尚未通过预审核，只有“已通过”的会话可以运行流水线。")
    session_path = _safe_vault_path(config.vault, Path(match["path"]))
    source_markdown = session_path.read_text(encoding="utf-8")
    record_stage("读取并验证会话", stage_started, f"{match['turns']} 轮消息，预审核已通过")

    events = read_session_events(config.vault, session_id)
    if not events:
        events = build_events_from_markdown(source_markdown)
        if events:
            store_session_events(config.vault, session_id, events)
    stages[-1]["detail"] += f"，已建立 {len(events)} 个可追溯事件"

    existing_issue: Optional[Path] = None
    for issue_path in (config.vault / config.knowledge_dir).glob("*.md"):
        if _frontmatter(issue_path.read_text(encoding="utf-8")).get("source_session") == session_id:
            existing_issue = issue_path
            break

    def qa_count_for_session() -> int:
        qa_path = config.vault / config.qa_file
        if not qa_path.exists():
            return 0
        count = 0
        for line in qa_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and str(item.get("source_session") or "") == session_id:
                count += 1
        return count

    reused = existing_issue is not None and not overwrite
    if reused:
        backfill_structured_knowledge(config, source_session=session_id)
        structured = read_structured_knowledge(config.vault, session_id) or {}
        stages.append(
            {
                "name": "OpenCode 知识抽取",
                "duration_seconds": 0.0,
                "detail": "检测到现有 Issue Card，本次未重复调用模型。",
            }
        )
        stages.append(
            {
                "name": "写入知识库",
                "duration_seconds": 0.0,
                "detail": "已安全复用现有知识；如需重新生成请启用覆盖。",
            }
        )
        knowledge_result = {
            "issue_path": str(existing_issue),
            "qa_path": str(config.vault / config.qa_file),
            "qa_count": qa_count_for_session(),
            "new_qa_count": 0,
            "structured_path": (
                str(structured_path(config.vault, session_id)) if structured else ""
            ),
            "quality": dict(structured.get("quality") or {}),
        }
    else:
        stage_started = time.monotonic()
        ensure_wiki_schema(config)
        prompt_template = (Path(__file__).parent / "prompts" / "issue-card.md").read_text(
            encoding="utf-8"
        )
        wiki_root = config.vault / "wiki"
        prompt = config.vault / "knowledge" / ".runtime" / "wiki-analysis-prompt.md"
        prompt.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            prompt,
            prompt_template.rstrip()
            + "\n\n# 当前 Wiki 目标\n\n"
            + (wiki_root / "purpose.md").read_text(encoding="utf-8")
            + "\n\n# 当前 Wiki Schema\n\n"
            + (wiki_root / "schema.md").read_text(encoding="utf-8"),
        )
        generated = OpenCodeClient(config.opencode_command).run_generation(
            session_path,
            prompt,
            config.vault,
            model=model or config.model,
            timeout=timeout,
        )
        record_stage("OpenCode 知识抽取", stage_started, "已生成 Issue Card 与候选 QA")

        stage_started = time.monotonic()
        knowledge = store_knowledge(
            generated,
            source_markdown,
            config.vault,
            config.knowledge_dir,
            config.qa_file,
            overwrite=overwrite,
        )
        knowledge_result = knowledge.as_dict()
        knowledge_result["new_qa_count"] = knowledge.qa_count
        knowledge_result["qa_count"] = qa_count_for_session()
        record_stage(
            "写入知识库",
            stage_started,
            f"新增 {knowledge.qa_count} 条候选 QA",
        )
    indexed = False
    if reindex:
        stage_started = time.monotonic()
        Runner(config.secall_command).run("reindex", "--from-vault", timeout=600)
        indexed = True
        record_stage("重建 seCall 索引", stage_started, "会话全文索引已刷新")
    stage_started = time.monotonic()
    wiki_plan = create_wiki_plan(config, reason=f"pipeline:{session_id}")
    record_stage(
        "生成 Wiki 更新计划",
        stage_started,
        f"待审核 {wiki_plan['summary']['total']} 项跨页面变更",
    )
    return {
        "session_id": session_id,
        "knowledge": knowledge_result,
        "indexed": indexed,
        "reused": reused,
        "wiki_plan_id": wiki_plan["plan_id"],
        "wiki_changes": wiki_plan["summary"],
        "requires_review": wiki_plan["requires_review"],
        "stages": stages,
        "elapsed_seconds": round(time.monotonic() - started_at, 2),
    }


class LocalAPIHandler(BaseHTTPRequestHandler):
    server_version = "seCallOpenCodeLocal/0.8"

    @property
    def config(self) -> Config:
        return self.server.config  # type: ignore[attr-defined]

    @property
    def search(self) -> HybridSearchService:
        return self.server.search  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[local-api] {self.address_string()} {fmt % args}")

    def _origin(self) -> Optional[str]:
        return self.headers.get("Origin")

    def _cors(self) -> None:
        origin = self._origin()
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header(
                "Access-Control-Allow-Methods",
                "GET, POST, PUT, DELETE, OPTIONS",
            )

    def _send(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, result: Any, status: int = HTTPStatus.OK) -> None:
        self._send(status, {"ok": True, "result": result})

    def _fail(self, exc: Exception, status: int = HTTPStatus.BAD_REQUEST) -> None:
        self._send(
            status,
            {
                "ok": False,
                "error": {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                },
            },
        )

    def _fail_chatgpt_import(self, exc: Exception, stage: str) -> None:
        original = exc.original if isinstance(exc, ChatGPTImportFailure) else exc
        details: Dict[str, Any] = {}
        if isinstance(exc, ChatGPTImportFailure):
            details = {
                "imported_before_failure": exc.imported,
                "failed_conversation_index": exc.conversation_index,
                "failed_conversation_id": exc.conversation_id,
                "failed_conversation_title": exc.conversation_title,
            }

        if isinstance(original, FileExistsError):
            code = "SESSION_CONFLICT"
            status = HTTPStatus.CONFLICT
            hint = "目标会话已存在但内容不同。请检查同名会话，或在确认后使用覆盖导入。"
        elif isinstance(original, PermissionError):
            code = "VAULT_PERMISSION_DENIED"
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            hint = "请确认 Vault 目录具有写入权限，且文件未被其他程序锁定。"
        elif isinstance(original, OSError):
            code = "VAULT_WRITE_FAILED"
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            hint = "请检查 Vault 路径、剩余磁盘空间和文件占用状态。"
        elif isinstance(original, (ValueError, TypeError)):
            code = "INVALID_CHATGPT_EXPORT"
            status = HTTPStatus.UNPROCESSABLE_ENTITY
            hint = "请选择 ChatGPT 官方导出的 conversations.json；文件中至少需要一个包含文本消息的会话。"
        else:
            code = "CHATGPT_IMPORT_FAILED"
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            hint = "请复制完整错误详情，并结合本地服务日志进一步排查。"

        details["cause"] = str(original)
        self._send(
            status,
            {
                "ok": False,
                "error": {
                    "type": original.__class__.__name__,
                    "code": code,
                    "stage": stage,
                    "message": str(exc),
                    "hint": hint,
                    "details": details,
                },
            },
        )

    def _fail_opencode_import(self, exc: Exception, stage: str) -> None:
        original = exc.original if isinstance(exc, OpenCodeImportFailure) else exc
        details: Dict[str, Any] = {"cause": str(original)}
        if isinstance(exc, OpenCodeImportFailure):
            details["session_id"] = exc.session_id
        if isinstance(original, FileExistsError):
            code, status = "SESSION_CONFLICT", HTTPStatus.CONFLICT
            hint = "该会话已存在但内容不同。请确认来源文件，或在确认后允许覆盖导入。"
        elif isinstance(original, PermissionError):
            code, status = "VAULT_PERMISSION_DENIED", HTTPStatus.INTERNAL_SERVER_ERROR
            hint = "请确认 Vault 目录可写，且文件没有被其他程序占用。"
        elif isinstance(original, OSError):
            code, status = "VAULT_WRITE_FAILED", HTTPStatus.INTERNAL_SERVER_ERROR
            hint = "请检查 Vault 路径、磁盘空间和文件占用状态。"
        elif isinstance(original, (ValueError, TypeError)):
            code, status = "INVALID_OPENCODE_EXPORT", HTTPStatus.UNPROCESSABLE_ENTITY
            hint = "请选择由 OpenCode/codeagent 的 export 命令生成的完整 JSON 文件。"
        else:
            code, status = "OPENCODE_IMPORT_FAILED", HTTPStatus.INTERNAL_SERVER_ERROR
            hint = "请复制完整错误详情，并结合本地服务日志继续排查。"
        self._send(status, {"ok": False, "error": {
            "type": original.__class__.__name__, "code": code, "stage": stage,
            "message": str(exc), "hint": hint, "details": details,
        }})

    def _json_body(self) -> Any:
        raw_length = self.headers.get("Content-Length")
        if not raw_length:
            raise ValueError("请求缺少 JSON 内容。")
        length = int(raw_length)
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("请求内容为空或超过 100 MB 限制。")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"请求不是有效 JSON：{exc}") from exc

    def _refresh_search(self) -> Dict[str, Any]:
        keyword = self.search.keyword.rebuild()
        semantic_sync = getattr(self.search.semantic, "sync", None)
        semantic = (
            semantic_sync()
            if self.search.semantic.available and callable(semantic_sync)
            else self.search.semantic.status()
        )
        return {"keyword": keyword, "semantic": semantic}

    def _sync_knowledge_derivatives(self) -> Dict[str, Any]:
        qa = reconcile_qa_with_knowledge_trash(self.config)
        wiki = sync_wiki_knowledge_views(self.config)
        graph = graph_snapshot(self.config)
        search = self._refresh_search()
        return {
            "qa": qa,
            "wiki": wiki,
            "graph": graph["stats"],
            "search": search,
        }

    def do_OPTIONS(self) -> None:  # noqa: N802
        if self._origin() not in ALLOWED_ORIGINS:
            self._send(HTTPStatus.FORBIDDEN, {"ok": False, "error": {"message": "不允许的来源。"}})
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            limit = int(query.get("limit", ["200"])[0])
            if parsed.path == "/api/health":
                client = OpenCodeClient(self.config.opencode_command)
                opencode_version = client.version()
                models = client.models()
                sessions = list_vault_sessions(self.config, limit=None)
                knowledge = list_knowledge(self.config, limit=1000)
                qa = read_qa(self.config)
                wiki = list_wiki_pages(self.config, limit=2000)
                graph = graph_snapshot(self.config)
                self._ok(
                    {
                        "ready": True,
                        "api_version": __version__,
                        "vault": str(self.config.vault),
                        "opencode_version": opencode_version,
                        "models": models,
                        "configured_model": self.config.model,
                        "sessions": len(sessions),
                        "knowledge": len(knowledge),
                        "qa": len(qa),
                        "pending_qa": sum(item.get("review_status") == "pending" for item in qa),
                        "wiki": wiki["count"],
                        "graph": graph["stats"],
                        "sync": self.server.sync_worker.status(),  # type: ignore[attr-defined]
                        "semantic": self.search.semantic.status(),
                    }
                )
            elif parsed.path == "/api/sessions":
                if "page" in query or "page_size" in query:
                    self._ok(
                        paginate_vault_sessions(
                            self.config,
                            page=int(query.get("page", ["1"])[0]),
                            page_size=int(query.get("page_size", ["10"])[0]),
                            review_status=str(
                                query.get("review_status", ["all"])[0]
                            ),
                            project=str(query.get("project", [""])[0]),
                            query=str(query.get("q", [""])[0]),
                        )
                    )
                else:
                    self._ok(list_vault_sessions(self.config, limit))
            elif parsed.path == "/api/sessions/hidden":
                hidden = [
                    item
                    for item in list_vault_sessions(
                        self.config, limit=None, include_hidden=True
                    )
                    if item["hidden"]
                ]
                self._ok(hidden[: max(1, min(limit, 1000))])
            elif parsed.path.startswith("/api/sessions/"):
                session_id = unquote(parsed.path.removeprefix("/api/sessions/"))
                self._ok(read_vault_session(self.config, session_id))
            elif parsed.path == "/api/knowledge":
                self._ok(list_knowledge(self.config, limit))
            elif parsed.path == "/api/knowledge/trash":
                self._ok(list_knowledge_trash(self.config))
            elif parsed.path == "/api/wiki":
                self._ok(
                    list_wiki_pages(
                        self.config,
                        category=str(query.get("category", ["all"])[0]),
                        query=str(query.get("q", [""])[0]),
                        limit=limit,
                    )
                )
            elif parsed.path == "/api/wiki/config":
                self._ok(get_wiki_config(self.config))
            elif parsed.path == "/api/wiki/plans":
                self._ok(list_wiki_plans(self.config, str(query.get("status", ["all"])[0])))
            elif parsed.path == "/api/wiki/lint/latest":
                self._ok(latest_wiki_lint(self.config))
            elif parsed.path == "/api/wiki/trash":
                self._ok(list_wiki_archive(self.config))
            elif parsed.path.startswith("/api/wiki/plans/"):
                plan_id = unquote(parsed.path.removeprefix("/api/wiki/plans/"))
                self._ok(read_wiki_plan(self.config, plan_id))
            elif parsed.path.startswith("/api/wiki/"):
                wiki_id = parsed.path.removeprefix("/api/wiki/")
                parts = [unquote(part) for part in wiki_id.split("/", 1)]
                if len(parts) != 2:
                    raise FileNotFoundError("Wiki 页面地址无效。")
                self._ok(read_wiki_page(self.config, parts[0], parts[1]))
            elif parsed.path == "/api/graph":
                self._ok(graph_snapshot(self.config))
            elif parsed.path.startswith("/api/knowledge/"):
                knowledge_id = unquote(parsed.path.removeprefix("/api/knowledge/"))
                self._ok(read_knowledge_document(self.config, knowledge_id))
            elif parsed.path == "/api/qa":
                self._ok(read_qa(self.config)[: max(1, min(limit, 1000))])
            elif parsed.path == "/api/search":
                self._ok(
                    self.search.search(
                        str(query.get("q", [""])[0]),
                        scope=str(query.get("scope", ["all"])[0]),
                        mode=str(query.get("mode", ["keyword"])[0]),
                        limit=limit,
                        filters={
                            key: str(query.get(key, [""])[0])
                            for key in (
                                "project",
                                "module",
                                "confidence",
                                "review_status",
                                "knowledge_type",
                            )
                            if str(query.get(key, [""])[0]).strip()
                        },
                    )
                )
            elif parsed.path == "/api/search/status":
                self._ok(self.search.semantic.status())
            elif parsed.path == "/api/sync/status":
                self._ok(self.server.sync_worker.status())  # type: ignore[attr-defined]
            else:
                self._fail(FileNotFoundError("接口不存在。"), HTTPStatus.NOT_FOUND)
        except FileNotFoundError as exc:
            self._fail(exc, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._fail(exc, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            body = self._json_body()
            if not isinstance(body, dict):
                raise ValueError("请求体必须是 JSON 对象。")
            if parsed.path == "/api/chatgpt/inspect":
                try:
                    self._ok(inspect_export(body.get("payload"), int(body.get("limit") or 20)))
                except Exception as exc:
                    self._fail_chatgpt_import(exc, "验证会话结构")
            elif parsed.path == "/api/opencode/inspect":
                project = str(body.get("project") or "").strip()
                try:
                    self._ok(inspect_opencode_export(body.get("payload"), project))
                except Exception as exc:
                    self._fail_opencode_import(exc, "验证 OpenCode 导出结构")
            elif parsed.path == "/api/chatgpt/import":
                project = str(body.get("project") or "chatgpt-import").strip()
                if not project:
                    raise ValueError("project 不能为空。")
                try:
                    self._ok(
                        import_chatgpt(
                            self.config,
                            body.get("payload"),
                            project,
                            limit=int(body["limit"]) if body.get("limit") is not None else None,
                            overwrite=bool(body.get("overwrite")),
                        ),
                        HTTPStatus.CREATED,
                    )
                except Exception as exc:
                    self._fail_chatgpt_import(exc, "写入会话 Vault")
            elif parsed.path == "/api/opencode/import":
                project = str(body.get("project") or "external-opencode").strip()
                try:
                    self._ok(
                        import_opencode_export(
                            self.config, body.get("payload"), project,
                            overwrite=bool(body.get("overwrite")),
                        ),
                        HTTPStatus.CREATED,
                    )
                except Exception as exc:
                    self._fail_opencode_import(exc, "写入会话 Vault")
            elif parsed.path == "/api/pipeline":
                reindex_requested = bool(body.get("reindex", True))
                result = run_session_pipeline(
                    self.config,
                    str(body.get("session_id") or ""),
                    model=str(body["model"]) if body.get("model") else None,
                    reindex=reindex_requested,
                    overwrite=bool(body.get("overwrite")),
                    timeout=int(body.get("timeout") or 1800),
                )
                wiki_sync = sync_wiki_knowledge_views(self.config)
                if reindex_requested:
                    search_started = time.monotonic()
                    search_result = self._refresh_search()
                    search_elapsed = round(time.monotonic() - search_started, 2)
                    result["stages"].append(
                        {
                            "name": "重建关键词与语义索引",
                            "duration_seconds": search_elapsed,
                            "detail": (
                                f"关键词 {search_result['keyword'].get('indexed', 0)} 篇，"
                                f"向量 {search_result['semantic'].get('indexed_documents', 0)} 篇"
                            ),
                        }
                    )
                    result["elapsed_seconds"] = round(
                        float(result["elapsed_seconds"]) + search_elapsed, 2
                    )
                else:
                    result["stages"].extend(
                        [
                            {
                                "name": "重建 seCall 索引",
                                "duration_seconds": 0.0,
                                "detail": "已按本次运行配置跳过。",
                            },
                            {
                                "name": "重建关键词与语义索引",
                                "duration_seconds": 0.0,
                                "detail": "已按本次运行配置跳过。",
                            },
                        ]
                    )
                result["derivatives"] = {
                    "wiki": wiki_sync,
                    "graph": graph_snapshot(self.config)["stats"],
                }
                self._ok(result)
            elif parsed.path == "/api/wiki/rebuild":
                plan = create_wiki_plan(
                    self.config,
                    reason="manual-rebuild",
                    regenerate=bool(body.get("regenerate", True)),
                )
                self._ok(plan, HTTPStatus.CREATED)
            elif parsed.path == "/api/wiki/lint":
                report = lint_wiki(self.config)
                if bool(body.get("create_fix_plan")) and report["finding_count"]:
                    report["fix_plan"] = create_wiki_plan(
                        self.config, reason="lint-repair", regenerate=False
                    )
                self._ok(report)
            elif (
                parsed.path.startswith("/api/wiki/plans/")
                and parsed.path.endswith("/apply")
            ):
                plan_id = unquote(
                    parsed.path.removeprefix("/api/wiki/plans/").removesuffix("/apply")
                ).rstrip("/")
                selected = body.get("selected_change_ids")
                if selected is not None and not isinstance(selected, list):
                    raise ValueError("selected_change_ids 必须是数组。")
                applied = apply_wiki_plan(self.config, plan_id, selected)
                applied["search"] = self._refresh_search()
                applied["graph"] = graph_snapshot(self.config)["stats"]
                self._ok(applied)
            elif (
                parsed.path.startswith("/api/wiki/plans/")
                and parsed.path.endswith("/reject")
            ):
                plan_id = unquote(
                    parsed.path.removeprefix("/api/wiki/plans/").removesuffix("/reject")
                ).rstrip("/")
                self._ok(reject_wiki_plan(self.config, plan_id, str(body.get("reason") or "")))
            elif parsed.path == "/api/index":
                result = Runner(self.config.secall_command).run(
                    "reindex", "--from-vault", timeout=600
                )
                search_result = self._refresh_search()
                self._ok(
                    {
                        "indexed": True,
                        "output": result.stdout.strip(),
                        "search": search_result,
                    }
                )
            elif parsed.path == "/api/knowledge/sync":
                self._ok(self._sync_knowledge_derivatives())
            elif parsed.path == "/api/knowledge/derivatives/purge":
                if str(body.get("confirm") or "") != "PURGE_DERIVED":
                    raise ValueError("清空全部知识派生数据需要明确确认。")
                result = purge_all_knowledge_derivatives(self.config)
                result["search"] = self._refresh_search()
                result["wiki"] = list_wiki_pages(self.config, limit=2000)
                result["graph"] = graph_snapshot(self.config)["stats"]
                self._ok(result)
            elif parsed.path == "/api/sync/now":
                self._ok(self.server.sync_worker.scan(force=True))  # type: ignore[attr-defined]
            elif parsed.path == "/api/rag/query":
                self._ok(
                    answer_with_rag(
                        self.config,
                        self.search,
                        str(body.get("question") or ""),
                        scope=str(body.get("scope") or "all"),
                        mode=str(body.get("mode") or "hybrid"),
                        limit=max(1, min(int(body.get("limit") or 6), 12)),
                        model=str(body["model"]) if body.get("model") else None,
                        timeout=int(body.get("timeout") or 600),
                    )
                )
            elif parsed.path == "/api/graph/rebuild":
                result = rebuild_graph(self.config)
                self._ok(result)
            elif (
                parsed.path.startswith("/api/sessions/")
                and parsed.path.endswith("/review")
            ):
                session_id = unquote(
                    parsed.path.removeprefix("/api/sessions/").removesuffix("/review")
                ).rstrip("/")
                known = {
                    item["id"]
                    for item in list_vault_sessions(
                        self.config, limit=None, include_hidden=True
                    )
                }
                if session_id not in known:
                    raise FileNotFoundError(f"Vault 中不存在 Session：{session_id}")
                requested_status = str(body.get("status") or "")
                target_state = {
                    "approved": "approved",
                    "rejected": "rejected",
                    "pending": "pending",
                }.get(requested_status)
                if target_state is None:
                    raise ValueError("审核状态必须是 pending、approved 或 rejected。")
                move_session_file(self.config, session_id, target_state)
                result = update_session_review(
                    self.config,
                    session_id,
                    requested_status,
                    str(body.get("note") or ""),
                )
                self._refresh_search()
                self._ok(result)
            elif (
                parsed.path.startswith("/api/sessions/")
                and parsed.path.endswith("/restore")
            ):
                session_id = unquote(
                    parsed.path.removeprefix("/api/sessions/").removesuffix("/restore")
                ).rstrip("/")
                result = restore_session(self.config, session_id)
                self._refresh_search()
                self._ok(result)
            elif parsed.path == "/api/qa/review":
                qa_id = str(body.get("id") or "")
                status = str(body.get("status") or "")
                if status not in {"approved", "rejected", "pending"}:
                    raise ValueError("status 必须是 approved、rejected 或 pending。")
                items = read_qa(self.config)
                matched = False
                for item in items:
                    if str(item.get("id")) == qa_id:
                        if status == "approved" and not (
                            item.get("evidence")
                            or item.get("evidence_event_ids")
                        ):
                            raise ValueError(
                                "该 QA 缺少来源证据，补充 evidence 或"
                                " evidence_event_ids 后才能通过审核。"
                            )
                        item["review_status"] = status
                        matched = True
                        break
                if not matched:
                    raise FileNotFoundError(f"QA 不存在：{qa_id}")
                write_qa(self.config, items)
                self._refresh_search()
                self._ok({"id": qa_id, "review_status": status})
            elif (
                parsed.path.startswith("/api/knowledge/trash/")
                and parsed.path.endswith("/restore")
            ):
                trash_id = parsed.path.removeprefix("/api/knowledge/trash/").removesuffix(
                    "/restore"
                )
                restored = restore_knowledge_document(
                    self.config,
                    unquote(trash_id.rstrip("/")),
                )
                restored["derivatives"] = self._sync_knowledge_derivatives()
                self._ok(restored)
            elif (
                parsed.path.startswith("/api/wiki/trash/")
                and parsed.path.endswith("/restore")
            ):
                trash_id = parsed.path.removeprefix("/api/wiki/trash/").removesuffix(
                    "/restore"
                )
                restored_wiki = restore_wiki_page(
                    self.config,
                    unquote(trash_id.rstrip("/")),
                )
                restored_wiki["derivatives"] = self._sync_knowledge_derivatives()
                self._ok(restored_wiki)
            else:
                self._fail(FileNotFoundError("接口不存在。"), HTTPStatus.NOT_FOUND)
        except FileNotFoundError as exc:
            self._fail(exc, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._fail(exc)

    def do_PUT(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            body = self._json_body()
            if not isinstance(body, dict):
                raise ValueError("请求体必须是 JSON 对象。")
            if parsed.path == "/api/wiki/config":
                self._ok(update_wiki_config(self.config, body))
                return
            if not parsed.path.startswith("/api/knowledge/"):
                raise FileNotFoundError("接口不存在。")
            knowledge_id = unquote(parsed.path.removeprefix("/api/knowledge/"))
            updated = update_knowledge_document(self.config, knowledge_id, body)
            updated["derivatives"] = self._sync_knowledge_derivatives()
            self._ok(updated)
        except FileNotFoundError as exc:
            self._fail(exc, HTTPStatus.NOT_FOUND)
        except RuntimeError as exc:
            self._fail(exc, HTTPStatus.CONFLICT)
        except Exception as exc:
            self._fail(exc)

    def do_DELETE(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/sessions/"):
                session_id = unquote(parsed.path.removeprefix("/api/sessions/"))
                known = {
                    item["id"]: item
                    for item in list_vault_sessions(
                        self.config, limit=None, include_hidden=True
                    )
                }
                if session_id not in known:
                    raise FileNotFoundError(f"Vault 中不存在 Session：{session_id}")
                hidden = hide_session(
                    self.config,
                    session_id,
                    str(known[session_id].get("review_status") or "pending"),
                )
                self._refresh_search()
                self._ok(hidden)
                return
            if parsed.path == "/api/wiki/trash":
                query = parse_qs(parsed.query)
                if query.get("confirm", [""])[0] != "clear":
                    raise ValueError("清空 Wiki 回收站需要 confirm=clear。")
                self._ok(purge_all_wiki_archive(self.config))
                return
            if parsed.path.startswith("/api/wiki/trash/"):
                query = parse_qs(parsed.query)
                if query.get("confirm", [""])[0] != "permanent":
                    raise ValueError("永久删除 Wiki 需要 confirm=permanent。")
                trash_id = unquote(parsed.path.removeprefix("/api/wiki/trash/"))
                self._ok(purge_wiki_archive(self.config, trash_id))
                return
            if parsed.path.startswith("/api/wiki/"):
                wiki_id = parsed.path.removeprefix("/api/wiki/")
                parts = [unquote(part) for part in wiki_id.split("/", 1)]
                if len(parts) != 2:
                    raise ValueError("Wiki 页面 ID 必须包含分类和页面名。")
                archived = archive_wiki_page(self.config, parts[0], parts[1])
                archived["derivatives"] = self._sync_knowledge_derivatives()
                self._ok(archived)
                return
            if not parsed.path.startswith("/api/knowledge/"):
                raise FileNotFoundError("接口不存在。")
            knowledge_id = unquote(parsed.path.removeprefix("/api/knowledge/"))
            deleted = delete_knowledge_document(self.config, knowledge_id)
            deleted["derivatives"] = self._sync_knowledge_derivatives()
            self._ok(deleted)
        except FileNotFoundError as exc:
            self._fail(exc, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._fail(exc)


class LocalAPIServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: Tuple[str, int], config: Config):
        super().__init__(address, LocalAPIHandler)
        self.config = config
        self.search = build_search_service(config)
        self.sync_worker = SessionSyncWorker(config)


def serve(config: Config, host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("本地 API 默认只允许绑定回环地址。")
    migration = migrate_legacy_sessions(config)
    structured_migration = backfill_structured_knowledge(config)
    if migration.get("staged"):
        try:
            Runner(config.secall_command).run("reindex", "--from-vault", timeout=600)
        except Exception as exc:
            print(f"迁移后的 seCall 索引刷新失败，可稍后在前端手动重建：{exc}")
    server = LocalAPIServer((host, port), config)
    if structured_migration.get("created"):
        server.search.keyword.rebuild()
        semantic_sync = getattr(server.search.semantic, "sync", None)
        if server.search.semantic.available and callable(semantic_sync):
            semantic_sync()
    server.sync_worker.start()
    print(f"seCall OpenCode Local API: http://{host}:{port}")
    print(f"会话生命周期迁移：{migration}")
    print(f"结构化知识兼容迁移：{structured_migration}")
    print("按 Ctrl+C 停止服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.sync_worker.stop()
        server.server_close()
