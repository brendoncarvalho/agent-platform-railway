"""
Eval Regression
===============

Optional workflow that runs a bounded eval profile and returns a compact report.
It is safe to keep registered because it only runs when called or scheduled.
The schedule is disabled by default in app/schedules.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from os import getenv
from pathlib import Path

from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow

from db import get_postgres_db

REPO_ROOT = Path(__file__).resolve().parents[1]


def _int_env(name: str, default: int) -> int:
    value = getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _format_summary(payload: dict, stdout_tail: str) -> str:
    summary = payload.get("summary", {})
    status = summary.get("status", "FAIL")
    lines = [
        "# Eval Regression",
        "",
        f"Overall: **{status}** ({summary.get('passed', 0)}/{summary.get('total', 0)} passed)",
        "",
    ]
    for case in payload.get("cases", []):
        result = "PASS" if case.get("passed") else "FAIL"
        duration = case.get("duration_seconds", 0)
        detail = f"{result} `{case.get('name')}` ({duration}s)"
        if case.get("error"):
            detail += f" — {case['error']}"
        lines.append(f"- {detail}")
    if stdout_tail:
        lines.extend(["", "```text", stdout_tail, "```"])
    return "\n".join(lines)


def _timeout_output(exc: subprocess.TimeoutExpired) -> str:
    if isinstance(exc.stdout, bytes):
        return exc.stdout.decode(errors="replace")
    return exc.stdout or ""


def eval_regression_step(_step_input: StepInput) -> StepOutput:
    """Run the configured eval profile and return a markdown summary."""
    profile = getenv("EVAL_REGRESSION_PROFILE", "smoke")
    timeout_seconds = _int_env("EVAL_REGRESSION_TIMEOUT_SECONDS", 90)
    suite_timeout_seconds = _int_env("EVAL_REGRESSION_SUITE_TIMEOUT_SECONDS", 300)

    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "eval-regression.json"
        command = [
            sys.executable,
            "-m",
            "evals",
            "--profile",
            profile,
            "--timeout",
            str(timeout_seconds),
            "--json-output",
            str(json_path),
        ]
        try:
            result = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=suite_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return StepOutput(
                content=(
                    "# Eval Regression\n\n"
                    f"Overall: **FAIL** — suite exceeded {suite_timeout_seconds}s.\n\n"
                    f"Command: `{' '.join(command)}`\n\n"
                    f"Partial output:\n\n```text\n{_timeout_output(exc)}\n```"
                ),
                success=False,
            )

        if json_path.exists():
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        else:
            payload = {
                "summary": {"status": "FAIL", "total": 0, "passed": 0, "failed": 1},
                "cases": [{"name": "eval-runner", "passed": False, "error": "json output missing"}],
            }

        stdout_tail = "\n".join(result.stdout.splitlines()[-20:])
        status = payload.get("summary", {}).get("status") == "PASS" and result.returncode == 0
        return StepOutput(content=_format_summary(payload, stdout_tail), success=status)


eval_regression = Workflow(
    id="eval-regression",
    name="Eval Regression",
    description="Run a bounded eval profile and report pass/fail status.",
    db=get_postgres_db(),
    steps=[Step(name="eval-regression", executor=eval_regression_step)],
)
