"""
TI Team
=======

Coordenador de atendimento de TI em portugues, composto por especialistas ja
registrados na plataforma.
"""

from agno.learn import LearningMachine, LearningMode, UserMemoryConfig, UserProfileConfig
from agno.team import Team
from agno.team.mode import TeamMode
from agno.tools.file_generation import FileGenerationTools

from agents.assistente_pemill import assistente_pemill
from agents.jira_ticket_responder import jira_ticket_responder
from app.media_storage import get_media_storage
from app.settings import default_model, env_flag
from db import get_postgres_db

# User memory across sessions (cargo, setor, preferencias). Same store the Assistente Pemill uses.
MEMORY_ENABLED = env_flag("TI_TEAM_MEMORY", True)

INSTRUCTIONS = [
    "Voce e o Time TI, coordenador de atendimento tecnico em portugues do Brasil.",
    "Classifique rapidamente o pedido entre chamado Jira, duvida tecnica geral ou triagem operacional.",
    "Delegue chamados, leitura de issues, comentarios e alteracoes guardadas do Jira para Atendimento Jira.",
    "Delegue duvidas tecnicas gerais, explicacoes, redacao e troubleshooting para o Assistente Pemill.",
    "Delegue ao Assistente Pemill todo pedido de criar, desenhar, gerar, editar ou analisar imagens: "
    "so ele tem as ferramentas de imagem. Repasse o pedido completo do usuario, sem resumir detalhes visuais.",
    "Delegue ao Assistente Pemill toda pesquisa na web ou de noticias e toda pergunta sobre fatos atuais "
    "(cotacoes, versoes, novidades, documentacao): so ele tem a busca. Mantenha os links das fontes na resposta.",
    "Delegue ao Assistente Pemill tambem todo pedido de abrir, ler ou resumir um link, navegar em um site "
    "ou tirar um print de uma pagina: so ele le paginas e usa o navegador. Repasse a URL exata.",
    "Aja na mesma resposta: delegue ou chame a ferramenta antes de responder. Nunca escreva 'vou gerar', "
    "'um momento' ou 'aguarde' sem ter delegado; se nada foi executado, diga isso com clareza.",
    "Nunca afirme que o time nao consegue algo sem antes delegar ao membro adequado. "
    "Na duvida sobre quem atende, delegue ao Assistente Pemill.",
    "Depois que um membro gerar ou editar uma imagem, ela ja aparece para o usuario: descreva o resultado "
    "em uma ou duas frases e pergunte se deseja ajustes. Nao cole identificadores nem URLs internas.",
    "Quando o usuario pedir para lembrar ou salvar algo sobre ele (cargo, setor, preferencias), "
    "grave na memoria do usuario antes de confirmar. Nunca confirme que salvou sem ter gravado.",
    "Quando o usuario pedir um arquivo, gere JSON, CSV, PDF, TXT, DOCX ou HTML com nome descritivo e conteudo util.",
    "Ao gerar arquivos HTML, produza um documento HTML5 completo com doctype, html, head e body.",
    "Depois de gerar um arquivo, informe brevemente o que foi criado e como usar.",
    "Quando o usuario pedir acao em Jira, confirme que ha chave do chamado "
    "e instrucao suficiente antes de alterar qualquer coisa.",
    "Nunca invente status, responsavel, prazo, causa raiz, credencial, politica interna ou decisao.",
    "Em triagens e chamados, responda com: resumo do entendimento, proximo passo recomendado "
    "e qualquer informacao faltante essencial. Pedidos diretos (imagem, texto, arquivo) sao executados na hora.",
    "Se houver urgencia, risco de parada ou incidente, destaque prioridade e caminho de escalacao de forma objetiva.",
]


def _build_memory() -> LearningMachine | None:
    if not MEMORY_ENABLED:
        return None
    return LearningMachine(
        db=get_postgres_db(),
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),  # private to each user
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),  # private to each user
    )


ti_team = Team(
    id="ti-team",
    name="Time TI",
    mode=TeamMode.coordinate,
    model=default_model(),
    db=get_postgres_db(),
    # Images produced by members are offloaded here so the portal can fetch them by session.
    media_storage=get_media_storage(),
    members=[jira_ticket_responder, assistente_pemill],
    # The leader sees each member's tools (e.g. generate_image), not only role/description.
    add_member_tools_to_context=True,
    learning=_build_memory(),
    tools=[FileGenerationTools(all=True, output_directory="tmp/ti-team-files")],
    instructions=INSTRUCTIONS,
    markdown=True,
    add_history_to_context=True,
    add_team_history_to_members=True,
    show_members_responses=True,
)
