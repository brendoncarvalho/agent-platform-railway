"""
Jira Tools
==========

Guarded Jira tools shared by the registry and Jira-facing agents.
"""

from os import getenv
from typing import Any

from agno.tools.jira import JiraTools

JIRA_AI_COMMENT_MARKER = "<!-- agentos-ai-comment -->"
JIRA_AI_COMMENT_FOOTER = "Informação gerada por uma ferramenta de IA."


def env_flag(name: str, default: bool = False) -> bool:
    value = getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes")


def jira_credentials_configured() -> bool:
    return bool(
        getenv("JIRA_SERVER_URL")
        and getenv("JIRA_USERNAME")
        and (getenv("JIRA_TOKEN") or getenv("JIRA_PASSWORD"))
    )


def _jira_client() -> Any:
    from jira import JIRA

    username = getenv("JIRA_USERNAME", "")
    secret = getenv("JIRA_TOKEN") or getenv("JIRA_PASSWORD", "")
    return JIRA(server=getenv("JIRA_SERVER_URL"), basic_auth=(username, secret))


def _jira_user_matches(user: Any, expected: str) -> bool:
    expected = expected.strip().lower()
    candidates = {
        str(value).strip().lower()
        for value in (
            getattr(user, "accountId", None),
            getattr(user, "emailAddress", None),
            getattr(user, "name", None),
            getattr(user, "key", None),
            getattr(user, "displayName", None),
        )
        if value
    }
    return expected in candidates


def _format_jira_ai_comment(comment_pt_br: str) -> str:
    body = comment_pt_br.strip()
    return f"Olá!\n\n{body}\n\n{JIRA_AI_COMMENT_MARKER}\n---\n{JIRA_AI_COMMENT_FOOTER}"


def _explicitly_requested(value: str, user_request_quote: str) -> bool:
    return value.strip().lower() in user_request_quote.strip().lower()


def comment_jira_issue(issue_key: str, comment_pt_br: str) -> str:
    """Adiciona um comentário de resposta em português do Brasil a qualquer chamado Jira.

    Use para responder chamados Jira. O comentário deve ser escrito em
    português do Brasil. A ferramenta adiciona saudação e aviso final de IA.
    Também adiciona um marcador interno para permitir editar somente
    comentários criados por esta ferramenta.
    """
    jira = _jira_client()
    formatted_comment = _format_jira_ai_comment(comment_pt_br)
    created_comment = jira.add_comment(issue_key, formatted_comment)
    comment_id = getattr(created_comment, "id", "unknown")
    return f"Comentário {comment_id} adicionado ao chamado {issue_key}."


def edit_jira_ai_comment(issue_key: str, comment_id: str, comment_pt_br: str) -> str:
    """Edita um comentário Jira somente quando ele foi criado por esta ferramenta de IA.

    Recusa editar comentários sem o marcador desta ferramenta ou que não foram
    criados por JIRA_USERNAME. Nunca use para deletar conteúdo. O novo texto
    deve estar em português do Brasil; a ferramenta adiciona novamente a
    saudação e o aviso de IA.
    """
    jira = _jira_client()
    comment = jira.comment(issue_key, comment_id)
    existing_body = getattr(comment, "body", "")
    author = getattr(comment, "author", None)

    if JIRA_AI_COMMENT_MARKER not in existing_body:
        return (
            f"Recusado: o comentário {comment_id} no chamado {issue_key} não "
            "foi criado por esta ferramenta de IA. Nenhuma alteração foi feita no Jira."
        )

    if not _jira_user_matches(author, getenv("JIRA_USERNAME", "")):
        return (
            f"Recusado: o comentário {comment_id} no chamado {issue_key} não "
            "foi criado por JIRA_USERNAME. Nenhuma alteração foi feita no Jira."
        )

    comment.update(body=_format_jira_ai_comment(comment_pt_br))
    return f"Comentário {comment_id} do chamado {issue_key} atualizado."


def transition_jira_issue(issue_key: str, target_status: str, user_request_quote: str) -> str:
    """Move um chamado Jira para um status explicitamente solicitado pelo usuário.

    Só use quando a solicitação do usuário declarar claramente o status de destino.
    Passe em user_request_quote o trecho literal da solicitação que contém esse
    status. A ferramenta recusa se target_status não aparecer nesse trecho.
    """
    if not _explicitly_requested(target_status, user_request_quote):
        return (
            f"Recusado: o status '{target_status}' não aparece explicitamente "
            "na solicitação informada. Nenhuma alteração foi feita no Jira."
        )

    jira = _jira_client()
    transitions = jira.transitions(issue_key)
    matching_transition = next(
        (
            transition
            for transition in transitions
            if str(transition.get("name", "")).strip().lower() == target_status.strip().lower()
        ),
        None,
    )
    if matching_transition is None:
        available = ", ".join(str(transition.get("name")) for transition in transitions)
        return (
            f"Recusado: o status '{target_status}' não está disponível para "
            f"{issue_key}. Transições disponíveis: {available}."
        )

    jira.transition_issue(issue_key, matching_transition["id"])
    return f"Chamado {issue_key} movido para '{target_status}'."


def set_jira_issue_original_estimate(issue_key: str, original_estimate: str, user_request_quote: str) -> str:
    """Define o tempo previsto de um chamado Jira quando explicitamente solicitado.

    Só use quando a solicitação do usuário declarar claramente o tempo previsto,
    por exemplo "2h", "30m", "1d" ou "3h 30m". Passe em user_request_quote o
    trecho literal da solicitação que contém esse valor. A ferramenta recusa se
    original_estimate não aparecer nesse trecho.
    """
    if not _explicitly_requested(original_estimate, user_request_quote):
        return (
            f"Recusado: o tempo previsto '{original_estimate}' não aparece "
            "explicitamente na solicitação informada. Nenhuma alteração foi feita no Jira."
        )

    jira = _jira_client()
    issue = jira.issue(issue_key)
    issue.update(fields={"timetracking": {"originalEstimate": original_estimate}})
    return f"Tempo previsto de {issue_key} definido como '{original_estimate}'."


def assign_jira_issue(issue_key: str, assignee: str, user_request_quote: str) -> str:
    """Atribui um responsável a um chamado Jira quando explicitamente solicitado.

    Só use quando a solicitação do usuário declarar claramente quem deve ser o
    responsável. Passe em user_request_quote o trecho literal da solicitação que
    contém o identificador, e-mail, accountId ou nome do responsável. A ferramenta
    recusa se assignee não aparecer nesse trecho.
    """
    if not _explicitly_requested(assignee, user_request_quote):
        return (
            f"Recusado: o responsável '{assignee}' não aparece explicitamente "
            "na solicitação informada. Nenhuma alteração foi feita no Jira."
        )

    jira = _jira_client()
    jira.assign_issue(issue_key, assignee)
    return f"Chamado {issue_key} atribuído para '{assignee}'."


def get_jira_tools() -> list[Any]:
    """Expose Jira tools when credentials are configured.

    Native JiraTools stay read-only. Jira writes are opt-in and limited to
    guarded tools: add comments anywhere; edit only AI-created comments; move
    status, set estimates, and assign owners only when explicit; and never delete.
    """
    if not jira_credentials_configured():
        return []

    tools: list[Any] = [
        JiraTools(
            enable_search_issues=True,
            enable_get_issue=True,
            enable_create_issue=False,
            enable_add_comment=False,
            enable_add_worklog=False,
        )
    ]
    if env_flag("JIRA_ENABLE_MUTATIONS", default=False):
        tools.extend(
            [
                comment_jira_issue,
                edit_jira_ai_comment,
                transition_jira_issue,
                set_jira_issue_original_estimate,
                assign_jira_issue,
            ]
        )
    return tools
