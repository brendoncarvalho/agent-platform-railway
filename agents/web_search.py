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

# When PARALLEL_API_KEY is set, use the official parallel-web SDK —
# the agent gets `parallel_search` and `parallel_extract` directly.
# Without a key, fall back to the keyless MCP endpoint and the agent
# gets `web_search` and `web_fetch` instead. AgentOS handles MCP
# connect/close as part of its lifespan.
if getenv("PARALLEL_API_KEY"):
    web_tools: ParallelTools | MCPTools = ParallelTools()
else:
    web_tools = MCPTools(url="https://search.parallel.ai/mcp", transport="streamable-http")


WEB_SEARCH_INSTRUCTIONS = """\
Search the web for current information.

Workflow:
1. Use the search tool to find candidate sources.
2. Prefer official primary sources over blogs and community articles.
3. For questions about latest versions, releases, dates, changelogs, or recent events:
   - always fetch the most relevant official URLs before answering;
   - do not rely only on search excerpts;
   - ignore stale or contextually unrelated excerpts.
4. Use community sources only as supplementary material.
5. Cite only sources actually used in the answer.
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
    markdown=True,
)
