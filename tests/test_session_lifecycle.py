from pathlib import Path

from secall_opencode.config import Config
from secall_opencode.session_lifecycle import (
    find_session_file,
    migrate_legacy_sessions,
    move_session_file,
)


def _session(path: Path, session_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nsession_id: {session_id}\ndate: 2026-07-30\n---\n# Session\n",
        encoding="utf-8",
    )


def test_migration_keeps_knowledge_sources_and_stages_other_sessions(
    tmp_path: Path,
) -> None:
    config = Config(vault=tmp_path)
    _session(tmp_path / "raw/.sessions/2026-07-30/approved.md", "approved-id")
    _session(tmp_path / "raw/.sessions/2026-07-30/pending.md", "pending-id")
    issue = tmp_path / "wiki/issues/approved.md"
    issue.parent.mkdir(parents=True)
    issue.write_text(
        "---\nsource_session: approved-id\n---\n# Approved\n",
        encoding="utf-8",
    )

    result = migrate_legacy_sessions(config)

    assert result == {"approved": 1, "staged": 1}
    assert find_session_file(config, "approved-id")[0] == "approved"
    assert find_session_file(config, "pending-id")[0] == "pending"


def test_session_moves_between_staging_vault_and_rejected_area(tmp_path: Path) -> None:
    config = Config(vault=tmp_path)
    _session(tmp_path / "staging/sessions/2026-07-30/demo.md", "demo-id")

    approved = move_session_file(config, "demo-id", "approved")
    rejected = move_session_file(config, "demo-id", "rejected")

    assert "raw" in approved.parts
    assert "rejected" in rejected.parts
    assert not approved.exists()
    assert rejected.exists()
