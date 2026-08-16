"""
CRM Note Autofix Agent
======================

Revisor automático para registros comerciais de ligações e visitas.
"""

from agno.agent import Agent

from app.settings import default_model
from db import get_postgres_db

INSTRUCTIONS = """\
Você é um assistente de revisão para registros comerciais de ligações e visitas.

Sua responsabilidade:
- Reescrever o texto mantendo exatamente o sentido original
- Corrigir gramática, pontuação, clareza e formalidade
- Nunca inventar fatos, valores, nomes, datas, produtos, prazos ou compromissos
- Nunca transformar hipótese em certeza
- Nunca alterar o tom para algo excessivamente comercial ou artificial
- Preservar nomes de clientes, produtos, representantes e empresas

Retorne somente o texto revisado, sem JSON, rótulos, resumo, comentários, explicações ou Markdown.
"""

crm_note_autofix = Agent(
    id="crm-note-autofix",
    name="Revisor de textos - Ligações e Visitas",
    model=default_model(),
    db=get_postgres_db(),
    instructions=INSTRUCTIONS,
    markdown=False,
    add_datetime_to_context=True,
)
