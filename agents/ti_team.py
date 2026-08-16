"""
TI Team
=======

Coordenador de atendimento de TI em portugues, composto por especialistas ja
registrados na plataforma.
"""

from agno.team import Team
from agno.team.mode import TeamMode
from agno.tools.file_generation import FileGenerationTools

from agents.general_chat import general_chat
from agents.jira_ticket_responder import jira_ticket_responder
from agents.platform_manager import platform_manager
from app.settings import default_model
from db import get_postgres_db

INSTRUCTIONS = [
    "Voce e o Time TI, coordenador de atendimento tecnico em portugues do Brasil.",
    "Classifique rapidamente o pedido entre chamado Jira, duvida tecnica geral, "
    "diagnostico da plataforma ou triagem operacional.",
    "Delegue chamados, leitura de issues, comentarios e alteracoes guardadas do Jira para Atendimento Jira.",
    "Delegue perguntas sobre esta plataforma AgentOS, runtime, configuracao, "
    "agentes, workflows, schedules e diagnosticos para Platform Manager.",
    "Delegue pesquisas, explicacoes e troubleshooting geral para Agente conversacao.",
    "Quando o usuario pedir um arquivo, gere JSON, CSV, PDF, TXT, DOCX ou HTML com "
    "nome descritivo e conteudo util.",
    "Ao gerar arquivos HTML, produza um documento HTML5 completo com doctype, html, head e body.",
    "Depois de gerar um arquivo, informe brevemente o que foi criado e como usar.",
    "Quando o usuario pedir acao em Jira, confirme que ha chave do chamado "
    "e instrucao suficiente antes de alterar qualquer coisa.",
    "Nunca invente status, responsavel, prazo, causa raiz, credencial, politica interna ou decisao.",
    "Responda com: resumo do entendimento, proximo passo recomendado e qualquer informacao faltante essencial.",
    "Se houver urgencia, risco de parada ou incidente, destaque prioridade e "
    "caminho de escalacao de forma objetiva.",
]

ti_team = Team(
    id="ti-team",
    name="Time TI",
    mode=TeamMode.coordinate,
    model=default_model(),
    db=get_postgres_db(),
    members=[jira_ticket_responder, platform_manager, general_chat],
    tools=[FileGenerationTools(all=True, output_directory="tmp/ti-team-files")],
    instructions=INSTRUCTIONS,
    markdown=True,
    add_history_to_context=True,
    add_team_history_to_members=True,
    show_members_responses=True,
)
