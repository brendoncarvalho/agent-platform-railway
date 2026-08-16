"""
Jira Tools
==========

Guarded Jira tools shared by the registry and Jira-facing agents.
"""

import json
from os import getenv
from typing import Any

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


def check_jira_configuration() -> str:
    """Verifica a configuração do Jira sem expor segredos.

    Use quando as ferramentas do Jira parecerem indisponíveis ou quando uma
    conexão falhar. Retorna quais variáveis obrigatórias estão configuradas,
    quais estão ausentes e se mutações guardadas estão habilitadas.
    """
    required_state = {
        "JIRA_SERVER_URL": bool(getenv("JIRA_SERVER_URL")),
        "JIRA_USERNAME": bool(getenv("JIRA_USERNAME")),
        "JIRA_TOKEN_or_JIRA_PASSWORD": bool(getenv("JIRA_TOKEN") or getenv("JIRA_PASSWORD")),
    }
    missing = [name for name, configured in required_state.items() if not configured]
    payload = {
        "configured": not missing,
        "missing": missing,
        "mutations_enabled": env_flag("JIRA_ENABLE_MUTATIONS", default=False),
        "server_url_set": required_state["JIRA_SERVER_URL"],
        "username_set": required_state["JIRA_USERNAME"],
        "secret_set": required_state["JIRA_TOKEN_or_JIRA_PASSWORD"],
    }
    return json.dumps(payload, ensure_ascii=False)


def _jira_client() -> Any:
    from jira import JIRA

    username = getenv("JIRA_USERNAME", "")
    secret = getenv("JIRA_TOKEN") or getenv("JIRA_PASSWORD", "")
    jira = JIRA(server=getenv("JIRA_SERVER_URL"), basic_auth=(username, secret))

    # Defensive compatibility guard for python-jira ResilientSession. Without
    # these attributes some error paths raise AttributeError before exposing the
    # real Jira HTTP/auth response.
    session = getattr(jira, "_session", None)
    if session is not None:
        if not hasattr(session, "max_retries"):
            session.max_retries = 3
        if not hasattr(session, "max_retry_delay"):
            session.max_retry_delay = 60
    return jira


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


def _jira_user_summary(user: Any) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "account_id": getattr(user, "accountId", None),
        "display_name": getattr(user, "displayName", None),
        "email": getattr(user, "emailAddress", None),
        "name": getattr(user, "name", None),
        "key": getattr(user, "key", None),
    }


def _jira_field_name(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "name", str(value))


def _jira_issue_summary(issue: Any, include_description: bool = False) -> dict[str, Any]:
    fields = issue.fields
    payload = {
        "key": issue.key,
        "summary": getattr(fields, "summary", None),
        "status": _jira_field_name(getattr(fields, "status", None)),
        "issue_type": _jira_field_name(getattr(fields, "issuetype", None)),
        "priority": _jira_field_name(getattr(fields, "priority", None)),
        "assignee": _jira_user_summary(getattr(fields, "assignee", None)),
        "reporter": _jira_user_summary(getattr(fields, "reporter", None)),
        "created": getattr(fields, "created", None),
        "updated": getattr(fields, "updated", None),
    }
    if include_description:
        payload["description"] = getattr(fields, "description", None)
    return payload


def search_jira_issues(jql: str, max_results: int = 10) -> str:
    """Busca chamados no Jira usando JQL e retorna um resumo em JSON.

    Use esta ferramenta para localizar chamados antes de responder. Não altera
    nenhum conteúdo do Jira.
    """
    jira = _jira_client()
    safe_limit = max(1, min(max_results, 25))
    issues = jira.search_issues(jql, maxResults=safe_limit)
    payload = [_jira_issue_summary(issue) for issue in issues]
    return json.dumps(payload, ensure_ascii=False, default=str)


def get_jira_issue(issue_key: str) -> str:
    """Obtém detalhes de um chamado Jira e retorna JSON.

    Use esta ferramenta para ler o chamado antes de responder ou executar uma
    ação guardada. Não altera nenhum conteúdo do Jira.
    """
    jira = _jira_client()
    issue = jira.issue(issue_key)
    payload = _jira_issue_summary(issue, include_description=True)

    try:
        comments = jira.comments(issue_key)
    except Exception:
        comments = []

    payload["comments"] = [
        {
            "id": getattr(comment, "id", None),
            "author": _jira_user_summary(getattr(comment, "author", None)),
            "created": getattr(comment, "created", None),
            "updated": getattr(comment, "updated", None),
            "body": getattr(comment, "body", None),
        }
        for comment in comments[-5:]
    ]
    return json.dumps(payload, ensure_ascii=False, default=str)


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

    Uses custom read tools instead of Agno's native JiraTools so every Jira
    operation goes through the same guarded client setup.
    """
    tools: list[Any] = [
        check_jira_configuration,
    ]
    if not jira_credentials_configured():
        return tools

    tools.extend(
        [
            search_jira_issues,
            get_jira_issue,
        ]
    )
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
