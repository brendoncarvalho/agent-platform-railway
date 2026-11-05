"""Time TI wiring: the leader must know who generates images and must be able to remember users."""

from agno.learn import LearningMachine

from agents.assistente_pemill import assistente_pemill
from agents.jira_ticket_responder import jira_ticket_responder
from agents.ti_team import INSTRUCTIONS, ti_team
from app.media_storage import get_media_storage


def test_members_describe_themselves_to_the_leader():
    assert ti_team.members == [jira_ticket_responder, assistente_pemill]
    # agno shows role/description of each member to the leader; that is how it routes.
    assert assistente_pemill.role and "imagens" in assistente_pemill.role
    assert assistente_pemill.description and "gera imagens" in assistente_pemill.description
    assert jira_ticket_responder.role and "Jira" in jira_ticket_responder.role
    assert ti_team.add_member_tools_to_context is True


def test_instructions_route_images_and_forbid_empty_promises():
    text = " ".join(INSTRUCTIONS).lower()
    assert "imagens" in text and "assistente pemill" in text
    assert "vou gerar" in text  # the forbidden promise is named explicitly
    assert "nunca afirme que o time nao consegue" in text
    assert "memoria do usuario" in text


def test_team_has_user_memory_and_media_storage():
    assert isinstance(ti_team.learning, LearningMachine)
    assert ti_team.media_storage is get_media_storage()
