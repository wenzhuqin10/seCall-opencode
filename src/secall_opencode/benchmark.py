from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence


def load_benchmark(path: Path) -> list[Dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 Benchmark：{exc}") from exc
    cases = value.get("cases") if isinstance(value, dict) else value
    if not isinstance(cases, list):
        raise ValueError("Benchmark 必须是 JSON 数组或包含 cases 数组的对象。")
    result = [dict(item) for item in cases if isinstance(item, Mapping)]
    if not result:
        raise ValueError("Benchmark 中没有测试用例。")
    return result


def run_retrieval_benchmark(
    service: Any,
    cases: Sequence[Mapping[str, Any]],
    *,
    default_mode: str = "hybrid",
    default_limit: int = 5,
) -> Dict[str, Any]:
    details = []
    reciprocal_rank_sum = 0.0
    hit_count = 0
    latency_sum = 0.0
    for index, case in enumerate(cases, 1):
        question = str(case.get("question") or "").strip()
        if not question:
            raise ValueError(f"Benchmark 第 {index} 条缺少 question。")
        expected = {
            str(item)
            for item in case.get("expected_ids", [])
            if str(item).strip()
        }
        if not expected:
            raise ValueError(f"Benchmark 第 {index} 条缺少 expected_ids。")
        started = time.perf_counter()
        response = service.search(
            question,
            scope=str(case.get("scope") or "all"),
            mode=str(case.get("mode") or default_mode),
            limit=max(1, int(case.get("limit") or default_limit)),
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        latency_sum += elapsed_ms
        result_ids = [str(item.get("id") or "") for item in response["results"]]
        rank = next(
            (position for position, item_id in enumerate(result_ids, 1) if item_id in expected),
            0,
        )
        hit = rank > 0
        if hit:
            hit_count += 1
            reciprocal_rank_sum += 1.0 / rank
        details.append(
            {
                "id": str(case.get("id") or f"case-{index:03d}"),
                "question": question,
                "expected_ids": sorted(expected),
                "result_ids": result_ids,
                "hit": hit,
                "rank": rank,
                "reciprocal_rank": round(1.0 / rank, 6) if rank else 0.0,
                "latency_ms": elapsed_ms,
                "effective_mode": response.get("effective_mode"),
                "fallback_reason": response.get("fallback_reason"),
            }
        )
    count = len(details)
    return {
        "cases": count,
        "hit_at_k": round(hit_count / count, 6),
        "mrr": round(reciprocal_rank_sum / count, 6),
        "average_latency_ms": round(latency_sum / count, 3),
        "passed": hit_count,
        "failed": count - hit_count,
        "details": details,
    }
