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
            "依据附件中的中文规则分析 Session。只输出结构化 SessionKnowledge、"
            "最终 Issue Card 与 QA 标记块，不要修改任何文件。"
        )
        raw = self.runner.run(*args, cwd=workdir, timeout=timeout).stdout
        return extract_generation_text(raw)

    def run_planning_analysis(
        self,
        session_file: Path,
        prompt_file: Path,
        workdir: Path,
        model: Optional[str] = None,
        timeout: int = 900,
    ) -> Dict[str, Any]:
        """Ask the model for candidates only; it must not generate a knowledge card."""
        args = [
            "run", "--format", "json", "--file", str(session_file), "--file", str(prompt_file),
            "--dir", str(workdir), "--title", f"seCall planning: {session_file.stem}",
        ]
        if model:
            args.extend(["--model", model])
        args.append("阅读会话并只返回候选知识清单。不要写入任何文件，也不要生成正式知识卡片、QA 或 Wiki。")
        raw = self.runner.run(*args, cwd=workdir, timeout=timeout).stdout
        text = extract_marked_text(raw, "<!-- SECALL_PLANNING_START -->", "<!-- SECALL_PLANNING_END -->")
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"知识策划分析未返回有效 JSON：{exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("知识策划分析必须返回 JSON 对象。")
        return value

    def run_planning_dialogue(
        self,
        session_file: Path,
        context_file: Path,
        prompt_file: Path,
        workdir: Path,
        message: str,
        model: Optional[str] = None,
        timeout: int = 900,
    ) -> Dict[str, Any]:
        args = [
            "run", "--format", "json", "--file", str(session_file), "--file", str(context_file),
            "--file", str(prompt_file), "--dir", str(workdir),
            "--title", f"seCall planning dialogue: {session_file.stem}",
        ]
        if model:
            args.extend(["--model", model])
        args.append(f"用户在知识策划阶段补充：{message}\n只返回策划对话 JSON，不要生成或写入正式知识。")
        raw = self.runner.run(*args, cwd=workdir, timeout=timeout).stdout
        text = extract_marked_text(raw, "<!-- SECALL_PLANNING_START -->", "<!-- SECALL_PLANNING_END -->")
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"知识策划对话未返回有效 JSON：{exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("知识策划对话必须返回 JSON 对象。")
        return value

    def run_candidate_entries(
        self,
        session_file: Path,
        context_file: Path,
        prompt_file: Path,
        workdir: Path,
        model: Optional[str] = None,
        timeout: int = 900,
    ) -> Dict[str, Any]:
        """Ask for selectable entries for one topic, never formal knowledge output."""
        args = [
            "run", "--format", "json", "--file", str(session_file), "--file", str(context_file),
            "--file", str(prompt_file), "--dir", str(workdir),
            "--title", f"seCall entry review: {session_file.stem}",
        ]
        if model:
            args.extend(["--model", model])
        args.append(
            "只为当前知识主题整理可供用户选择的知识条目。不得生成正式知识卡片、QA 或 Wiki，"
            "也不得扩展到用户未选择或未确认的内容。"
        )
        raw = self.runner.run(*args, cwd=workdir, timeout=timeout).stdout
        text = extract_marked_text(raw, "<!-- SECALL_CANDIDATE_ENTRIES_START -->", "<!-- SECALL_CANDIDATE_ENTRIES_END -->")
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"知识条目整理未返回有效 JSON：{exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("知识条目整理必须返回 JSON 对象。")
        return value

    def run_rag_answer(
        self,
        context_file: Path,
        prompt_file: Path,
        workdir: Path,
        question: str,
        model: Optional[str] = None,
        timeout: int = 600,
    ) -> str:
        args = [
            "run",
            "--format",
            "json",
            "--file",
            str(context_file),
            "--file",
            str(prompt_file),
            "--dir",
            str(workdir),
            "--title",
            f"seCall RAG: {question[:48]}",
        ]
        if model:
            args.extend(["--model", model])
        args.append(
            f"用户问题：{question}\n"
            "请严格依据附件中的检索证据回答，并保留 [S1] 形式的来源编号。"
        )
        raw = self.runner.run(*args, cwd=workdir, timeout=timeout).stdout
        return extract_marked_text(
            raw,
            "<!-- SECALL_RAG_START -->",
            "<!-- SECALL_RAG_END -->",
        )


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


def extract_marked_text(raw: str, start: str, end: str) -> str:
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
    if start in joined and end in joined:
        return joined.split(start, 1)[1].split(end, 1)[0].strip()
    if joined.strip():
        return joined.strip()
    raise ValueError("未能从 OpenCode 输出中提取 RAG 回答。")
