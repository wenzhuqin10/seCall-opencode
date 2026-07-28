from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class ChatGPTConversation:
    id: str
    title: str
    created: float
    updated: float
    messages: List[Dict[str, Any]]

    def as_export(self, project: str) -> Dict[str, Any]:
        return {
            "info": {
                "id": self.id,
                "title": self.title,
                "directory": project,
                "time": {
                    "created": int(self.created * 1000),
                    "updated": int(self.updated * 1000),
                },
                "agent": "chatgpt",
                "source": "chatgpt",
                "source_format": "chatgpt-conversations-json",
            },
            "messages": self.messages,
        }


def load_chatgpt_export(path: Path) -> List[Dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 ChatGPT 导出文件 {path}: {exc}") from exc
    return conversation_objects(value)


def conversation_objects(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict) and isinstance(value.get("conversations"), list):
        items = value["conversations"]
    elif isinstance(value, dict) and ("mapping" in value or "messages" in value):
        items = [value]
    else:
        raise ValueError(
            "不支持的 ChatGPT 导出结构；需要 conversations.json、"
            "包含 conversations 数组的对象，或单个会话对象。"
        )
    result = [item for item in items if isinstance(item, dict)]
    if not result:
        raise ValueError("ChatGPT 导出中没有可读取的会话。")
    return result


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        text = content.get("text")
        return text.strip() if isinstance(text, str) else ""
    rendered: List[str] = []
    for part in parts:
        if isinstance(part, str):
            rendered.append(part)
        elif isinstance(part, dict):
            if isinstance(part.get("text"), str):
                rendered.append(part["text"])
            else:
                rendered.append(json.dumps(part, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(item for item in rendered if item.strip()).strip()


def _active_branch(conversation: Dict[str, Any]) -> List[Dict[str, Any]]:
    mapping = conversation.get("mapping")
    if not isinstance(mapping, dict):
        messages = conversation.get("messages")
        return [item for item in messages if isinstance(item, dict)] if isinstance(messages, list) else []

    current = conversation.get("current_node")
    if current not in mapping:
        leaves = [
            (node_id, node)
            for node_id, node in mapping.items()
            if isinstance(node, dict) and not node.get("children")
        ]
        if leaves:
            current = max(
                leaves,
                key=lambda item: float(
                    ((item[1].get("message") or {}).get("create_time") or 0)
                    if isinstance(item[1].get("message"), dict)
                    else 0
                ),
            )[0]

    nodes: List[Dict[str, Any]] = []
    visited = set()
    while current in mapping and current not in visited:
        visited.add(current)
        node = mapping[current]
        if not isinstance(node, dict):
            break
        nodes.append(node)
        current = node.get("parent")
    nodes.reverse()
    return [
        node["message"]
        for node in nodes
        if isinstance(node.get("message"), dict)
    ]


def parse_conversation(conversation: Dict[str, Any], index: int = 0) -> ChatGPTConversation:
    raw_id = str(conversation.get("id") or conversation.get("conversation_id") or "")
    if not raw_id:
        digest = hashlib.sha256(
            json.dumps(conversation, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        raw_id = digest
    session_id = raw_id if raw_id.startswith("chatgpt_") else f"chatgpt_{raw_id}"
    title = str(conversation.get("title") or f"ChatGPT 会话 {index + 1}")
    created = float(conversation.get("create_time") or 0)
    updated = float(conversation.get("update_time") or created or 0)

    normalized: List[Dict[str, Any]] = []
    for message in _active_branch(conversation):
        author = message.get("author")
        role = str(author.get("role") or "unknown") if isinstance(author, dict) else str(message.get("role") or "unknown")
        if role not in {"user", "assistant", "system", "tool"}:
            continue
        text = _text_from_content(message.get("content") or message.get("text"))
        if not text:
            continue
        timestamp = float(message.get("create_time") or created or 0)
        normalized.append(
            {
                "info": {
                    "role": role,
                    "time": {"created": int(timestamp * 1000)},
                    "modelID": message.get("metadata", {}).get("model_slug")
                    if isinstance(message.get("metadata"), dict)
                    else None,
                },
                "parts": [{"type": "text", "text": text}],
            }
        )
    if not normalized:
        raise ValueError(f"会话“{title}”没有可导入的文本消息。")
    if not created:
        created = min(
            float(item["info"]["time"]["created"]) / 1000 for item in normalized
        )
    if not updated:
        updated = max(
            float(item["info"]["time"]["created"]) / 1000 for item in normalized
        )
    return ChatGPTConversation(session_id, title, created, updated, normalized)


def parse_export(value: Any, limit: Optional[int] = None) -> List[ChatGPTConversation]:
    objects = conversation_objects(value)
    if limit is not None:
        objects = objects[: max(0, limit)]
    parsed: List[ChatGPTConversation] = []
    errors: List[str] = []
    for index, conversation in enumerate(objects):
        try:
            parsed.append(parse_conversation(conversation, index))
        except ValueError as exc:
            errors.append(str(exc))
    if not parsed:
        raise ValueError("; ".join(errors) or "没有可导入的 ChatGPT 会话。")
    return parsed


def inspect_export(value: Any, limit: int = 20) -> Dict[str, Any]:
    conversations = parse_export(value)
    return {
        "conversation_count": len(conversations),
        "message_count": sum(len(item.messages) for item in conversations),
        "preview": [
            {
                "id": item.id,
                "title": item.title,
                "messages": len(item.messages),
                "created": item.created,
                "updated": item.updated,
            }
            for item in conversations[: max(1, limit)]
        ],
    }
