from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


class CommandError(RuntimeError):
    def __init__(self, command: Sequence[str], returncode: int, stderr: str):
        super().__init__(
            f"命令执行失败（exit={returncode}）：{' '.join(command)}\n{stderr.strip()}"
        )
        self.command = list(command)
        self.returncode = returncode
        self.stderr = stderr


@dataclass
class Runner:
    executable: str

    def command(self, *args: str) -> List[str]:
        return [*shlex.split(self.executable, posix=False), *args]

    def run(
        self,
        *args: str,
        cwd: Optional[Path] = None,
        timeout: int = 600,
    ) -> subprocess.CompletedProcess[str]:
        command = self.command(*args)
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            raise CommandError(command, result.returncode, result.stderr)
        return result


class OpenCodeClient:
    def __init__(self, executable: str = "opencode"):
        self.runner = Runner(executable)

    def version(self) -> str:
        return self.runner.run("--version", timeout=30).stdout.strip()

    def models(self) -> List[str]:
        raw = self.runner.run("models", timeout=60).stdout
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def list_sessions(self, limit: int = 20) -> List[Dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        sql = (
            "SELECT id,title,directory,agent,model,tokens_input,tokens_output,"
            "time_created,time_updated,time_archived "
            f"FROM session ORDER BY time_updated DESC LIMIT {limit}"
        )
        raw = self.runner.run("db", sql, "--format", "json", timeout=60).stdout
        value = json.loads(raw or "[]")
        if not isinstance(value, list):
            raise ValueError("OpenCode session 查询没有返回 JSON 数组。")
        return [item for item in value if isinstance(item, dict)]

    def export(self, session_id: str, sanitize: bool = False) -> Dict[str, Any]:
        args = ["export", session_id]
        if sanitize:
            args.append("--sanitize")
        raw = self.runner.run(*args, timeout=180).stdout
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"OpenCode 导出不是有效 JSON：{exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("OpenCode 导出必须是 JSON 对象。")
        return value

    def run_generation(
        self,
        session_file: Path,
        prompt_file: Path,
        workdir: Path,
        model: Optional[str] = None,
        timeout: int = 1800,
    ) -> str:
        args = [
            "run",
            "--format",
            "json",
            "--file",
            str(session_file),
            "--file",
            str(prompt_file),
            "--dir",
            str(workdir),
            "--title",
            f"seCall knowledge: {session_file.stem}",
        ]
        if model:
            args.extend(["--model", model])
        args.append(
            "依据附件中的中文规则分析 Session。只输出最终 Issue Card 与 QA 标记块，"
            "不要修改任何文件。"
        )
        raw = self.runner.run(*args, cwd=workdir, timeout=timeout).stdout
        return extract_generation_text(raw)


def _walk_text(value: Any) -> List[str]:
    texts: List[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"text", "content"} and isinstance(item, str):
                texts.append(item)
            elif isinstance(item, (dict, list)):
                texts.extend(_walk_text(item))
    elif isinstance(value, list):
        for item in value:
            texts.extend(_walk_text(item))
    return texts


def extract_generation_text(raw: str) -> str:
    """Extract the final marked document from OpenCode JSONL output."""
    candidates: List[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            candidates.append(line)
            continue
        candidates.extend(_walk_text(event))

    joined = "\n".join(candidates)
    start = "<!-- SECALL_DOCUMENT_START -->"
    end = "<!-- SECALL_DOCUMENT_END -->"
    if start in joined and end in joined:
        return joined.split(start, 1)[1].split(end, 1)[0].strip()

    markdown_candidates = [
        text.strip()
        for text in candidates
        if text.strip().startswith("---") or "\n# " in text
    ]
    if markdown_candidates:
        return max(markdown_candidates, key=len)
    if joined.strip():
        return joined.strip()
    raise ValueError("未能从 OpenCode 输出中提取最终文档。")
