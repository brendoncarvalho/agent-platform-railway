"""
AgentOS Entrypoint
==================
"""

from contextlib import asynccontextmanager
from os import getenv
from pathlib import Path

from agno.os import AgentOS
from agno.utils.log import log_info
from fastapi import FastAPI

from agents.assistente_pemill import assistente_pemill
from agents.crm_note_autofix import crm_note_autofix
from agents.hr_resume_analyst import hr_resume_analyst
from agents.jira_ticket_responder import jira_ticket_responder
from agents.ti_team import ti_team
from app.media_storage import get_media_storage
from app.registry import registry
from db import get_postgres_db

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
runtime_env = getenv("RUNTIME_ENV", "prd")
# Used by the scheduler and the OAuth server when MCP OAuth is enabled.
agentos_url = getenv("AGENTOS_URL", "http://127.0.0.1:8000")

# ---------------------------------------------------------------------------
# Interfaces
# - Assistente Pemill becomes available on Slack when both env vars are set
# ---------------------------------------------------------------------------
SLACK_BOT_TOKEN = getenv("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = getenv("SLACK_SIGNING_SECRET", "")

interfaces: list = []
if SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET:
    from agno.os.interfaces.slack import Slack

    interfaces.append(
        Slack(
            agent=assistente_pemill,
            streaming=True,
            token=SLACK_BOT_TOKEN,
            signing_secret=SLACK_SIGNING_SECRET,
            resolve_user_identity=True,
            loading_text="Pensando...",
        )
    )


# ---------------------------------------------------------------------------
# Base FastAPI app
# - Custom webhook routes live here before AgentOS mounts its own routes.
# ---------------------------------------------------------------------------
base_app = FastAPI(title="Pemill AgentOS")
if getenv("ROCKETCHAT_WEBHOOK_TOKEN"):
    from app.rocketchat import rocketchat_router

    base_app.include_router(rocketchat_router())


# ---------------------------------------------------------------------------
# MCP OAuth — enabled by setting the MCP_CONNECT_SECRET environment variable.
# Connect your favorite AI apps and coding agents to a secure /mcp using OAuth.
# ---------------------------------------------------------------------------
MCP_CONNECT_SECRET = getenv("MCP_CONNECT_SECRET", "")

mcp_auth = None
if MCP_CONNECT_SECRET:
    from agno.os import AgentOSBuiltinAuth

    mcp_auth = AgentOSBuiltinAuth(
        url=agentos_url,
        secret=MCP_CONNECT_SECRET,
        # `or None`: an empty value (e.g. an unset compose variable) means "generate and persist a key".
        signing_key_material=getenv("AGENTOS_MCP_SIGNING_KEY") or None,
    )


# ---------------------------------------------------------------------------
# Lifespan — app-level startup / teardown.
#
# AgentOS handles the MCP lifecycle (connect on startup, close on shutdown)
# for agent-attached and registry tools. Keep this hook to plug in your own setup.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app):  # type: ignore[no-untyped-def]
    log_info("AgentOS lifespan: startup")
    try:
        yield
    finally:
        log_info("AgentOS lifespan: shutdown")


# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    name="Pemill AgentOS",
    base_app=base_app,
    tracing=True,
    scheduler=True,
    scheduler_base_url=agentos_url,
    authorization=runtime_env != "dev",
    mcp_server=True,
    mcp_auth=mcp_auth,
    lifespan=lifespan,
    db=get_postgres_db(),
    # Uploaded and generated images are offloaded here and served by /sessions/{id}/media/{key}.
    media_storage=get_media_storage(),
    agents=[
        assistente_pemill,
        crm_note_autofix,
        jira_ticket_responder,
        hr_resume_analyst,
    ],
    teams=[ti_team],
    interfaces=interfaces,
    registry=registry,
    config=str(Path(__file__).parent / "config.yaml"),
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="app.main:app", reload=False)
