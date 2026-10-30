"""
AgentOS Registry
================

The tools, functions, models, databases, and agents available to AgentOS Studio.
"""

from os import getenv

from agno.registry import Registry
from agno.tools.mcp import MCPTools
from agno.tools.parallel import ParallelTools
from agno.tools.reasoning import ReasoningTools

from agents.crm_note_autofix import crm_note_autofix
from agents.general_chat import general_chat
from agents.jira_ticket_responder import jira_ticket_responder
from agents.platform_manager import platform_manager
from app.jira_tools import get_jira_tools
from app.settings import STUDIO_MODEL_IDS, default_model
from app.web_tools import SharedParallelTools
from db import get_postgres_db

AGNO_DOCS_MCP_URL = "https://docs.agno.com/mcp"

# The `think`/`analyze` steps reach users: the portal chat shows each step's title and
# text. agno's default instructions are English-only and never name a language, so the
# model titled steps in English ("Remember about") under pt-BR answers. Passing
# `instructions` replaces the default text, so keep it and append the language rule.
REASONING_INSTRUCTIONS = (
    "<reasoning_instructions>\n"
    + ReasoningTools.DEFAULT_INSTRUCTIONS
    + "\n- **Language:** always write `title`, `thought`, `action`, `analysis` and `result` in Brazilian"
    " Portuguese (pt-BR), whatever language these instructions are in — users read these steps in the chat."
    "\n</reasoning_instructions>\n"
)


def get_agno_docs_tools() -> list[MCPTools]:
    return [MCPTools(transport="streamable-http", url=AGNO_DOCS_MCP_URL, name="agno_docs")]


def get_parallel_tools() -> list[ParallelTools | MCPTools]:
    if getenv("PARALLEL_API_KEY"):
        return [SharedParallelTools()]
    # timeout_seconds: web_fetch page extraction regularly exceeds the 10s MCP default.
    return [
        MCPTools(
            url="https://search.parallel.ai/mcp", transport="streamable-http", name="parallel_tools", timeout_seconds=30
        )
    ]


def route_component_type(request: str) -> str:
    """Suggest agent, team, or workflow from a plain-language request."""
    lower = request.lower()
    if any(word in lower for word in ("daily", "schedule", "pipeline", "approval", "steps", "workflow")):
        return "workflow"
    if any(word in lower for word in ("team", "specialists", "debate", "reviewers", "coordinate")):
        return "team"
    return "agent"


def score_eval_status(passed: int, total: int) -> str:
    """Return PASS only when every selected eval case passed."""
    if total <= 0:
        return "FAIL"
    return "PASS" if passed == total else "FAIL"


registry = Registry(
    name="AgentOS Registry",
    tools=[
        *get_agno_docs_tools(),
        *get_parallel_tools(),
        *get_jira_tools(),
        ReasoningTools(add_instructions=True, instructions=REASONING_INSTRUCTIONS),
    ],
    models=[default_model(), *(default_model(id=model_id) for model_id in STUDIO_MODEL_IDS)],
    dbs=[get_postgres_db()],
    functions=[route_component_type, score_eval_status],
    agents=[platform_manager, crm_note_autofix, general_chat, jira_ticket_responder],
)
