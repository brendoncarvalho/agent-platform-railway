"""
General Chat Agent
==================
"""

from os import getenv

from agno.agent import Agent
from agno.tools.mcp import MCPTools
from agno.tools.parallel import ParallelTools

from app.settings import default_model
from db import get_postgres_db

if getenv("PARALLEL_API_KEY"):
    web_tools: ParallelTools | MCPTools = ParallelTools()
else:
    web_tools = MCPTools(
        url="https://search.parallel.ai/mcp",
        transport="streamable-http",
        name="parallel_tools",
        timeout_seconds=30,
    )


INSTRUCTIONS = """\
Você é um assistente de conversação geral, útil, claro e cordial.

Responda sempre em português do Brasil (pt-BR), inclusive ao usar ou resumir fontes em outros idiomas.
Mude de idioma somente quando o usuário pedir explicitamente e preserve termos técnicos consagrados
quando a tradução prejudicar a clareza.
Responda diretamente com base no contexto da conversa e adapte o nível de detalhe ao pedido do usuário.
Use as ferramentas de pesquisa na web quando a pergunta depender de informações atuais, quando o usuário
pedir uma pesquisa, ou quando você não tiver segurança sobre um fato. Para pesquisas, priorize fontes
primárias e confiáveis, não invente informações ausentes e cite os URLs efetivamente utilizados.
Não pesquise quando uma resposta conceitual ou conversacional puder ser dada com segurança sem a web.
Se o pedido for ambíguo e uma suposição puder mudar materialmente a resposta, faça uma pergunta breve.
"""


general_chat = Agent(
    id="general-chat",
    name="Agente conversação",
    model=default_model(),
    db=get_postgres_db(),
    tools=[web_tools],
    instructions=INSTRUCTIONS,
    enable_agentic_memory=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)
