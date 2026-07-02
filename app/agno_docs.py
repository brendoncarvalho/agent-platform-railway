"""
Agno Docs MCP
=============
"""

from agno.tools.mcp import MCPTools

AGNO_DOCS_MCP_URL = "https://docs.agno.com/mcp"


def get_agno_docs_mcp_tools() -> list[MCPTools]:
    """Return a fresh toolkit for Agno's public docs MCP server."""
    return [MCPTools(transport="streamable-http", url=AGNO_DOCS_MCP_URL, name="agno_docs")]
