from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterator, Set, Tuple

from .config import Config
from .knowledge_store import atomic_write_text, parse_frontmatter


SESSION_LOCATIONS = {
    "approved": Path("raw/.sessions"),
    "pending": Path("staging/sessions"),
    "rejected": Path("staging/rejected"),
}


def session_root(config: Config, state: str) -> Path:
    if state not in SESSION_LOCATIONS:
        raise ValueError(f"未知会话存储状态：{state}")
    return config.vault / SESSION_LOCATIONS[state]


def iter_session_files(config: Config) -> Iterator[Tuple[str, Path]]:
    for state, relative in SESSION_LOCATIONS.items():
        root = config.vault / relative
        if root.exists():
            yield from ((state, path) for path in root.rglob("*.md"))


def find_session_file(config: Config, session_id: str) -> Tuple[str, Path] | None:
    for state, path in iter_session_files(config):
        metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        if (metadata.get("session_id") or path.stem) == session_id:
            return state, path
    return None


def move_session_file(config: Config, session_id: str, target_state: str) -> Path:
    found = find_session_file(config, session_id)
    if not found:
        raise FileNotFoundError(f"Vault 中不存在 Session：{session_id}")
    _, source = found
    metadata, _ = parse_frontmatter(source.read_text(encoding="utf-8", errors="replace"))
    date = metadata.get("date") or source.parent.name
    destination = session_root(config, target_state) / date / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.resolve() != source.resolve():
        raise FileExistsError(f"目标位置已存在同名会话：{destination}")
    if destination.resolve() != source.resolve():
        source.replace(destination)
    return destination


def knowledge_source_sessions(config: Config) -> Set[str]:
    result: Set[str] = set()
    root = config.vault / config.knowledge_dir
    if not root.exists():
        return result
    for path in root.glob("*.md"):
        metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        if metadata.get("source_session"):
            result.add(metadata["source_session"])
    return result


def migrate_legacy_sessions(config: Config) -> Dict[str, int]:
    marker = config.vault / "knowledge" / "session-lifecycle-v1.json"
    if marker.exists():
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return {key: int(value.get(key) or 0) for key in ("approved", "staged")}
        except (OSError, json.JSONDecodeError):
            pass
    approved_ids = knowledge_source_sessions(config)
    approved = 0
    staged = 0
    raw_root = session_root(config, "approved")
    for path in list(raw_root.rglob("*.md")) if raw_root.exists() else []:
        metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        session_id = metadata.get("session_id") or path.stem
        if session_id in approved_ids:
            approved += 1
            continue
        date = metadata.get("date") or path.parent.name
        destination = session_root(config, "pending") / date / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            path.replace(destination)
        staged += 1
    result = {"approved": approved, "staged": staged}
    marker.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(marker, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result
