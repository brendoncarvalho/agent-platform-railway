"""
WebSearch Agent
===============
"""

from os import getenv

from agno.agent import Agent
from agno.tools.mcp import MCPTools
from agno.tools.parallel import ParallelTools

from app.settings import default_model
from db import get_postgres_db

# When PARALLEL_API_KEY is set, use the parallel-web SDK.
# Without a key, fall back to the keyless MCP endpoint.
# AgentOS handles MCP connect/close as part of its lifespan.
if getenv("PARALLEL_API_KEY"):
    web_tools: ParallelTools | MCPTools = ParallelTools()
else:
    # timeout_seconds: web_fetch page extraction regularly exceeds the 10s MCP default.
    web_tools = MCPTools(
        url="https://search.parallel.ai/mcp", transport="streamable-http", name="parallel_tools", timeout_seconds=30
    )


WEB_SEARCH_INSTRUCTIONS = """\
Search the web for current information. Keep your answers grounded in the information you find. Don't over-search.

Workflow:
1. Use the search tool to find candidate sources.
2. Prefer official primary sources over blogs and community articles.
3. For questions about latest versions, releases, dates, changelogs, or recent events:
   - answer only from results found in the current run;
   - fetch the most relevant official URLs before answering when snippets are too thin;
   - do not infer publications, titles, dates, or claims beyond what the results support;
   - ignore stale or contextually unrelated excerpts.
4. Use community sources only as supplementary material.
5. Cite only sources actually used in the answer as plain URLs.
6. If reliable official information cannot be confirmed, say so plainly.
"""


web_search = Agent(
    id="web-search",
    name="WebSearch",
    model=default_model(),
    db=get_postgres_db(),
    tools=[web_tools],
    instructions=WEB_SEARCH_INSTRUCTIONS,
    enable_agentic_memory=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
)
