from __future__ import annotations

import argparse
import json
import os
import sys
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import __version__
from .config import Config, default_config_path, load_config, save_config
from .converter import convert_export, render_markdown, validate_export
from .knowledge import store_knowledge
from .opencode_client import OpenCodeClient, Runner


def _configure_stdio() -> None:
    """Keep Chinese/Korean tool output usable on Windows GBK consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _emit(value: Any, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps({"ok": True, "result": value}, ensure_ascii=False, indent=2))
        return
    if isinstance(value, str):
        print(value)
    elif isinstance(value, list):
        for item in value:
            print(json.dumps(item, ensure_ascii=False))
    elif isinstance(value, dict):
        for key, item in value.items():
            print(f"{key}: {item}")
    else:
        print(value)


def _error(exc: Exception, json_mode: bool) -> int:
    payload = {
        "ok": False,
        "error": {
            "type": exc.__class__.__name__,
            "message": str(exc),
        },
    }
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"错误：{exc}", file=sys.stderr)
    return 1


def _config(args: argparse.Namespace, require_vault: bool = True) -> Config:
    try:
        return load_config(
            Path(args.config).expanduser() if args.config else None,
            Path(args.vault).expanduser() if getattr(args, "vault", None) else None,
        )
    except ValueError:
        if require_vault:
            raise
        return Config(
            vault=Path(getattr(args, "vault", None) or ".").resolve(),
            opencode_command=os.environ.get("OPENCODE_COMMAND", "opencode"),
            secall_command=os.environ.get("SECALL_COMMAND", "secall"),
            model=os.environ.get("OPENCODE_MODEL"),
        )


def _read_export(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 OpenCode 导出 {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("OpenCode 导出必须是 JSON 对象。")
    validate_export(value)
    return value


def command_init(args: argparse.Namespace) -> Dict[str, Any]:
    vault = Path(args.vault).expanduser().resolve()
    vault.mkdir(parents=True, exist_ok=True)
    config = Config(
        vault=vault,
        opencode_command=args.opencode_command,
        secall_command=args.secall_command,
        model=args.model,
        timezone=args.timezone,
    )
    destination = save_config(
        config,
        Path(args.config).expanduser() if args.config else None,
        force=args.force,
    )
    return {
        "config_path": str(destination),
        "vault": str(vault),
        "next": "secall-opencode --json doctor",
    }


def command_doctor(args: argparse.Namespace) -> Dict[str, Any]:
    cfg = _config(args, require_vault=False)
    checks: Dict[str, Any] = {
        "config_path": str(
            Path(args.config).expanduser() if args.config else default_config_path()
        ),
        "config_exists": (
            Path(args.config).expanduser() if args.config else default_config_path()
        ).exists(),
        "vault": str(cfg.vault),
        "vault_exists": cfg.vault.exists(),
        "raw_sessions_exists": (cfg.vault / "raw" / ".sessions").exists(),
        "network_auth_required": False,
        "model": cfg.model or "OpenCode provider default",
    }
    try:
        client = OpenCodeClient(cfg.opencode_command)
        checks["opencode_version"] = client.version()
        checks["opencode_models"] = client.models()
        if cfg.model:
            checks["configured_model_available"] = cfg.model in checks["opencode_models"]
        checks["opencode_ok"] = True
    except Exception as exc:  # doctor must report rather than crash
        checks["opencode_ok"] = False
        checks["opencode_error"] = str(exc)
    try:
        status = Runner(cfg.secall_command).run("status", timeout=60).stdout
        checks["secall_ok"] = True
        checks["secall_status"] = status.strip()
    except Exception as exc:
        checks["secall_ok"] = False
        checks["secall_error"] = str(exc)
    checks["ready"] = bool(
        checks.get("opencode_ok")
        and checks.get("secall_ok")
        and checks.get("vault_exists")
        and checks.get("configured_model_available", True)
    )
    return checks


def command_sessions_list(args: argparse.Namespace) -> List[Dict[str, Any]]:
    cfg = _config(args)
    return OpenCodeClient(cfg.opencode_command).list_sessions(args.limit)


def command_sessions_export(args: argparse.Namespace) -> Dict[str, Any]:
    cfg = _config(args)
    data = OpenCodeClient(cfg.opencode_command).export(
        args.session_id, sanitize=args.sanitize
    )
    destination = Path(args.out).expanduser().resolve()
    if destination.exists() and not args.overwrite:
        raise FileExistsError(f"导出文件已存在：{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "session_id": args.session_id,
        "path": str(destination),
        "sanitized": args.sanitize,
        "bytes": destination.stat().st_size,
    }


def command_convert(args: argparse.Namespace) -> Dict[str, Any]:
    cfg = _config(args)
    data = _read_export(Path(args.export).expanduser())
    result = convert_export(
        data,
        cfg.vault,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )
    return result.as_dict(include_markdown=args.dry_run)


def _prompt_path() -> Path:
    return Path(resources.files("secall_opencode").joinpath("prompts/issue-card.md"))


def command_generate(args: argparse.Namespace) -> Dict[str, Any]:
    cfg = _config(args)
    session_file = Path(args.session_file).expanduser().resolve()
    if not session_file.exists():
        raise FileNotFoundError(f"Session Markdown 不存在：{session_file}")
    prompt = Path(args.prompt).expanduser().resolve() if args.prompt else _prompt_path()
    if args.dry_run:
        return {
            "dry_run": True,
            "session_file": str(session_file),
            "prompt_file": str(prompt),
            "model": args.model or cfg.model or "OpenCode provider default",
            "writes": [
                str(cfg.vault / cfg.knowledge_dir),
                str(cfg.vault / cfg.qa_file),
            ],
        }
    generated = OpenCodeClient(cfg.opencode_command).run_generation(
        session_file,
        prompt,
        cfg.vault,
        model=args.model or cfg.model,
        timeout=args.timeout,
    )
    result = store_knowledge(
        generated,
        session_file.read_text(encoding="utf-8"),
        cfg.vault,
        cfg.knowledge_dir,
        cfg.qa_file,
        overwrite=args.overwrite,
    )
    return result.as_dict()


def command_index(args: argparse.Namespace) -> Dict[str, Any]:
    cfg = _config(args)
    if args.dry_run:
        return {
            "dry_run": True,
            "command": Runner(cfg.secall_command).command("reindex", "--from-vault"),
            "vault": str(cfg.vault),
        }
    runner = Runner(cfg.secall_command)
    reindex = runner.run("reindex", "--from-vault", timeout=args.timeout)
    status = runner.run("status", timeout=60)
    return {
        "indexed": True,
        "reindex_output": reindex.stdout.strip(),
        "status": status.stdout.strip(),
    }


def _pipeline_one(
    session_id: str,
    cfg: Config,
    args: argparse.Namespace,
    client: OpenCodeClient,
) -> Dict[str, Any]:
    data = client.export(session_id, sanitize=args.sanitize)
    converted = convert_export(
        data,
        cfg.vault,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )
    item: Dict[str, Any] = {"conversion": converted.as_dict(args.dry_run)}
    if not args.skip_generate:
        if args.dry_run:
            item["generation"] = {
                "dry_run": True,
                "session_file": str(converted.output_path),
            }
        else:
            generated = client.run_generation(
                converted.output_path,
                _prompt_path(),
                cfg.vault,
                model=args.model or cfg.model,
                timeout=args.timeout,
            )
            item["generation"] = store_knowledge(
                generated,
                converted.markdown,
                cfg.vault,
                cfg.knowledge_dir,
                cfg.qa_file,
                overwrite=args.overwrite,
            ).as_dict()
    return item


def command_pipeline(args: argparse.Namespace) -> Dict[str, Any]:
    cfg = _config(args)
    client = OpenCodeClient(cfg.opencode_command)
    if args.all:
        sessions = client.list_sessions(args.limit)
        ids = [str(item["id"]) for item in sessions if item.get("id")]
    else:
        ids = list(args.session or [])
    if not ids:
        raise ValueError("没有可处理的 Session；指定 --session，或使用 --all。")
    results = [_pipeline_one(session_id, cfg, args, client) for session_id in ids]

    indexed = False
    if not args.skip_index and not args.dry_run:
        Runner(cfg.secall_command).run("reindex", "--from-vault", timeout=args.timeout)
        indexed = True
    return {
        "processed": len(results),
        "session_ids": ids,
        "indexed": indexed,
        "dry_run": args.dry_run,
        "items": results,
    }


def command_inspect(args: argparse.Namespace) -> Dict[str, Any]:
    data = _read_export(Path(args.export).expanduser())
    markdown, meta = render_markdown(data)
    role_counts: Dict[str, int] = {}
    part_counts: Dict[str, int] = {}
    for message in data.get("messages", []):
        info = message.get("info") if isinstance(message, dict) else {}
        role = str(info.get("role") or "unknown") if isinstance(info, dict) else "unknown"
        role_counts[role] = role_counts.get(role, 0) + 1
        for part in message.get("parts", []) if isinstance(message, dict) else []:
            kind = str(part.get("type") or "unknown") if isinstance(part, dict) else "unknown"
            part_counts[kind] = part_counts.get(kind, 0) + 1
    return {
        **meta,
        "messages": len(data.get("messages", [])),
        "role_counts": role_counts,
        "part_counts": part_counts,
        "rendered_bytes": len(markdown.encode("utf-8")),
    }


def command_raw_db(args: argparse.Namespace) -> Any:
    query = args.query.strip()
    normalized = query.rstrip(";").strip()
    if ";" in normalized:
        raise ValueError("raw db 每次仅允许一条只读查询。")
    lowered = normalized.lower()
    safe_pragma = (
        "pragma table_info(",
        "pragma table_list",
        "pragma database_list",
        "pragma index_list(",
        "pragma index_info(",
    )
    if not lowered.startswith("select ") and not lowered.startswith(safe_pragma):
        raise ValueError("raw db 仅允许 SELECT 或只读结构 PRAGMA 查询。")
    cfg = _config(args, require_vault=False)
    raw = Runner(cfg.opencode_command).run(
        "db", normalized, "--format", "json", timeout=60
    ).stdout
    return json.loads(raw or "[]")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="secall-opencode",
        description="将 OpenCode Session 转换为 seCall 会话、Issue Card 与候选 QA。",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--json", action="store_true", help="输出稳定 JSON envelope。")
    parser.add_argument("--config", help="配置文件路径；默认使用用户配置目录。")
    parser.add_argument("--vault", help="临时覆盖 seCall Vault 路径。")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="保存本地 OpenCode/seCall 适配配置。")
    init.add_argument("--vault", required=True, help="seCall Vault 目录。")
    init.add_argument("--opencode-command", default="opencode")
    init.add_argument("--secall-command", default="secall")
    init.add_argument("--model", help="OpenCode provider/model；省略则使用默认模型。")
    init.add_argument("--timezone", default="Asia/Shanghai")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=command_init)

    doctor = sub.add_parser("doctor", help="检查配置、命令和 Vault 可用性。")
    doctor.set_defaults(func=command_doctor)

    sessions = sub.add_parser("sessions", help="发现和导出 OpenCode Session。")
    sessions_sub = sessions.add_subparsers(dest="sessions_command", required=True)
    sessions_list = sessions_sub.add_parser("list", help="列出最近 Session。")
    sessions_list.add_argument("--limit", type=int, default=20)
    sessions_list.set_defaults(func=command_sessions_list)
    export = sessions_sub.add_parser("export", help="按稳定 Session ID 导出 JSON。")
    export.add_argument("session_id")
    export.add_argument("--out", required=True)
    export.add_argument(
        "--sanitize",
        action="store_true",
        help="脱敏导出；会隐藏正文，不适合后续知识生成。",
    )
    export.add_argument("--overwrite", action="store_true")
    export.set_defaults(func=command_sessions_export)

    convert = sub.add_parser("convert", help="把 OpenCode JSON 转为 seCall Markdown。")
    convert.add_argument("export")
    convert.add_argument("--dry-run", action="store_true")
    convert.add_argument("--overwrite", action="store_true")
    convert.set_defaults(func=command_convert)

    inspect = sub.add_parser("inspect", help="检查导出结构，不写入任何文件。")
    inspect.add_argument("export")
    inspect.set_defaults(func=command_inspect)

    generate = sub.add_parser("generate", help="调用 OpenCode/GLM 生成 Issue Card 和 QA。")
    generate.add_argument("session_file")
    generate.add_argument("--prompt")
    generate.add_argument("--model")
    generate.add_argument("--timeout", type=int, default=1800)
    generate.add_argument("--dry-run", action="store_true")
    generate.add_argument("--overwrite", action="store_true")
    generate.set_defaults(func=command_generate)

    index = sub.add_parser("index", help="调用 seCall 从 Vault 重建索引。")
    index.add_argument("--timeout", type=int, default=600)
    index.add_argument("--dry-run", action="store_true")
    index.set_defaults(func=command_index)

    pipeline = sub.add_parser("pipeline", help="串联导出、转换、生成和索引。")
    source = pipeline.add_mutually_exclusive_group(required=True)
    source.add_argument("--session", action="append", help="OpenCode Session ID，可重复。")
    source.add_argument("--all", action="store_true", help="处理最近 Session。")
    pipeline.add_argument("--limit", type=int, default=20)
    pipeline.add_argument("--model")
    pipeline.add_argument("--timeout", type=int, default=1800)
    pipeline.add_argument(
        "--sanitize",
        action="store_true",
        help="脱敏导出；会隐藏正文，仅适合验证转换链路。",
    )
    pipeline.add_argument("--skip-generate", action="store_true")
    pipeline.add_argument("--skip-index", action="store_true")
    pipeline.add_argument("--dry-run", action="store_true")
    pipeline.add_argument("--overwrite", action="store_true")
    pipeline.set_defaults(func=command_pipeline)

    raw = sub.add_parser("raw", help="只读修复入口。")
    raw_sub = raw.add_subparsers(dest="raw_command", required=True)
    raw_db = raw_sub.add_parser("db", help="执行 OpenCode SELECT/PRAGMA 查询。")
    raw_db.add_argument("--query", required=True)
    raw_db.set_defaults(func=command_raw_db)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except Exception as exc:
        return _error(exc, args.json)
    _emit(result, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
