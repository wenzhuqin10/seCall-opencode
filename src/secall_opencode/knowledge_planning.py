"""Draft-first, item-by-item knowledge planning."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .config import Config
from .knowledge import split_generated_output, store_knowledge
from .knowledge_store import atomic_write_text, parse_frontmatter

PLAN_VERSION = 2


def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _hash(value: str) -> str: return hashlib.sha256(value.encode("utf-8")).hexdigest()
def _root(config: Config) -> Path: return config.vault / "knowledge" / "planning"
def _path(config: Config, plan_id: str) -> Path: return _root(config) / f"{plan_id}.json"
def _draft_root(config: Config, plan_id: str) -> Path: return _root(config) / "drafts" / plan_id


def _write(config: Config, plan: Mapping[str, Any]) -> Dict[str, Any]:
    value = dict(plan)
    value["updated_at"] = _now()
    value["version"] = int(value.get("version") or 0) + 1
    atomic_write_text(_path(config, str(value["plan_id"])), json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return value


def _migrate(plan: Mapping[str, Any]) -> Dict[str, Any]:
    value = dict(plan)
    if int(value.get("schema_version") or 1) >= PLAN_VERSION:
        return value
    selected = {str(item) for item in value.get("selected_candidate_ids") or []}
    candidates = []
    for source in value.get("candidates") or []:
        if not isinstance(source, Mapping): continue
        item = dict(source)
        item.update({
            "selection_status": "pending" if str(item.get("id")) in selected else "unselected",
            "entry_revisions": [], "selected_entry_ids": [], "skip_reason": "", "supplements": [],
        })
        candidates.append(item)
    old_status = str(value.get("status") or "candidate_selection")
    value.update({"schema_version": PLAN_VERSION, "candidates": candidates,
                  "confirmation_order": [str(item.get("id")) for item in candidates if str(item.get("id")) in selected],
                  "active_candidate_id": "",
                  "status": "candidate_selection" if old_status in {"discussing", "scope_confirmed", "reviewing"} else old_status})
    if old_status in {"scope_confirmed", "reviewing"}: value["draft"] = {"invalidated_by": "schema_v2_item_confirmation_required"}
    return value


def read_plan(config: Config, plan_id: str) -> Dict[str, Any]:
    path = _path(config, plan_id)
    if not path.exists(): raise FileNotFoundError(f"知识策划不存在：{plan_id}")
    try: raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc: raise ValueError("知识策划文件损坏。") from exc
    if not isinstance(raw, dict): raise ValueError("知识策划文件无效。")
    plan = _migrate(raw)
    return _write(config, plan) if plan != raw else plan


def list_plans(config: Config, status: str = "all") -> List[Dict[str, Any]]:
    if not _root(config).exists(): return []
    result = []
    for path in _root(config).glob("plan-*.json"):
        try: plan = read_plan(config, path.stem)
        except (ValueError, FileNotFoundError): continue
        if status == "all" or plan.get("status") == status:
            result.append({key: plan.get(key) for key in ("plan_id", "session_id", "project", "status", "created_at", "updated_at", "version", "index_status") } | {"candidate_count": len(plan.get("candidates") or []), "selected_count": len(plan.get("selected_candidate_ids") or [])})
    return sorted(result, key=lambda item: str(item.get("updated_at") or ""), reverse=True)


def _events(events: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [{"event_id": str(item.get("event_id") or ""), "sequence": item.get("sequence"), "actor": item.get("actor"), "type": item.get("type"), "content": str(item.get("content") or "")[:1200]} for item in events]


def _candidate(item: Mapping[str, Any], session_id: str, allowed: set[str], index: int) -> Dict[str, Any]:
    evidence = item.get("evidence_event_ids") or []
    if not isinstance(evidence, list): evidence = [evidence]
    return {"id": str(item.get("id") or f"candidate-{index + 1}"), "type": str(item.get("type") or "issue"), "title": str(item.get("title") or f"候选主题 {index + 1}"), "value": str(item.get("value") or item.get("summary") or ""), "confidence": str(item.get("confidence") or "low"), "evidence_event_ids": [str(value) for value in evidence if str(value) in allowed], "recommendation": str(item.get("recommendation") or "discuss"), "duplicate_hint": str(item.get("duplicate_hint") or ""), "conflict_hint": str(item.get("conflict_hint") or ""), "source_session": session_id, "selection_status": "unselected", "entry_revisions": [], "selected_entry_ids": [], "skip_reason": "", "supplements": []}


def _source_relative_path(config: Config, source_path: Path | None) -> str:
    """Return a Vault-relative path only when the source lives in this Vault."""
    if source_path is None:
        return ""
    try:
        return source_path.resolve().relative_to(config.vault.resolve()).as_posix()
    except (OSError, ValueError):
        return ""


def create_plan(config: Config, *, session_id: str, project: str, source_markdown: str, events: Sequence[Mapping[str, Any]], analysis: Mapping[str, Any] | None = None, source_path: Path | None = None) -> Dict[str, Any]:
    analysis = analysis or {}
    allowed = {str(item.get("event_id")) for item in events if item.get("event_id")}
    raw_candidates = analysis.get("candidates") if isinstance(analysis.get("candidates"), list) else []
    candidates = [_candidate(item, session_id, allowed, index) for index, item in enumerate(raw_candidates) if isinstance(item, Mapping)]
    if not candidates and allowed:
        candidates = [_candidate({"title": "待确认的会话经验", "value": "会话包含可追溯事件，请确认是否需要沉淀。", "evidence_event_ids": list(allowed)[:3]}, session_id, allowed, 0)]
    now = _now()
    return _write(config, {"schema_version": PLAN_VERSION, "plan_id": f"plan-{uuid.uuid4().hex[:12]}", "session_id": session_id, "project": project or "unknown", "source_path": _source_relative_path(config, source_path), "status": "candidate_selection", "created_at": now, "updated_at": now, "version": 0, "session_hash": _hash(source_markdown), "events": _events(events), "candidates": candidates, "selected_candidate_ids": [], "confirmation_order": [], "active_candidate_id": "", "messages": [{"id": "message-1", "role": "assistant", "at": now, "content": str(analysis.get("assistant_message") or "请选择需要逐项确认的知识主题。")}], "user_facts": [], "draft": {}, "index_status": "not_requested"})


def _find(plan: Mapping[str, Any], candidate_id: str) -> Dict[str, Any]:
    for candidate in plan.get("candidates") or []:
        if str(candidate.get("id")) == candidate_id: return candidate
    raise FileNotFoundError(f"候选知识主题不存在：{candidate_id}")


def update_scope(config: Config, plan_id: str, selected: Sequence[str]) -> Dict[str, Any]:
    plan = read_plan(config, plan_id)
    if plan.get("status") != "candidate_selection": raise ValueError("当前不能修改知识主题选择。")
    requested = [str(item) for item in selected]
    valid = {str(item.get("id")) for item in plan.get("candidates") or []}
    if set(requested) - valid: raise ValueError("包含不存在的知识主题。")
    plan["selected_candidate_ids"] = requested
    for candidate in plan.get("candidates") or []:
        candidate["selection_status"] = "pending" if str(candidate.get("id")) in requested else "unselected"
    return _write(config, plan)


def start_review(config: Config, plan_id: str) -> Dict[str, Any]:
    plan = read_plan(config, plan_id)
    if plan.get("status") != "candidate_selection": raise ValueError("当前不在主题选择阶段。")
    if not plan.get("selected_candidate_ids"): raise ValueError("请至少选择一个知识主题。")
    plan["confirmation_order"] = list(plan["selected_candidate_ids"])
    plan["active_candidate_id"] = plan["confirmation_order"][0]
    plan["status"] = "item_reviewing"
    return _write(config, plan)


def read_candidate(config: Config, plan_id: str, candidate_id: str) -> Dict[str, Any]:
    plan = read_plan(config, plan_id); candidate = _find(plan, candidate_id); order = list(plan.get("confirmation_order") or [])
    revisions = candidate.get("entry_revisions") or []
    return {"plan_id": plan_id, "status": plan.get("status"), "active_candidate_id": plan.get("active_candidate_id"), "progress": {"current": order.index(candidate_id) + 1 if candidate_id in order else 0, "total": len(order)}, "candidate": candidate, "current_revision": revisions[-1] if revisions else None}


def _entries(raw: Any, candidate: Mapping[str, Any], allowed: set[str]) -> List[Dict[str, Any]]:
    if not isinstance(raw, list): return []
    result = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping): continue
        evidence = item.get("evidence_event_ids") or []
        if not isinstance(evidence, list): evidence = [evidence]
        source = str(item.get("source") or "session_evidence")
        result.append({"id": str(item.get("id") or f"entry-{index + 1}"), "type": str(item.get("type") or "note"), "content": str(item.get("content") or ""), "source": source if source in {"session_evidence", "user_provided", "mixed"} else "session_evidence", "evidence_event_ids": [str(value) for value in evidence if str(value) in allowed], "confidence": str(item.get("confidence") or candidate.get("confidence") or "low"), "recommended": bool(item.get("recommended", False)), "duplicate_hint": str(item.get("duplicate_hint") or ""), "conflict_hint": str(item.get("conflict_hint") or "")})
    return result


def save_candidate_revision(config: Config, plan_id: str, candidate_id: str, analysis: Mapping[str, Any], supplement: str = "") -> Dict[str, Any]:
    plan = read_plan(config, plan_id)
    if plan.get("status") != "item_reviewing" or plan.get("active_candidate_id") != candidate_id: raise ValueError("请先完成当前知识主题。")
    candidate = _find(plan, candidate_id)
    if supplement.strip():
        record = {"id": f"supplement-{uuid.uuid4().hex[:8]}", "source": "user_provided", "content": supplement.strip(), "at": _now()}
        candidate.setdefault("supplements", []).append(record); plan.setdefault("user_facts", []).append({**record, "candidate_id": candidate_id})
    revisions = candidate.setdefault("entry_revisions", [])
    revisions.append({"revision": len(revisions) + 1, "created_at": _now(), "assistant_message": str(analysis.get("assistant_message") or "请选择要沉淀的知识条目。"), "entries": _entries(analysis.get("entries"), candidate, {str(item.get("event_id")) for item in plan.get("events") or []}), "supplement": supplement.strip()})
    candidate["selected_entry_ids"] = []; candidate["selection_status"] = "options_ready"
    return _write(config, plan)


def _next(plan: Mapping[str, Any], current: str) -> str:
    order = list(plan.get("confirmation_order") or []); start = order.index(current) + 1 if current in order else 0
    for candidate_id in order[start:] + order[:start]:
        if _find(plan, candidate_id).get("selection_status") in {"pending", "options_ready"}: return candidate_id
    return ""


def confirm_candidate(config: Config, plan_id: str, candidate_id: str, selected: Sequence[str]) -> Dict[str, Any]:
    plan = read_plan(config, plan_id)
    if plan.get("status") != "item_reviewing" or plan.get("active_candidate_id") != candidate_id: raise ValueError("只能确认当前知识主题。")
    candidate = _find(plan, candidate_id); revisions = candidate.get("entry_revisions") or []
    if not revisions: raise ValueError("请先让模型列出知识条目。")
    picked = [str(item) for item in selected]; valid = {str(item.get("id")) for item in revisions[-1].get("entries") or []}
    if not picked: raise ValueError("请至少选择一条知识条目，或跳过此主题。")
    if set(picked) - valid: raise ValueError("选择了不存在的知识条目。")
    candidate["selected_entry_ids"] = picked; candidate["selection_status"] = "confirmed"; plan["active_candidate_id"] = _next(plan, candidate_id)
    return _write(config, plan)


def skip_candidate(config: Config, plan_id: str, candidate_id: str, reason: str) -> Dict[str, Any]:
    plan = read_plan(config, plan_id)
    if plan.get("status") != "item_reviewing" or plan.get("active_candidate_id") != candidate_id: raise ValueError("只能跳过当前知识主题。")
    if not reason.strip(): raise ValueError("请说明跳过此主题的原因。")
    candidate = _find(plan, candidate_id); candidate.update({"selection_status": "skipped", "skip_reason": reason.strip(), "selected_entry_ids": []}); plan["active_candidate_id"] = _next(plan, candidate_id)
    return _write(config, plan)


def reopen_candidate(config: Config, plan_id: str, candidate_id: str) -> Dict[str, Any]:
    plan = read_plan(config, plan_id)
    if plan.get("status") not in {"item_reviewing", "scope_confirmed"}: raise ValueError("生成草稿后不能返回修改。")
    candidate = _find(plan, candidate_id)
    if candidate_id not in set(plan.get("confirmation_order") or []): raise ValueError("该主题不在确认队列中。")
    candidate.update({"selection_status": "options_ready" if candidate.get("entry_revisions") else "pending", "selected_entry_ids": [], "skip_reason": ""}); plan.update({"status": "item_reviewing", "active_candidate_id": candidate_id, "draft": {"invalidated_by": f"candidate_reopened:{candidate_id}"}})
    return _write(config, plan)


def confirm_scope(config: Config, plan_id: str) -> Dict[str, Any]:
    plan = read_plan(config, plan_id)
    if plan.get("status") != "item_reviewing": raise ValueError("请先完成逐项确认。")
    order = list(plan.get("confirmation_order") or [])
    if any(_find(plan, item).get("selection_status") not in {"confirmed", "skipped"} for item in order): raise ValueError("仍有知识主题尚未确认。")
    if not any(_find(plan, item).get("selection_status") == "confirmed" for item in order): raise ValueError("没有确认任何可沉淀的知识条目。")
    plan.update({"status": "scope_confirmed", "active_candidate_id": ""})
    return _write(config, plan)


# Backwards-compatible free-text route; callers should use candidate revisions.
def append_dialogue(config: Config, plan_id: str, message: str, *, assistant_reply: str = "", user_facts: Sequence[str] | None = None) -> Dict[str, Any]:
    plan = read_plan(config, plan_id)
    plan.setdefault("messages", []).append({"id": f"message-{uuid.uuid4().hex[:8]}", "role": "user", "at": _now(), "content": message})
    if assistant_reply: plan["messages"].append({"id": f"message-{uuid.uuid4().hex[:8]}", "role": "assistant", "at": _now(), "content": assistant_reply})
    return _write(config, plan)


def skip_plan(config: Config, plan_id: str, reason: str) -> Dict[str, Any]:
    plan = read_plan(config, plan_id)
    if not reason.strip(): raise ValueError("请说明跳过沉淀的原因。")
    plan.update({"status": "skipped", "skip_reason": reason.strip()}); return _write(config, plan)


def reopen_plan(config: Config, plan_id: str) -> Dict[str, Any]:
    plan = read_plan(config, plan_id); plan.update({"status": "candidate_selection", "skip_reason": ""}); return _write(config, plan)


def _confirmed_context(plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    result = []
    for candidate in plan.get("candidates") or []:
        if candidate.get("selection_status") != "confirmed": continue
        revisions = candidate.get("entry_revisions") or []
        if not revisions: continue
        selected = set(candidate.get("selected_entry_ids") or [])
        result.append({"candidate_id": candidate.get("id"), "title": candidate.get("title"), "type": candidate.get("type"), "entries": [item for item in revisions[-1].get("entries") or [] if item.get("id") in selected]})
    return result


def confirmed_context(plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Return only entries explicitly selected by the user for draft generation."""
    return _confirmed_context(plan)


def save_draft(config: Config, plan_id: str, generated: str) -> Dict[str, Any]:
    plan = read_plan(config, plan_id)
    if plan.get("status") not in {"scope_confirmed", "generating", "reviewing"}: raise ValueError("请先完成逐项确认。")
    document, qa, structured = split_generated_output(generated); root = _draft_root(config, plan_id); atomic_write_text(root / "generated.md", generated.strip() + "\n")
    draft = {"document": document, "qa": qa, "structured": structured or {}, "confirmed_context": _confirmed_context(plan), "wiki_preview": _wiki_preview(plan), "generated_at": _now(), "content_hash": _hash(generated)}
    atomic_write_text(root / "draft.json", json.dumps(draft, ensure_ascii=False, indent=2) + "\n")
    plan.update({"draft": {"path": str(root / "draft.json"), "content_hash": draft["content_hash"], "qa_count": len(qa), "wiki_change_count": len(draft["wiki_preview"])}, "status": "reviewing"})
    return _write(config, plan)


def _wiki_preview(plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [{"id": f"wiki-{index + 1}", "category": "issues" if item.get("type") == "issue" else "topics", "title": item.get("title"), "action": "create_or_update", "reason": f"已确认 {len(item.get('entries') or [])} 条知识条目", "diff": f"+ {item.get('title')}\n+ 来源会话：{plan.get('session_id')}"} for index, item in enumerate(_confirmed_context(plan))]


def read_draft(config: Config, plan_id: str) -> Dict[str, Any]:
    plan = read_plan(config, plan_id); path = _draft_root(config, plan_id) / "draft.json"
    if not path.exists(): raise FileNotFoundError("该知识策划尚未生成草稿。")
    value = json.loads(path.read_text(encoding="utf-8")); return {"plan": plan, "draft": value}


def update_draft(config: Config, plan_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    data = read_draft(config, plan_id); plan, draft = data["plan"], data["draft"]
    if plan.get("status") != "reviewing": raise ValueError("只有待最终审核的草稿可以编辑。")
    for key in ("document", "qa", "wiki_preview"):
        if key in payload: draft[key] = payload[key]
    draft["content_hash"] = _hash(json.dumps(draft, ensure_ascii=False, sort_keys=True)); atomic_write_text(_draft_root(config, plan_id) / "draft.json", json.dumps(draft, ensure_ascii=False, indent=2) + "\n")
    plan["draft"] = {**dict(plan.get("draft") or {}), "content_hash": draft["content_hash"]}; return _write(config, plan)


def _append_selected_qa(config: Config, plan: Mapping[str, Any], qa: Sequence[Mapping[str, Any]], knowledge_id: str) -> int:
    path = config.vault / config.qa_file; existing = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try: item = json.loads(line)
            except json.JSONDecodeError: continue
            if isinstance(item, dict): existing.append(item)
    known = {str(item.get("id")) for item in existing}; added = 0
    for item in qa:
        record = dict(item); record.setdefault("id", f"qa-{uuid.uuid4().hex[:12]}")
        if str(record["id"]) in known: continue
        record.update({
            "source_session": plan["session_id"],
            "project": plan["project"],
            "knowledge_id": knowledge_id,
            "review_status": "pending",
            "review_origin": "knowledge_planning",
            "submitted_by_plan": plan["plan_id"],
            "submitted_at": _now(),
        }); existing.append(record); known.add(str(record["id"])); added += 1
    atomic_write_text(path, "\n".join(json.dumps(item, ensure_ascii=False) for item in existing) + ("\n" if existing else "")); return added


def migrate_legacy_planning_qa(config: Config) -> Dict[str, Any]:
    """Move legacy planner-approved QA into the dedicated review queue once.

    Older planning releases marked generated QA as ``approved`` immediately.
    Only QA tied to a published planning record without the v2 queue marker and
    without human-review audit fields are migrated, so manually reviewed QA are
    left unchanged.
    """
    qa_path = config.vault / config.qa_file
    if not qa_path.exists() or not _root(config).exists():
        return {"plans": 0, "qa_migrated": 0, "backup": ""}
    original_qa = qa_path.read_text(encoding="utf-8", errors="replace")
    qa_items: List[Dict[str, Any]] = []
    for line in original_qa.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            qa_items.append(item)
    migrated = 0
    migrated_plans = 0
    for plan_path in sorted(_root(config).glob("plan-*.json")):
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(plan, dict) or plan.get("status") != "published":
            continue
        published = dict(plan.get("published") or {})
        if "qa" not in set(str(value) for value in published.get("selected") or []):
            continue
        if int(published.get("qa_review_queue_version") or 1) >= 2:
            continue
        knowledge_id = str(published.get("knowledge_id") or "")
        session_id = str(plan.get("session_id") or "")
        plan_migrated = 0
        for item in qa_items:
            if (
                str(item.get("knowledge_id") or "") == knowledge_id
                and str(item.get("source_session") or "") == session_id
                and item.get("review_status") == "approved"
                and not item.get("reviewed_at")
                and not item.get("reviewed_by")
            ):
                item.update({
                    "review_status": "pending",
                    "review_origin": "knowledge_planning",
                    "submitted_by_plan": plan.get("plan_id"),
                    "submitted_at": published.get("at") or _now(),
                    "migration_reason": "legacy_planning_bypassed_qa_review",
                })
                plan_migrated += 1
        published.update({
            "qa_review_queue_version": 2,
            "qa_review_queue_migrated_at": _now(),
            "qa_review_queue_migrated_count": plan_migrated,
        })
        plan["published"] = published
        _write(config, plan)
        migrated += plan_migrated
        migrated_plans += 1
    backup_path = ""
    if migrated:
        backup = config.vault / ".tmp" / "migrations" / (
            f"qa-before-review-queue-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
        )
        atomic_write_text(backup, original_qa)
        backup_path = backup.relative_to(config.vault).as_posix()
        atomic_write_text(
            qa_path,
            "\n".join(json.dumps(item, ensure_ascii=False) for item in qa_items) + "\n",
        )
    return {"plans": migrated_plans, "qa_migrated": migrated, "backup": backup_path}


def _resolve_source_session(config: Config, plan: Mapping[str, Any]) -> Path | None:
    """Resolve the source by stored path, then repair legacy plans by metadata.

    Imported session file names are human-readable rather than their UUID, so
    publishing must match the immutable ``session_id`` in front matter instead
    of assuming that the Markdown file is named ``<session_id>.md``.
    """
    session_id = str(plan.get("session_id") or "")
    if not session_id:
        return None
    vault_root = config.vault.resolve()
    stored_path = str(plan.get("source_path") or "")
    if stored_path:
        try:
            candidate = (config.vault / stored_path).resolve()
            candidate.relative_to(vault_root)
            if candidate.is_file():
                metadata, _ = parse_frontmatter(candidate.read_text(encoding="utf-8", errors="replace"))
                if str(metadata.get("session_id") or "") == session_id:
                    return candidate
        except (OSError, ValueError):
            pass
    for candidate in config.vault.rglob("*.md"):
        try:
            metadata, _ = parse_frontmatter(candidate.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if str(metadata.get("session_id") or "") == session_id:
            return candidate.resolve()
    return None


def publish_plan(config: Config, plan_id: str, selected: Sequence[str], *, reindex: bool = True) -> Dict[str, Any]:
    data = read_draft(config, plan_id); plan, draft = data["plan"], data["draft"]
    if plan.get("status") != "reviewing": raise ValueError("只有待最终审核的草稿可以发布。")
    requested = set(str(item) for item in selected)
    if not requested or requested - {"knowledge", "qa", "wiki"}: raise ValueError("发布项无效。")
    if ("qa" in requested or "wiki" in requested) and "knowledge" not in requested: raise ValueError("QA 和 Wiki 必须依赖本次同时发布的知识卡片。")
    source_file = _resolve_source_session(config, plan)
    if source_file is None: raise FileNotFoundError(f"来源会话 {plan.get('session_id')} 在 Vault 中找不到，无法发布草稿。")
    generated = _draft_root(config, plan_id) / "generated.md"
    if not generated.exists(): raise FileNotFoundError("知识草稿原文丢失，无法发布。")
    result = store_knowledge(generated.read_text(encoding="utf-8"), source_file.read_text(encoding="utf-8"), config.vault, config.knowledge_dir, config.qa_file, include_qa=False)
    added = _append_selected_qa(config, plan, draft.get("qa") or [], result.issue_path.stem) if "qa" in requested else 0
    plan.update({"source_path": _source_relative_path(config, source_file), "status": "published", "published": {"selected": sorted(requested), "knowledge_id": result.issue_path.stem, "qa_added": added, "at": _now(), "qa_review_queue_version": 2}, "index_status": "pending" if reindex else "not_requested"})
    return _write(config, plan) | {"published": plan["published"]}


def mark_index_result(config: Config, plan_id: str, success: bool, detail: str = "") -> Dict[str, Any]:
    plan = read_plan(config, plan_id); plan.update({"index_status": "ready" if success else "pending", "index_detail": detail}); return _write(config, plan)
