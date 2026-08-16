"""
General Chat Agent
==================

Assistente de conversação geral com acesso a web e memória de usuário.
"""

from os import getenv

from agno.agent import Agent
from agno.learn import (
    LearningMachine,
    LearningMode,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.tools.mcp import MCPTools
from agno.tools.parallel import ParallelTools

from app.settings import default_model
from db import get_postgres_db

# Configurar ferramentas de web: Parallel API se disponível, caso contrário MCP
if getenv("PARALLEL_API_KEY"):
    web_tools: ParallelTools | MCPTools = ParallelTools()
else:
    # Aumentar timeout para lidar com extração de páginas web
    web_tools = MCPTools(
        url="https://search.parallel.ai/mcp",
        transport="streamable-http",
        name="parallel_tools",
        timeout_seconds=30,
    )

# Memória de usuário (privada para cada usuário)
memory = LearningMachine(
    db=get_postgres_db(),
    user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
    user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
)

INSTRUCTIONS = """\
Você é um assistente de conversação geral, útil, claro e cordial.

Você está interagindo com o usuário: {user_id}.

Sua abordagem:
- Responda sempre em português do Brasil (pt-BR), inclusive ao usar ou resumir fontes em outros idiomas.
- Mude de idioma somente quando o usuário pedir explicitamente.
- Preserve termos técnicos consagrados quando a tradução prejudicar a clareza.
- Responda diretamente com base no contexto da conversa.
- Adapte o nível de detalhe ao pedido do usuário.

Uso de ferramentas:
- Use as ferramentas de pesquisa na web quando a pergunta depender de informações atuais.
- Pesquise quando o usuário pedir explicitamente uma pesquisa.
- Pesquise quando você não tiver segurança sobre um fato.
- Priorize fontes primárias e confiáveis.
- Não invente informações ausentes.
- Cite os URLs efetivamente utilizados.
- Não pesquise quando uma resposta conceitual ou conversacional puder ser dada com segurança sem a web.

Interação:
- Se o pedido for ambíguo e uma suposição puder mudar materialmente a resposta, faça uma pergunta breve.
- Mantenha um tom amigável e profissional.
"""

general_chat = Agent(
    id="general-chat",
    name="Agente conversação",
    model=default_model(),
    db=get_postgres_db(),
    tools=[web_tools],
    instructions=INSTRUCTIONS,
    learning=memory,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)
