"""
Jira Tools
==========

Guarded Jira tools shared by the registry and Jira-facing agents.
"""

import json
from os import getenv
from typing import Any
from urllib.parse import quote
from uuid import UUID

JIRA_AI_COMMENT_MARKER = "<!-- agentos-ai-comment -->"
JIRA_AI_COMMENT_FOOTER = "**Resposta enviada/gerada por uma ferramenta de IA.**"
JIRA_LEGACY_AI_COMMENT_FOOTER = "Informação gerada por uma ferramenta de IA."
JIRA_OAUTH2_API_BASE = "https://api.atlassian.com/ex/jira"
JIRA_REST_API_VERSION = "2"


def env_flag(name: str, default: bool = False) -> bool:
    value = getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes")


def _normalized_url(url: str | None) -> str:
    return (url or "").strip().rstrip("/").lower()


def _jira_auth_type() -> str:
    explicit = getenv("JIRA_AUTH_TYPE", "").strip().lower()
    if explicit:
        return explicit
    if getenv("JIRA_OAUTH_ACCESS_TOKEN_SECRET") or getenv("JIRA_OAUTH_CONSUMER_KEY"):
        return "oauth1"
    if getenv("JIRA_OAUTH_ACCESS_TOKEN"):
        return "oauth2"
    return "basic"


def _jira_oauth_key_cert() -> str:
    key_cert = getenv("JIRA_OAUTH_KEY_CERT")
    if key_cert:
        return key_cert.replace("\\n", "\n")

    key_cert_file = getenv("JIRA_OAUTH_KEY_CERT_FILE")
    if not key_cert_file:
        return ""

    with open(key_cert_file, encoding="utf-8") as cert_file:
        return cert_file.read()


def _jira_required_state() -> dict[str, bool]:
    auth_type = _jira_auth_type()
    if auth_type not in ("basic", "oauth2", "oauth1"):
        return {"JIRA_AUTH_TYPE_supported": False}
    if auth_type == "oauth2":
        return {
            "JIRA_OAUTH_ACCESS_TOKEN_or_CLIENT_CREDENTIALS": bool(
                getenv("JIRA_OAUTH_ACCESS_TOKEN")
                or (getenv("JIRA_OAUTH_CLIENT_ID") and getenv("JIRA_OAUTH_CLIENT_SECRET"))
            ),
            "JIRA_CLOUD_ID_or_JIRA_SERVER_URL": bool(getenv("JIRA_CLOUD_ID") or getenv("JIRA_SERVER_URL")),
        }
    if auth_type == "oauth1":
        return {
            "JIRA_SERVER_URL": bool(getenv("JIRA_SERVER_URL")),
            "JIRA_OAUTH_ACCESS_TOKEN": bool(getenv("JIRA_OAUTH_ACCESS_TOKEN")),
            "JIRA_OAUTH_ACCESS_TOKEN_SECRET": bool(getenv("JIRA_OAUTH_ACCESS_TOKEN_SECRET")),
            "JIRA_OAUTH_CONSUMER_KEY": bool(getenv("JIRA_OAUTH_CONSUMER_KEY")),
            "JIRA_OAUTH_KEY_CERT_or_FILE": bool(getenv("JIRA_OAUTH_KEY_CERT") or getenv("JIRA_OAUTH_KEY_CERT_FILE")),
        }
    return {
        "JIRA_SERVER_URL": bool(getenv("JIRA_SERVER_URL")),
        "JIRA_USERNAME": bool(getenv("JIRA_USERNAME")),
        "JIRA_TOKEN_or_JIRA_PASSWORD": bool(getenv("JIRA_TOKEN") or getenv("JIRA_PASSWORD")),
    }


def jira_credentials_configured() -> bool:
    return all(_jira_required_state().values())


def check_jira_configuration() -> str:
    """Verifica a configuração do Jira sem expor segredos.

    Use quando as ferramentas do Jira parecerem indisponíveis ou quando uma
    conexão falhar. Retorna quais variáveis obrigatórias estão configuradas,
    quais estão ausentes e se mutações guardadas estão habilitadas.
    """
    required_state = _jira_required_state()
    missing = [name for name, configured in required_state.items() if not configured]
    payload = {
        "configured": not missing,
        "missing": missing,
        "note": "Este teste valida variáveis de ambiente; use diagnose_jira_connection para testar a API real.",
        "auth_type": _jira_auth_type(),
        "mutations_enabled": env_flag("JIRA_ENABLE_MUTATIONS", default=False),
        "server_url_set": bool(getenv("JIRA_SERVER_URL")),
        "username_set": bool(getenv("JIRA_USERNAME")),
        "basic_secret_set": bool(getenv("JIRA_TOKEN") or getenv("JIRA_PASSWORD")),
        "oauth_access_token_set": bool(getenv("JIRA_OAUTH_ACCESS_TOKEN")),
        "oauth_client_id_set": bool(getenv("JIRA_OAUTH_CLIENT_ID")),
        "oauth_client_secret_set": bool(getenv("JIRA_OAUTH_CLIENT_SECRET")),
        "oauth_access_token_secret_set": bool(getenv("JIRA_OAUTH_ACCESS_TOKEN_SECRET")),
        "oauth_consumer_key_set": bool(getenv("JIRA_OAUTH_CONSUMER_KEY")),
        "oauth_key_cert_set": bool(getenv("JIRA_OAUTH_KEY_CERT") or getenv("JIRA_OAUTH_KEY_CERT_FILE")),
        "cloud_id_set": bool(getenv("JIRA_CLOUD_ID")),
    }
    if _jira_auth_type() == "oauth2" and getenv("JIRA_CLOUD_ID"):
        cloud_id = getenv("JIRA_CLOUD_ID", "")
        if cloud_id.startswith("http://") or cloud_id.startswith("https://"):
            payload["cloud_id_format"] = "invalid_url"
        elif not _valid_uuid(cloud_id):
            payload["cloud_id_format"] = "invalid_uuid"
        else:
            payload["cloud_id_format"] = "uuid"
            payload["oauth2_api_base"] = f"{JIRA_OAUTH2_API_BASE}/{cloud_id}/rest/api/{JIRA_REST_API_VERSION}"
    return json.dumps(payload, ensure_ascii=False)


def diagnose_jira_connection(issue_key: str = "") -> str:
    """Diagnostica configuração e conectividade real com o Jira.

    Combina check_jira_configuration com test_jira_connection. Use para
    troubleshooting, especialmente quando houver HTTP 401/403/404.
    """
    configuration = json.loads(check_jira_configuration())
    payload: dict[str, Any] = {
        "ok": False,
        "configuration": configuration,
        "accessible_resources": None,
        "live_test": None,
    }
    if not configuration["configured"]:
        payload["message"] = "Configuração incompleta; a API real não foi chamada."
        return json.dumps(payload, ensure_ascii=False, default=str)

    if _jira_auth_type() == "oauth2":
        payload["accessible_resources"] = _jira_oauth2_accessible_resources_for_diagnostics()

    live_test = json.loads(test_jira_connection(issue_key=issue_key))
    payload["live_test"] = live_test
    payload["ok"] = bool(live_test.get("ok"))
    if not payload["ok"]:
        payload["message"] = "Configuração completa, mas o teste real da API falhou."
    else:
        payload["message"] = "Configuração completa e teste real da API aprovado."
    return json.dumps(payload, ensure_ascii=False, default=str)


def test_jira_connection(issue_key: str = "") -> str:
    """Testa a autenticação real com o Jira sem modificar dados.

    Use depois de check_jira_configuration para validar se o token consegue
    chamar a API. Quando issue_key for informado, também testa a leitura desse
    chamado específico.
    """
    try:
        if _jira_auth_type() == "oauth2":
            server_info = _jira_oauth2_request("GET", "/serverInfo")
            payload = {
                "ok": True,
                "auth_type": "oauth2",
                "api_base": _jira_oauth2_api_url(""),
                "server_info": {
                    "base_url": server_info.get("baseUrl"),
                    "server_title": server_info.get("serverTitle"),
                    "version": server_info.get("version"),
                },
            }
            if issue_key.strip():
                issue = _jira_oauth2_request(
                    "GET",
                    f"/issue/{quote(issue_key.strip())}",
                    params={"fields": "summary,status"},
                )
                payload["issue"] = _jira_rest_issue_summary(issue)
            return json.dumps(payload, ensure_ascii=False, default=str)

        jira = _jira_client()
        payload = {
            "ok": True,
            "auth_type": _jira_auth_type(),
            "account": _jira_user_summary(jira.myself()),
        }
        if issue_key.strip():
            payload["issue"] = _jira_issue_summary(jira.issue(issue_key.strip()))
        return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as exc:
        return _jira_error_payload(exc, "test_jira_connection")


def _jira_oauth2_access_token() -> str:
    access_token = getenv("JIRA_OAUTH_ACCESS_TOKEN")
    if access_token:
        return access_token

    import requests

    response = requests.post(
        "https://auth.atlassian.com/oauth/token",
        data={
            "client_id": getenv("JIRA_OAUTH_CLIENT_ID", ""),
            "client_secret": getenv("JIRA_OAUTH_CLIENT_SECRET", ""),
            "grant_type": "client_credentials",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        msg = "A Atlassian não retornou access_token ao trocar as credenciais OAuth 2.0."
        raise RuntimeError(msg)
    return str(token)


def _valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


def _jira_oauth2_api_url(path: str) -> str:
    cloud_id = getenv("JIRA_CLOUD_ID")
    if not cloud_id:
        cloud_id = _lookup_jira_cloud_id(_jira_oauth2_access_token())
    if cloud_id.startswith("http://") or cloud_id.startswith("https://"):
        msg = (
            "JIRA_CLOUD_ID deve ser o UUID/cloudId do site Atlassian, não a URL. "
            "Use JIRA_SERVER_URL para https://seu-site.atlassian.net."
        )
        raise RuntimeError(msg)
    if not _valid_uuid(cloud_id):
        msg = (
            "JIRA_CLOUD_ID não parece ser um UUID/cloudId válido. Obtenha o valor correto em "
            "https://api.atlassian.com/oauth/token/accessible-resources."
        )
        raise RuntimeError(msg)
    return f"{JIRA_OAUTH2_API_BASE}/{cloud_id}/rest/api/{JIRA_REST_API_VERSION}{path}"


def _jira_oauth2_request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    import requests

    url = _jira_oauth2_api_url(path)
    access_token = _jira_oauth2_access_token()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        **kwargs.pop("headers", {}),
    }
    response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
    response.raise_for_status()
    if response.status_code == 204 or not response.content:
        return {}
    return response.json()


def _text_from_adf(value: Any) -> str | None:
    if isinstance(value, str) or value is None:
        return value
    if not isinstance(value, dict):
        return str(value)

    fragments: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text" and node.get("text"):
                fragments.append(str(node["text"]))
            for child in node.get("content", []):
                walk(child)
            if node.get("type") == "paragraph":
                fragments.append("\n")
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return "".join(fragments).strip()


def _lookup_jira_cloud_id(access_token: str) -> str:
    import requests

    response = requests.get(
        "https://api.atlassian.com/oauth/token/accessible-resources",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    resources = response.json()
    if not isinstance(resources, list) or not resources:
        msg = "Nenhum recurso Jira Cloud acessível foi retornado para o token OAuth configurado."
        raise RuntimeError(msg)

    server_url = _normalized_url(getenv("JIRA_SERVER_URL"))
    if server_url:
        for resource in resources:
            if _normalized_url(resource.get("url")) == server_url:
                return str(resource["id"])
        msg = (
            "O token OAuth é válido, mas não retornou um recurso com a URL de JIRA_SERVER_URL. "
            "Defina JIRA_CLOUD_ID explicitamente ou confirme se o usuário autorizou este site Jira."
        )
        raise RuntimeError(msg)

    if len(resources) == 1:
        return str(resources[0]["id"])

    msg = (
        "O token OAuth acessa mais de um site Atlassian. Defina JIRA_CLOUD_ID ou JIRA_SERVER_URL "
        "para selecionar o Jira correto."
    )
    raise RuntimeError(msg)


def _jira_oauth2_accessible_resources_for_diagnostics() -> dict[str, Any]:
    import requests

    try:
        access_token = _jira_oauth2_access_token()
        response = requests.get(
            "https://api.atlassian.com/oauth/token/accessible-resources",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        resources = response.json()
        if not isinstance(resources, list):
            resources = []

        configured_cloud_id = getenv("JIRA_CLOUD_ID", "")
        configured_server_url = _normalized_url(getenv("JIRA_SERVER_URL"))
        return {
            "ok": True,
            "count": len(resources),
            "configured_cloud_id_found": any(resource.get("id") == configured_cloud_id for resource in resources),
            "configured_server_url_found": any(
                _normalized_url(resource.get("url")) == configured_server_url for resource in resources
            ),
            "resources": [
                {
                    "id": resource.get("id"),
                    "url": resource.get("url"),
                    "name": resource.get("name"),
                }
                for resource in resources
            ],
        }
    except Exception as exc:
        return json.loads(_jira_error_payload(exc, "oauth2_accessible_resources"))


def _jira_client() -> Any:
    from jira import JIRA

    auth_type = _jira_auth_type()
    if auth_type == "oauth2":
        access_token = _jira_oauth2_access_token()
        cloud_id = getenv("JIRA_CLOUD_ID") or _lookup_jira_cloud_id(access_token)
        jira = JIRA(
            server=f"{JIRA_OAUTH2_API_BASE}/{cloud_id}",
            token_auth=access_token,
            rest_api_version=JIRA_REST_API_VERSION,
            max_retries=3,
        )
    elif auth_type == "oauth1":
        oauth_dict = {
            "access_token": getenv("JIRA_OAUTH_ACCESS_TOKEN", ""),
            "access_token_secret": getenv("JIRA_OAUTH_ACCESS_TOKEN_SECRET", ""),
            "consumer_key": getenv("JIRA_OAUTH_CONSUMER_KEY", ""),
            "key_cert": _jira_oauth_key_cert(),
        }
        jira = JIRA(server=getenv("JIRA_SERVER_URL"), oauth=oauth_dict, max_retries=3)
    elif auth_type == "basic":
        username = getenv("JIRA_USERNAME", "")
        secret = getenv("JIRA_TOKEN") or getenv("JIRA_PASSWORD", "")
        jira = JIRA(server=getenv("JIRA_SERVER_URL"), basic_auth=(username, secret), max_retries=3)
    else:
        msg = "JIRA_AUTH_TYPE deve ser 'basic', 'oauth2' ou 'oauth1'."
        raise RuntimeError(msg)

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


def _jira_error_payload(error: Exception, operation: str) -> str:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    message = getattr(error, "text", None) or str(error)
    if response is not None:
        try:
            response_payload = response.json()
            message = response_payload.get("message") or response_payload.get("error_description") or message
            if response_payload.get("errorMessages"):
                message = "; ".join(str(item) for item in response_payload["errorMessages"])
        except ValueError:
            if getattr(response, "text", None):
                message = response.text
    if _jira_auth_type() == "oauth2":
        suggestion = (
            "Verifique se JIRA_OAUTH_ACCESS_TOKEN ainda é válido ou se JIRA_OAUTH_CLIENT_ID/"
            "JIRA_OAUTH_CLIENT_SECRET conseguem emitir token, se JIRA_CLOUD_ID aponta para o site correto "
            "e se o OAuth possui escopos/permissões para acessar esse chamado/projeto."
        )
        if (getattr(error, "status_code", None) or getattr(response, "status_code", None)) == 404:
            suggestion = (
                "HTTP 404 em OAuth 2 normalmente indica JIRA_CLOUD_ID incorreto, JIRA_CLOUD_ID preenchido "
                "com a URL em vez do UUID/cloudId, ou chamado/projeto não acessível para essa credencial."
            )
    elif _jira_auth_type() == "oauth1":
        suggestion = (
            "Verifique access token, access token secret, consumer key, chave privada OAuth e permissões "
            "da conta autorizada no Jira."
        )
    else:
        suggestion = (
            "Verifique se JIRA_USERNAME é o e-mail da conta Atlassian, se JIRA_TOKEN "
            "é um API token válido dessa mesma conta e se a conta tem permissão para ver o chamado/projeto."
        )
    if "consultas JQL ilimitadas" in message or "unrestricted jql" in message.lower():
        suggestion = (
            "A autenticação funcionou, mas o Jira recusou uma JQL sem restrição. "
            "Use um filtro como 'project = TI', 'updated >= -30d', "
            "'assignee = currentUser()' ou 'reporter = currentUser()'."
        )
    payload = {
        "ok": False,
        "operation": operation,
        "status_code": getattr(error, "status_code", None) or getattr(response, "status_code", None),
        "url": getattr(error, "url", None) or getattr(response, "url", None),
        "message": message,
        "login_reason": headers.get("X-Seraph-Loginreason"),
        "atl_request_id": headers.get("Atl-Request-Id"),
        "suggestion": suggestion,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


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


def _jira_comment_recipient(issue_key: str) -> str:
    try:
        if _jira_auth_type() == "oauth2":
            issue = _jira_oauth2_request("GET", f"/issue/{quote(issue_key)}", params={"fields": "reporter"})
            reporter = _jira_rest_user_summary(issue.get("fields", {}).get("reporter"))
        else:
            issue = _jira_client().issue(issue_key)
            reporter = _jira_user_summary(getattr(issue.fields, "reporter", None))
    except Exception:
        reporter = None

    if not reporter:
        return ""
    return reporter.get("display_name") or reporter.get("email") or reporter.get("name") or ""


def _format_jira_ai_comment(comment_pt_br: str, issue_key: str) -> str:
    body = comment_pt_br.strip()
    recipient = _jira_comment_recipient(issue_key)
    greeting = f"Olá @{recipient}!" if recipient else "Olá!"
    return f"{greeting}\n\n{body}\n\n{JIRA_AI_COMMENT_FOOTER}"


def _is_jira_ai_comment(body: str) -> bool:
    return (
        JIRA_AI_COMMENT_MARKER in body
        or JIRA_AI_COMMENT_FOOTER in body
        or JIRA_LEGACY_AI_COMMENT_FOOTER in body
    )


def _explicitly_requested(value: str, user_request_quote: str) -> bool:
    return value.strip().lower() in user_request_quote.strip().lower()


def _jira_estimate_for_api(original_estimate: str) -> str:
    normalized = original_estimate.strip().lower()
    replacements = (
        (" minutos", "m"),
        (" minuto", "m"),
        (" min", "m"),
        (" horas", "h"),
        (" hora", "h"),
        (" dias", "d"),
        (" dia", "d"),
    )
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    return normalized.replace(" ", "")


def _jira_user_summary(user: Any) -> dict[str, Any] | None:
    if user is None:
        return None
    if isinstance(user, dict):
        return _jira_rest_user_summary(user)
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


def _jira_rest_user_summary(user: dict[str, Any] | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "account_id": user.get("accountId"),
        "display_name": user.get("displayName"),
        "email": user.get("emailAddress"),
        "name": user.get("name"),
        "key": user.get("key"),
    }


def _jira_rest_issue_summary(issue: dict[str, Any], include_description: bool = False) -> dict[str, Any]:
    fields = issue.get("fields", {})
    payload = {
        "key": issue.get("key"),
        "summary": fields.get("summary"),
        "status": (fields.get("status") or {}).get("name"),
        "issue_type": (fields.get("issuetype") or {}).get("name"),
        "priority": (fields.get("priority") or {}).get("name"),
        "assignee": _jira_rest_user_summary(fields.get("assignee")),
        "reporter": _jira_rest_user_summary(fields.get("reporter")),
        "created": fields.get("created"),
        "updated": fields.get("updated"),
    }
    if include_description:
        payload["description"] = _text_from_adf(fields.get("description"))
    return payload


def _looks_like_account_id(value: str) -> bool:
    normalized = value.strip()
    return ":" in normalized or (_valid_uuid(normalized) and "@" not in normalized)


def _jira_oauth2_assignable_users(issue_key: str, assignee: str) -> list[dict[str, Any]]:
    params = {"issueKey": issue_key, "maxResults": 10}
    if _looks_like_account_id(assignee):
        params["accountId"] = assignee
    else:
        params["query"] = assignee

    users = _jira_oauth2_request("GET", "/user/assignable/search", params=params)
    if not isinstance(users, list):
        return []
    return users


def _jira_oauth2_resolve_assignee(issue_key: str, assignee: str) -> dict[str, Any]:
    users = _jira_oauth2_assignable_users(issue_key, assignee)
    if not users:
        return {
            "ok": False,
            "reason": "assignee_not_found",
            "message": (
                f"Nenhum usuário atribuível ao chamado {issue_key} foi encontrado para '{assignee}'. "
                "Nenhuma alteração foi feita no Jira."
            ),
            "candidates": [],
        }

    normalized = assignee.strip().lower()
    exact_matches = [
        user
        for user in users
        if normalized
        in {
            str(user.get("accountId", "")).strip().lower(),
            str(user.get("emailAddress", "")).strip().lower(),
            str(user.get("displayName", "")).strip().lower(),
        }
    ]
    if len(exact_matches) == 1:
        return {"ok": True, "user": exact_matches[0]}
    if len(users) == 1:
        return {"ok": True, "user": users[0]}

    return {
        "ok": False,
        "reason": "ambiguous_assignee",
        "message": (
            f"Mais de um usuário atribuível foi encontrado para '{assignee}'. "
            "Informe o nome completo, e-mail ou accountId. Nenhuma alteração foi feita no Jira."
        ),
        "candidates": [_jira_rest_user_summary(user) for user in users],
    }


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
    try:
        if _jira_auth_type() == "oauth2":
            safe_limit = max(1, min(max_results, 25))
            payload = _jira_oauth2_request(
                "GET",
                "/search/jql",
                params={
                    "jql": jql,
                    "maxResults": safe_limit,
                    "fields": "summary,status,issuetype,priority,assignee,reporter,created,updated",
                },
            )
            issues = payload.get("issues", [])
            return json.dumps(
                {"ok": True, "issues": [_jira_rest_issue_summary(issue) for issue in issues]},
                ensure_ascii=False,
                default=str,
            )

        jira = _jira_client()
        safe_limit = max(1, min(max_results, 25))
        issues = jira.search_issues(jql, maxResults=safe_limit)
        payload = {"ok": True, "issues": [_jira_issue_summary(issue) for issue in issues]}
        return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as exc:
        return _jira_error_payload(exc, "search_jira_issues")


def get_jira_issue(issue_key: str) -> str:
    """Obtém detalhes de um chamado Jira e retorna JSON.

    Use esta ferramenta para ler o chamado antes de responder ou executar uma
    ação guardada. Não altera nenhum conteúdo do Jira.
    """
    try:
        if _jira_auth_type() == "oauth2":
            fields = "summary,status,issuetype,priority,assignee,reporter,created,updated,description"
            issue = _jira_oauth2_request("GET", f"/issue/{quote(issue_key)}", params={"fields": fields})
            payload = {"ok": True, "issue": _jira_rest_issue_summary(issue, include_description=True)}
        else:
            jira = _jira_client()
            issue = jira.issue(issue_key)
            payload = {"ok": True, "issue": _jira_issue_summary(issue, include_description=True)}
    except Exception as exc:
        return _jira_error_payload(exc, "get_jira_issue")

    try:
        if _jira_auth_type() == "oauth2":
            comments_payload = _jira_oauth2_request(
                "GET",
                f"/issue/{quote(issue_key)}/comment",
                params={"maxResults": 5, "orderBy": "-created"},
            )
            comments = comments_payload.get("comments", [])
            payload["issue"]["comments"] = [
                {
                    "id": comment.get("id"),
                    "author": _jira_rest_user_summary(comment.get("author")),
                    "created": comment.get("created"),
                    "updated": comment.get("updated"),
                    "body": _text_from_adf(comment.get("body")),
                }
                for comment in comments
            ]
            return json.dumps(payload, ensure_ascii=False, default=str)

        comments = jira.comments(issue_key)
    except Exception:
        comments = []

    payload["issue"]["comments"] = [
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
    português do Brasil. A ferramenta adiciona saudação mencionando o reporter
    do chamado, quando disponível, e aviso final de IA em destaque.
    """
    try:
        formatted_comment = _format_jira_ai_comment(comment_pt_br, issue_key)
        if _jira_auth_type() == "oauth2":
            created_comment = _jira_oauth2_request(
                "POST",
                f"/issue/{quote(issue_key)}/comment",
                json={"body": formatted_comment},
                headers={"Content-Type": "application/json"},
            )
            comment_id = created_comment.get("id", "unknown")
        else:
            jira = _jira_client()
            created_comment = jira.add_comment(issue_key, formatted_comment)
            comment_id = getattr(created_comment, "id", "unknown")
        return f"Comentário {comment_id} adicionado ao chamado {issue_key}."
    except Exception as exc:
        return _jira_error_payload(exc, "comment_jira_issue")


def edit_jira_ai_comment(issue_key: str, comment_id: str, comment_pt_br: str) -> str:
    """Edita um comentário Jira somente quando ele foi criado por esta ferramenta de IA.

    Recusa editar comentários sem o rodapé desta ferramenta ou que não foram
    criados por JIRA_USERNAME. Também reconhece comentários legados com o
    marcador antigo. Nunca use para deletar conteúdo. O novo texto deve estar
    em português do Brasil; a ferramenta adiciona novamente a saudação e o
    aviso de IA.
    """
    try:
        if _jira_auth_type() == "oauth2":
            comment = _jira_oauth2_request("GET", f"/issue/{quote(issue_key)}/comment/{quote(comment_id)}")
            existing_body = _text_from_adf(comment.get("body")) or ""

            if not _is_jira_ai_comment(existing_body):
                return (
                    f"Recusado: o comentário {comment_id} no chamado {issue_key} não "
                    "foi criado por esta ferramenta de IA. Nenhuma alteração foi feita no Jira."
                )

            updated_comment = _jira_oauth2_request(
                "PUT",
                f"/issue/{quote(issue_key)}/comment/{quote(comment_id)}",
                json={"body": _format_jira_ai_comment(comment_pt_br, issue_key)},
                headers={"Content-Type": "application/json"},
            )
            updated_id = updated_comment.get("id", comment_id)
            return f"Comentário {updated_id} do chamado {issue_key} atualizado."

        jira = _jira_client()
        comment = jira.comment(issue_key, comment_id)
        existing_body = getattr(comment, "body", "")
        author = getattr(comment, "author", None)

        if not _is_jira_ai_comment(existing_body):
            return (
                f"Recusado: o comentário {comment_id} no chamado {issue_key} não "
                "foi criado por esta ferramenta de IA. Nenhuma alteração foi feita no Jira."
            )

        if not _jira_user_matches(author, getenv("JIRA_USERNAME", "")):
            return (
                f"Recusado: o comentário {comment_id} no chamado {issue_key} não "
                "foi criado por JIRA_USERNAME. Nenhuma alteração foi feita no Jira."
            )

        comment.update(body=_format_jira_ai_comment(comment_pt_br, issue_key))
        return f"Comentário {comment_id} do chamado {issue_key} atualizado."
    except Exception as exc:
        return _jira_error_payload(exc, "edit_jira_ai_comment")


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

    try:
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
    except Exception as exc:
        return _jira_error_payload(exc, "transition_jira_issue")


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

    try:
        estimate_for_api = _jira_estimate_for_api(original_estimate)
        if _jira_auth_type() == "oauth2":
            _jira_oauth2_request(
                "PUT",
                f"/issue/{quote(issue_key)}",
                json={"fields": {"timetracking": {"originalEstimate": estimate_for_api}}},
                headers={"Content-Type": "application/json"},
            )
            return f"Tempo previsto de {issue_key} definido como '{original_estimate}'."

        jira = _jira_client()
        issue = jira.issue(issue_key)
        issue.update(fields={"timetracking": {"originalEstimate": estimate_for_api}})
        return f"Tempo previsto de {issue_key} definido como '{original_estimate}'."
    except Exception as exc:
        return _jira_error_payload(exc, "set_jira_issue_original_estimate")


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

    try:
        if _jira_auth_type() == "oauth2":
            resolved = _jira_oauth2_resolve_assignee(issue_key, assignee)
            if not resolved["ok"]:
                return json.dumps(resolved, ensure_ascii=False, default=str)

            user = resolved["user"]
            _jira_oauth2_request(
                "PUT",
                f"/issue/{quote(issue_key)}/assignee",
                json={"accountId": user["accountId"]},
                headers={"Content-Type": "application/json"},
            )
            display_name = user.get("displayName") or assignee
            return f"Chamado {issue_key} atribuído para '{display_name}'."

        jira = _jira_client()
        jira.assign_issue(issue_key, assignee)
        return f"Chamado {issue_key} atribuído para '{assignee}'."
    except Exception as exc:
        return _jira_error_payload(exc, "assign_jira_issue")


def get_jira_tools() -> list[Any]:
    """Expose Jira tools when credentials are configured.

    Uses custom read tools instead of Agno's native JiraTools so every Jira
    operation goes through the same guarded client setup.
    """
    tools: list[Any] = [
        check_jira_configuration,
        diagnose_jira_connection,
    ]
    if not jira_credentials_configured():
        return tools

    tools.extend(
        [
            test_jira_connection,
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
