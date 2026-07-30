from __future__ import annotations

import json
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _ms_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).astimezone()


def _safe_name(value: str, fallback: str = "unknown") -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).strip(" .-")
    value = re.sub(r"\s+", "-", value)
    return value[:80] or fallback


@dataclass(frozen=True)
class ConversionResult:
    session_id: str
    project: str
    date: str
    output_path: Path
    turns: int
    tools: Tuple[str, ...]
    created: bool
    markdown: str

    def as_dict(self, include_markdown: bool = False) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "session_id": self.session_id,
            "project": self.project,
            "date": self.date,
            "output_path": str(self.output_path),
            "turns": self.turns,
            "tools": list(self.tools),
            "created": self.created,
        }
        if include_markdown:
            result["markdown"] = self.markdown
        return result


def validate_export(data: Dict[str, Any]) -> None:
    info = _dict(data.get("info"))
    if not info.get("id"):
        raise ValueError("OpenCode 导出缺少 info.id。")
    if not _dict(info.get("time")).get("created"):
        raise ValueError("OpenCode 导出缺少 info.time.created。")
    if not isinstance(data.get("messages"), list):
        raise ValueError("OpenCode 导出缺少 messages 数组。")


def _tool_parts(parts: Iterable[Any]) -> List[Dict[str, str]]:
    tools: List[Dict[str, str]] = []
    for raw_part in parts:
        part = _dict(raw_part)
        if part.get("type") != "tool":
            continue
        state = _dict(part.get("state"))
        tools.append(
            {
                "name": str(part.get("tool") or "unknown"),
                "call_id": str(part.get("callID") or ""),
                "input": _scalar(state.get("input")),
                "output": _scalar(state.get("output")),
            }
        )
    return tools


def render_markdown(data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    validate_export(data)
    info = _dict(data["info"])
    source = str(info.get("source") or info.get("agent") or "opencode").lower()
    agent = str(info.get("agent") or source)
    session_id = str(info["id"])
    directory = str(info.get("directory") or "")
    project = Path(directory).name if directory else str(info.get("title") or "unknown")
    project = project or "unknown"
    start = _ms_datetime(_dict(info.get("time")).get("created"))
    if start is None:
        raise ValueError("无法解析 Session 创建时间。")
    end = _ms_datetime(_dict(info.get("time")).get("updated"))

    rendered_turns: List[str] = []
    tool_names: List[str] = []
    model: Optional[str] = None
    first_user = ""

    for message in _list(data.get("messages")):
        msg = _dict(message)
        msg_info = _dict(msg.get("info"))
        role = str(msg_info.get("role") or "system")
        parts = _list(msg.get("parts"))
        texts = [
            str(_dict(part).get("text"))
            for part in parts
            if _dict(part).get("type") == "text" and _dict(part).get("text")
        ]
        content = "\n".join(texts).strip()
        tools = _tool_parts(parts)
        if not content and not tools:
            continue

        if role == "assistant" and model is None:
            raw_model = msg_info.get("model") or info.get("model")
            model_info = _dict(raw_model)
            model_id = (
                msg_info.get("modelID")
                or model_info.get("modelID")
                or model_info.get("id")
            )
            provider_id = msg_info.get("providerID") or model_info.get("providerID")
            if model_id and provider_id:
                model = f"{provider_id}/{model_id}"
            elif model_id:
                model = str(model_id)
            elif isinstance(raw_model, str):
                model = raw_model
        if role == "user" and not first_user and content:
            first_user = content

        timestamp = _ms_datetime(_dict(msg_info.get("time")).get("created"))
        time_suffix = f" ({timestamp.strftime('%H:%M')})" if timestamp else ""
        label = {"user": "用户", "assistant": "助手", "system": "系统"}.get(
            role, role
        )
        turn_no = len(rendered_turns) + 1
        block = [f"## Turn {turn_no} — {label}{time_suffix}", ""]
        if content:
            block.extend([content, ""])
        for tool in tools:
            name = tool["name"]
            if name not in tool_names:
                tool_names.append(name)
            block.append(f"> [!tool]- {name}")
            if tool["input"]:
                block.extend(["> ```json"])
                block.extend(f"> {line}" for line in tool["input"].splitlines())
                block.append("> ```")
            if tool["output"]:
                block.append("> **输出**")
                block.extend(f"> {line}" for line in tool["output"].splitlines())
            block.append("")
        rendered_turns.append("\n".join(block).rstrip())

    if not rendered_turns:
        raise ValueError("OpenCode Session 没有可转换的文本或工具调用。")

    title = str(info.get("title") or first_user.splitlines()[0][:120] or project)
    summary = re.sub(r"\s+", " ", first_user).strip()[:240] or title
    tokens_in = int(info.get("tokens_input") or info.get("tokensIn") or 0)
    tokens_out = int(info.get("tokens_output") or info.get("tokensOut") or 0)
    source_format = str(
        info.get("source_format")
        or f"{source}-export-v{info.get('version') or 'unknown'}"
    )
    source_label = {
        "opencode": "OpenCode",
        "chatgpt": "ChatGPT",
        "codex": "Codex",
    }.get(source, source.capitalize())

    frontmatter = [
        "---",
        "type: session",
        f"agent: {_yaml_string(agent)}",
        f"source: {_yaml_string(source)}",
    ]
    if model:
        frontmatter.append(f"model: {_yaml_string(model)}")
    frontmatter.extend(
        [
            f"project: {_yaml_string(project)}",
            f"cwd: {_yaml_string(directory)}",
            f"session_id: {_yaml_string(session_id)}",
            f"date: {start.strftime('%Y-%m-%d')}",
            f'start_time: "{start.isoformat(timespec="seconds")}"',
        ]
    )
    if end:
        frontmatter.append(f'end_time: "{end.isoformat(timespec="seconds")}"')
    frontmatter.extend(
        [
            f"turns: {len(rendered_turns)}",
            f"tokens_in: {tokens_in}",
            f"tokens_out: {tokens_out}",
            f"tools_used: [{', '.join(_yaml_string(name) for name in tool_names)}]",
            f"host: {_yaml_string(socket.gethostname())}",
            f"summary: {_yaml_string(summary)}",
            "status: raw",
            "session_type: interactive",
            f"source_format: {_yaml_string(source_format)}",
            "---",
            "",
            f"# {source_label} 会话：{title}",
            "",
            f"> **项目**：{project} | **时间**：{start.strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
    )
    markdown = (
        "\n".join(frontmatter).rstrip()
        + "\n\n"
        + "\n\n".join(rendered_turns).rstrip()
        + "\n"
    )
    metadata = {
        "session_id": session_id,
        "project": project,
        "date": start.strftime("%Y-%m-%d"),
        "turns": len(rendered_turns),
        "tools": tuple(tool_names),
    }
    return markdown, metadata


def convert_export(
    data: Dict[str, Any],
    vault: Path,
    dry_run: bool = False,
    overwrite: bool = False,
    destination_dir: str = "raw/.sessions",
) -> ConversionResult:
    markdown, meta = render_markdown(data)
    info = _dict(data.get("info"))
    source = _safe_name(str(info.get("source") or info.get("agent") or "opencode"))
    short_id = _safe_name(meta["session_id"])[:16]
    filename = f"{source}_{_safe_name(meta['project'])}_{short_id}.md"
    output_path = vault / destination_dir / meta["date"] / filename
    exists = output_path.exists()
    if exists and not overwrite:
        existing = output_path.read_text(encoding="utf-8")
        if existing == markdown:
            return ConversionResult(
                output_path=output_path,
                created=False,
                markdown=markdown,
                **meta,
            )
        raise FileExistsError(
            f"目标会话已存在且内容不同：{output_path}；使用 --overwrite 覆盖。"
        )
    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
    return ConversionResult(
        output_path=output_path,
        created=not exists,
        markdown=markdown,
        **meta,
    )
