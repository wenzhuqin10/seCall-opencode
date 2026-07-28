from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class Config:
    vault: Path
    opencode_command: str = "opencode"
    secall_command: str = "secall"
    model: Optional[str] = None
    timezone: str = "Asia/Shanghai"
    knowledge_dir: str = "wiki/issues"
    qa_file: str = "knowledge/qa/candidates.jsonl"


def default_config_path() -> Path:
    explicit = os.environ.get("SECALL_OPENCODE_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    return base / "secall-opencode" / "config.json"


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取配置文件 {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"配置文件必须是 JSON 对象：{path}")
    return value


def load_config(
    config_path: Optional[Path] = None,
    vault_override: Optional[Path] = None,
) -> Config:
    path = config_path or default_config_path()
    raw = _read_json(path)
    vault_value = (
        str(vault_override)
        if vault_override is not None
        else os.environ.get("SECALL_VAULT") or raw.get("vault")
    )
    if not vault_value:
        raise ValueError(
            "尚未配置 seCall Vault。先运行 `secall-opencode init --vault <路径>`，"
            "或设置 SECALL_VAULT。"
        )
    return Config(
        vault=Path(vault_value).expanduser().resolve(),
        opencode_command=os.environ.get("OPENCODE_COMMAND")
        or str(raw.get("opencode_command") or "opencode"),
        secall_command=os.environ.get("SECALL_COMMAND")
        or str(raw.get("secall_command") or "secall"),
        model=os.environ.get("OPENCODE_MODEL") or raw.get("model"),
        timezone=str(raw.get("timezone") or "Asia/Shanghai"),
        knowledge_dir=str(raw.get("knowledge_dir") or "wiki/issues"),
        qa_file=str(raw.get("qa_file") or "knowledge/qa/candidates.jsonl"),
    )


def save_config(config: Config, path: Optional[Path] = None, force: bool = False) -> Path:
    destination = (path or default_config_path()).expanduser()
    if destination.exists() and not force:
        raise FileExistsError(f"配置已存在：{destination}；使用 --force 覆盖。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(config)
    payload["vault"] = str(config.vault)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination
