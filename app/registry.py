"""
Studio Registry
===============
"""

from os import getenv

from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.mcp import MCPTools
from agno.tools.parallel import ParallelTools
from agno.tools.reasoning import ReasoningTools

from agents.code_search import code_search
from agents.web_search import web_search
from app.agno_docs import get_agno_docs_mcp_tools
from app.settings import default_model
from app.studio_components import (
    AgentSpec,
    EvalReport,
    list_project_files,
    read_project_file,
    route_component_type,
    score_eval_status,
    search_project_text,
)
from db import get_postgres_db


def _get_web_tools() -> list[ParallelTools | MCPTools]:
    """Return web tools for builder-created components."""
    if getenv("PARALLEL_API_KEY"):
        return [ParallelTools()]
    return [MCPTools(url="https://search.parallel.ai/mcp", transport="streamable-http", name="parallel_web_search")]


def _get_tools() -> list:
    """Build the safe public toolkit registry for StudioTools."""
    return [
        *get_agno_docs_mcp_tools(),
        *_get_web_tools(),
        CalculatorTools(),
        ReasoningTools(add_instructions=True),
    ]


registry = Registry(
    name="Self-Driving Agent Platform Registry",
    description="Safe tools, schemas, functions, models, databases, and reference agents for Agent Builder.",
    tools=_get_tools(),
    models=[default_model()],
    dbs=[get_postgres_db()],
    schemas=[AgentSpec, EvalReport],
    functions=[route_component_type, score_eval_status, list_project_files, read_project_file, search_project_text],
    agents=[web_search, code_search],
)
