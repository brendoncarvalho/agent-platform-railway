"""
AgentOS Entrypoint
==================
"""

from contextlib import asynccontextmanager
from os import getenv
from pathlib import Path

from agno.os import AgentOS
from agno.tools.mcp import MCPTools
from agno.utils.log import log_info

from agents.agent_builder import agent_builder
from agents.code_search import code_search
from agents.web_search import web_search
from app.registry import registry
from app.schedules import register_schedules
from db import get_postgres_db
from workflows.deployment_check import deployment_check
from workflows.eval_regression import eval_regression

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
runtime_env = getenv("RUNTIME_ENV", "prd")
scheduler_base_url = getenv("AGENTOS_URL", "http://127.0.0.1:8000")

# ---------------------------------------------------------------------------
# Interfaces
# - The Agent Builder agent becomes available on Slack when both env vars are set
# ---------------------------------------------------------------------------
SLACK_BOT_TOKEN = getenv("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = getenv("SLACK_SIGNING_SECRET", "")

interfaces: list = []
if SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET:
    from agno.os.interfaces.slack import Slack

    interfaces.append(
        Slack(
            agent=agent_builder,
            streaming=True,
            token=SLACK_BOT_TOKEN,
            signing_secret=SLACK_SIGNING_SECRET,
            resolve_user_identity=True,
        )
    )


# ---------------------------------------------------------------------------
# Lifespan — extension hook for app-level startup / teardown.
#
# AgentOS handles the MCP lifecycle for agent-attached tools (connect on
# startup, close on shutdown). Keep this hook in place so you can plug in
# your own setup as needed.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app):  # type: ignore[no-untyped-def]
    log_info("AgentOS lifespan: startup")
    # Register schedules on startup. Idempotent and fail-soft.
    register_schedules()
    # agno 2.6.20 only connects MCP tools attached to agents/teams/workflows;
    # MCP toolkits that live only in the Studio registry stay unconnected, so
    # components created through StudioTool would persist them with empty
    # function sets. Connect them here until agno handles registry tools too.
    registry_mcp_tools = [tool for tool in registry.tools or [] if isinstance(tool, MCPTools)]
    for mcp_tool in registry_mcp_tools:
        await mcp_tool.connect()
    try:
        yield
    finally:
        for mcp_tool in registry_mcp_tools:
            await mcp_tool.close()
        log_info("AgentOS lifespan: shutdown")


# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    name="Self-Driving Agent Platform",
    tracing=True,
    scheduler=True,
    scheduler_base_url=scheduler_base_url,
    # Auto-generated per process when unset — fine for one replica. Set it to a
    # shared value when running multiple replicas so scheduler callbacks
    # authenticate no matter which replica they land on.
    internal_service_token=getenv("INTERNAL_SERVICE_TOKEN") or None,
    authorization=runtime_env == "prd",
    lifespan=lifespan,
    db=get_postgres_db(),
    agents=[agent_builder, code_search, web_search],
    workflows=[deployment_check, eval_regression],
    interfaces=interfaces,
    registry=registry,
    config=str(Path(__file__).parent / "config.yaml"),
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="app.main:app", reload=False)
