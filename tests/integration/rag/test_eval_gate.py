"""
Integration test that exercises the RAG eval gate end-to-end.

The test is gated on RAG_EVAL_GATE_ENABLED=true so local pytest runs don't
spend OpenAI / MongoDB resources by default. CI flips the flag and a successful
run requires every aggregated metric to meet its threshold.
"""

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RAG_EVAL_GATE_ENABLED", "false").lower() != "true",
    reason="Set RAG_EVAL_GATE_ENABLED=true to run the live RAG eval gate (CI-only by default)",
)
async def test_rag_eval_gate_meets_thresholds(tmp_path):
    from rag.evaluation.gate import run_gate

    datasets = [
        ROOT / "tests" / "golden_datasets" / "newsletters_v2.json",
        ROOT / "tests" / "golden_datasets" / "podcasts_v1.json",
    ]
    output_path = tmp_path / "rag_eval_report.json"

    passed, report = await run_gate(datasets, output_path=output_path)

    assert output_path.exists()
    payload = json.loads(output_path.read_text())
    assert payload["case_count"] == report["case_count"]

    failures = "\n".join(report["failures"])
    assert passed, f"RAG eval gate failed: \n{failures}\n\nFull report at {output_path}"
