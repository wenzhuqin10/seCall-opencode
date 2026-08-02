from __future__ import annotations

from secall_opencode.benchmark import run_retrieval_benchmark


class FakeSearch:
    def search(self, question, scope, mode, limit):
        return {
            "effective_mode": mode,
            "fallback_reason": None,
            "results": [{"id": "wrong"}, {"id": "expected"}][:limit],
        }


def test_retrieval_benchmark_reports_hit_mrr_and_latency() -> None:
    result = run_retrieval_benchmark(
        FakeSearch(),
        [
            {
                "id": "harq",
                "question": "HARQ timeout 如何定位？",
                "expected_ids": ["expected"],
            }
        ],
        default_mode="keyword",
        default_limit=5,
    )

    assert result["hit_at_k"] == 1.0
    assert result["mrr"] == 0.5
    assert result["passed"] == 1
    assert result["details"][0]["rank"] == 2
