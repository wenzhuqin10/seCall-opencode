from pathlib import Path

from secall_opencode.config import Config
from secall_opencode.rag import answer_with_rag


class FakeSearch:
    def search(self, question, scope, mode, limit):
        return {
            "requested_mode": mode,
            "effective_mode": "hybrid",
            "semantic_available": True,
            "fallback_reason": None,
            "results": [
                {
                    "id": "knowledge-1",
                    "scope": "knowledge",
                    "title": "Index guide",
                    "snippet": "Rebuild the local index after importing a session.",
                    "project": "demo",
                    "source_session": "session-1",
                    "score": 0.9,
                    "match_type": "hybrid",
                    "review_status": "approved",
                }
            ],
        }


def test_rag_answer_returns_grounded_sources(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    def fake_answer(self, context_file, prompt_file, workdir, question, **kwargs):
        captured["context"] = context_file.read_text(encoding="utf-8")
        return "Rebuild the index. [S1]"

    monkeypatch.setattr(
        "secall_opencode.rag.OpenCodeClient.run_rag_answer",
        fake_answer,
    )
    result = answer_with_rag(
        Config(vault=tmp_path),
        FakeSearch(),
        "How do I refresh imported knowledge?",
    )

    assert result["grounded"] is True
    assert result["sources"][0]["citation"] == "S1"
    assert "[S1] Index guide" in captured["context"]
    assert result["answer"].endswith("[S1]")


def test_rag_does_not_call_model_without_evidence(tmp_path: Path) -> None:
    class EmptySearch:
        def search(self, question, scope, mode, limit):
            return {
                "requested_mode": mode,
                "effective_mode": mode,
                "semantic_available": True,
                "fallback_reason": None,
                "results": [],
            }

    result = answer_with_rag(
        Config(vault=tmp_path),
        EmptySearch(),
        "Question with no evidence",
    )

    assert result["grounded"] is False
    assert result["sources"] == []
