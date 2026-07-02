"""
Studio Registry
===============

The safe surface Agent Builder composes from: tools, schemas, functions,
models, databases, and reference agents — everything in one place.
"""

from os import getenv
from typing import Literal

from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.mcp import MCPTools
from agno.tools.parallel import ParallelTools
from agno.tools.reasoning import ReasoningTools
from pydantic import BaseModel, Field

from agents.code_search import code_search
from agents.web_search import web_search
from app.settings import default_model
from db import get_postgres_db

AGNO_DOCS_MCP_URL = "https://docs.agno.com/mcp"


def get_agno_docs_mcp_tools() -> list[MCPTools]:
    """Return a fresh toolkit for Agno's public docs MCP server."""
    return [MCPTools(transport="streamable-http", url=AGNO_DOCS_MCP_URL, name="agno_docs")]


def _get_web_tools() -> list[ParallelTools | MCPTools]:
    """Return web tools for builder-created components."""
    if getenv("PARALLEL_API_KEY"):
        return [ParallelTools()]
    return [MCPTools(url="https://search.parallel.ai/mcp", transport="streamable-http", name="parallel_web_search")]


class AgentSpec(BaseModel):
    """Structured input for a proposed agent, team, or workflow."""

    name: str = Field(description="Human-readable component name.")
    purpose: str = Field(description="One sentence describing the job to be done.")
    component_type: Literal["agent", "team", "workflow"] = Field(description="Best-fit component type.")
    required_tools: list[str] = Field(default_factory=list, description="Registry tool names the component needs.")


class EvalReport(BaseModel):
    """Structured output for eval regression summaries."""

    profile: str = Field(description="Eval profile that ran, such as smoke, release, or live.")
    total: int = Field(description="Total cases selected.")
    passed: int = Field(description="Cases that passed.")
    failed: int = Field(description="Cases that failed.")
    status: Literal["PASS", "FAIL"] = Field(description="Overall eval status.")


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
    name="Self-Driving Agent Platform Registry",
    description="Safe tools, schemas, functions, models, databases, and reference agents for Agent Builder.",
    tools=[
        *get_agno_docs_mcp_tools(),
        *_get_web_tools(),
        CalculatorTools(),
        ReasoningTools(add_instructions=True),
    ],
    models=[default_model()],
    dbs=[get_postgres_db()],
    schemas=[AgentSpec, EvalReport],
    functions=[route_component_type, score_eval_status],
    agents=[web_search, code_search],
)
