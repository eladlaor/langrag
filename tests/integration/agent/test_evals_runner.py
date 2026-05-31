"""Integration smoke for the agent eval gate runner.

Invokes `scripts/run_agent_evals.py` as a subprocess against the docker
MongoDB and asserts exit code 0 (full pass). This proves the runner
itself is healthy independent of any single eval case.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "run_agent_evals.py"


@pytest.mark.skipif(not SCRIPT.exists(), reason="eval runner missing")
def test_eval_runner_exits_zero():
    env = os.environ.copy()
    env.setdefault("MONGODB_URI", os.environ.get("MONGODB_URI", "mongodb://localhost:27017"))
    env.setdefault("MONGODB_DATABASE", "langrag_test")
    env.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--threshold", "1.0"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, (
        f"runner failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "passed" in result.stdout, result.stdout
