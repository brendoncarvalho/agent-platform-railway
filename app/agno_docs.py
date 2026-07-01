"""
Agno Docs MCP
=============
"""

from agno.tools.mcp import MCPTools

AGNO_DOCS_MCP_URL = "https://docs.agno.com/mcp"


def get_agno_docs_mcp_tools() -> list[MCPTools]:
    """Return a fresh toolkit for Agno's public docs MCP server."""
    tools = MCPTools(transport="streamable-http", url=AGNO_DOCS_MCP_URL)
    # agno 2.6.20 hardcodes name="MCPTools" for every MCP toolkit; a distinct
    # name keeps Studio registry discovery and tool_names resolution unambiguous.
    tools.name = "agno_docs"
    return [tools]
