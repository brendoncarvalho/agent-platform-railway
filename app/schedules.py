"""
AgentOS Schedules
==================
"""

from os import getenv

from agno.scheduler import ScheduleManager
from agno.utils.log import log_info, log_warning

from db import get_postgres_db


def register_schedules() -> None:
    """Register schedules (idempotent and fail-soft).

    The deployment check runs daily by default. Eval regression is opt-in because it uses model calls.
    """
    try:
        manager = ScheduleManager(get_postgres_db())
    except Exception as exc:
        log_warning(f"schedules: could not initialize ScheduleManager: {exc}")
        return

    if getenv("ENABLE_DEPLOY_CHECK", "True") == "True":
        try:
            manager.create(
                name="deployment-check",
                cron="0 13 * * *",  # 13:00 UTC daily
                endpoint="/workflows/deployment-check/runs",
                payload={"message": "Scheduled deployment check."},
                description="Daily: verify platform wiring and readiness.",
                if_exists="update",
            )
        except Exception as exc:
            log_warning(f"schedules: could not register 'deployment-check': {exc}")
        else:
            log_info("schedules: registered 'deployment-check'")
    else:
        log_info("schedules: deployment-check disabled (ENABLE_DEPLOY_CHECK=False)")

    if getenv("ENABLE_EVAL_REGRESSION", "False") == "True":
        try:
            manager.create(
                name="eval-regression",
                cron="0 14 * * *",  # 14:00 UTC daily
                endpoint="/workflows/eval-regression/runs",
                payload={"message": "Scheduled eval regression."},
                description="Daily: run the eval regression suite.",
                if_exists="update",
            )
        except Exception as exc:
            log_warning(f"schedules: could not register 'eval-regression': {exc}")
        else:
            log_info("schedules: registered 'eval-regression'")
    else:
        log_info("schedules: eval-regression disabled (ENABLE_EVAL_REGRESSION=True to enable)")
