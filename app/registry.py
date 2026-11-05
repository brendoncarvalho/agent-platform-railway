"""
AgentOS Registry
================

The tools, models, databases, and agents available to AgentOS Studio when building new
components from the UI.
"""

from agno.registry import Registry
from agno.tools.reasoning import ReasoningTools

from agents.assistente_pemill import assistente_pemill
from agents.crm_note_autofix import crm_note_autofix
from agents.hr_resume_analyst import hr_resume_analyst
from agents.jira_ticket_responder import jira_ticket_responder
from app.jira_tools import get_jira_tools
from app.settings import STUDIO_MODEL_IDS, default_model
from app.web_browser import build_browser_tools
from app.web_reader import build_web_reader_tools
from app.web_search import build_web_search_tools
from db import get_postgres_db

# The `think`/`analyze` steps reach users: the portal chat shows each step's title and
# text. agno's default instructions are English-only and never name a language, so the
# model titled steps in English ("Remember about") under pt-BR answers. Passing
# `instructions` replaces the default text, so keep it and append the language rule.
REASONING_INSTRUCTIONS = (
    "<reasoning_instructions>\n"
    + ReasoningTools.DEFAULT_INSTRUCTIONS
    + "\n- **Language:** always write `title`, `thought`, `action`, `analysis` and `result` in Brazilian"
    " Portuguese (pt-BR), whatever language these instructions are in — users read these steps in the chat."
    "\n</reasoning_instructions>\n"
)

# Web tools offered to agents built in the portal too; a builder returns None when switched off.
_web_tools = [
    toolkit
    for toolkit in (build_web_search_tools(), build_web_reader_tools(), build_browser_tools())
    if toolkit is not None
]

registry = Registry(
    name="Pemill Registry",
    tools=[
        *get_jira_tools(),
        ReasoningTools(add_instructions=True, instructions=REASONING_INSTRUCTIONS),
        *_web_tools,
    ],
    models=[default_model(), *(default_model(id=model_id) for model_id in STUDIO_MODEL_IDS)],
    dbs=[get_postgres_db()],
    agents=[assistente_pemill, crm_note_autofix, jira_ticket_responder, hr_resume_analyst],
)
