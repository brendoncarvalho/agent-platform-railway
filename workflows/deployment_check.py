"""
Deployment Check
================

A reference workflow that checks whether the AgentOS is wired correctly.
"""

from dataclasses import dataclass
from os import getenv
from urllib.parse import urlparse

from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow
from sqlalchemy import create_engine, text

from db import db_url, get_postgres_db


@dataclass(frozen=True)
class CheckResult:
    """One deployment readiness check."""

    name: str
    status: str
    detail: str


def _pass(name: str, detail: str) -> CheckResult:
    return CheckResult(name=name, status="PASS", detail=detail)


def _warn(name: str, detail: str) -> CheckResult:
    return CheckResult(name=name, status="WARN", detail=detail)


def _fail(name: str, detail: str) -> CheckResult:
    return CheckResult(name=name, status="FAIL", detail=detail)


def _check_database() -> CheckResult:
    db = get_postgres_db()
    sessions_table = f"{db.db_schema}.{db.session_table_name}"
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            table_exists = conn.execute(
                text("SELECT to_regclass(:table_name)"),
                {"table_name": sessions_table},
            ).scalar()
    except Exception as exc:
        return _fail("Database", f"Could not connect using configured DB_* env vars: {exc}")
    finally:
        engine.dispose()

    if table_exists is None:
        return _fail("Database", f"Connected, but expected table {sessions_table} is missing.")
    return _pass("Database", f"Connected and found {sessions_table}.")


def _check_runtime() -> CheckResult:
    runtime_env = getenv("RUNTIME_ENV", "prd")
    if runtime_env == "prd":
        if getenv("JWT_VERIFICATION_KEY") or getenv("JWT_JWKS_FILE"):
            return _pass("Runtime", "Production mode with JWT verification configured.")
        return _fail("Runtime", "Production mode requires JWT_VERIFICATION_KEY or JWT_JWKS_FILE.")
    if runtime_env == "dev":
        return _warn(
            "Runtime",
            "Development mode; JWT authorization is disabled. Expected locally — "
            "if this is a production deploy, remove RUNTIME_ENV=dev from the synced env vars.",
        )
    return _warn("Runtime", f"Unexpected RUNTIME_ENV={runtime_env!r}; expected 'dev' or 'prd'.")


def _check_agentos_url() -> CheckResult:
    runtime_env = getenv("RUNTIME_ENV", "prd")
    agentos_url = getenv("AGENTOS_URL", "http://127.0.0.1:8000")
    parsed = urlparse(agentos_url)
    if not parsed.scheme or not parsed.netloc:
        return _fail("AgentOS URL", f"AGENTOS_URL is not a valid absolute URL: {agentos_url!r}.")

    localhost_names = {"127.0.0.1", "localhost", "0.0.0.0"}
    if runtime_env == "prd" and parsed.hostname in localhost_names:
        return _fail("AgentOS URL", "Production scheduler cannot reach AgentOS at a localhost URL.")
    return _pass("AgentOS URL", f"Scheduler base URL is {agentos_url}.")


def _check_slack_config() -> CheckResult:
    token = bool(getenv("SLACK_BOT_TOKEN"))
    signing_secret = bool(getenv("SLACK_SIGNING_SECRET"))
    if token and signing_secret:
        return _pass("Slack", "Slack interface credentials are both set.")
    if token or signing_secret:
        return _warn("Slack", "Only one Slack credential is set; Slack interface will stay disabled.")
    return _pass("Slack", "Slack interface is disabled; no partial credentials found.")


def _check_reference_components() -> CheckResult:
    try:
        from agents.agent_builder import agent_builder
        from agents.code_search import code_search
        from agents.web_search import web_search
        from app.registry import registry
        from workflows.eval_regression import eval_regression
    except Exception as exc:
        return _fail("Components", f"Could not import reference components: {exc}")

    agent_ids = sorted([agent_id for agent_id in (web_search.id, code_search.id, agent_builder.id) if agent_id])
    workflow_ids = sorted([workflow_id for workflow_id in (deployment_check.id, eval_regression.id) if workflow_id])
    return _pass(
        "Components",
        "Reference components import cleanly: "
        f"agents={', '.join(agent_ids)}; workflows={', '.join(workflow_ids)}. "
        f"Registry has {len(registry.tools)} tools.",
    )


def _check_schedule_flag() -> CheckResult:
    deploy = getenv("ENABLE_DEPLOY_CHECK", "True") == "True"
    evals = getenv("ENABLE_EVAL_REGRESSION", "False") == "True"
    if deploy and evals:
        return _pass("Schedule", "Deployment-check and eval-regression crons are armed.")
    if deploy:
        return _pass("Schedule", "Deployment-check cron is armed; eval-regression cron is opt-in and disabled.")
    if evals:
        return _pass("Schedule", "Eval-regression cron is armed; deployment-check cron is disabled.")
    return _pass("Schedule", "Deployment-check and eval-regression crons are disabled; run endpoints remain available.")


def _format_report(checks: list[CheckResult]) -> str:
    failed = sum(1 for check in checks if check.status == "FAIL")
    warned = sum(1 for check in checks if check.status == "WARN")
    overall = "FAIL" if failed else "WARN" if warned else "PASS"

    lines = [
        "# Deployment Check",
        "",
        f"Overall: **{overall}** ({failed} failed, {warned} warning)",
        "",
    ]
    lines.extend(f"- **{check.status}** {check.name}: {check.detail}" for check in checks)
    return "\n".join(lines)


def deployment_check_step(_step_input: StepInput) -> StepOutput:
    """Run deterministic deployment readiness checks and return a report."""
    checks = [
        _check_database(),
        _check_runtime(),
        _check_agentos_url(),
        _check_slack_config(),
        _check_reference_components(),
        _check_schedule_flag(),
    ]
    failed = any(check.status == "FAIL" for check in checks)
    return StepOutput(content=_format_report(checks), success=not failed)


deployment_check = Workflow(
    id="deployment-check",
    name="Deployment Check",
    description="Check DB, auth, scheduler URL, Slack config, schedules, and reference component imports.",
    db=get_postgres_db(),
    steps=[Step(name="deployment-check", executor=deployment_check_step)],
)
