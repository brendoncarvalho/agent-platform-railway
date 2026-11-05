# Pemill AgentOS — guia para agentes de código

Este arquivo é a fonte de verdade para qualquer agente de código (Claude Code, Codex, outros) trabalhando neste
repositório. `CLAUDE.md` aponta para este arquivo.

## Visão geral

Plataforma de agentes de IA da Pemill sobre o [Agno](https://docs.agno.com) **3.1.12** (AgentOS). Um backend
FastAPI (`app/main.py`) expõe os agentes como REST, chat (AgentOS UI, Slack, Rocket.Chat) e MCP (`/mcp`).
Postgres + pgvector guardam sessões, memória e conhecimento. O repositório nasceu do template `agentos-railway`
da Agno; os agentes de exemplo do template foram removidos — restam apenas os agentes da Pemill.

## Arquitetura

```
AgentOS (app/main.py)
├── Assistente Pemill   (agents/assistente_pemill.py) — conversa geral pt-BR, visão, geração/edição de imagens,
│                        memória de usuário (LearningMachine), histórico por sessão; agente padrão do Slack
├── Revisor de textos   (agents/crm_note_autofix.py)  — revisão de registros comerciais
├── Atendimento Jira    (agents/jira_ticket_responder.py) — ferramentas Jira guardadas (app/jira_tools.py)
├── Analista de Currículos (agents/hr_resume_analyst.py) — triagem de currículos (app/hr_resume_tools.py)
└── Time TI (team)      (agents/ti_team.py) — coordena Atendimento Jira + Assistente Pemill, gera arquivos
```

Compartilhado:
- `app/settings.py` — helpers de env (`env_flag`, `env_int`, `env_list`), fábricas de modelo
  (`default_model()` OpenRouter; `chat_model()` por provedor via `CHAT_MODEL_PROVIDER`/`CHAT_MODEL_ID`),
  `image_settings()` e `media_storage_settings()`.
- `app/media_storage.py` — `get_media_storage()` (agno `LocalMediaStorage` ou `S3MediaStorage`, env `MEDIA_STORAGE`).
  Passado ao `AgentOS(media_storage=...)` e aos agentes que lidam com mídia; o agno descarrega imagens de
  entrada/saída para lá ao fim do run e a rota `/sessions/{id}/media/{key}` as serve à UI.
- `app/image_input.py` — `ImageInputGuardrail` (pre_hook): valida formato (magic bytes) e tamanho das imagens
  recebidas (upload, URL, data URL, base64). URLs remotas são baixadas uma vez e viram bytes.
- `app/image_generation.py` — `ImageGenerationTools` (`generate_image`, `edit_image`) com backends OpenRouter
  (Image API `POST /images`, padrão; gera e edita via imagem de referência), OpenAI (gpt-image/dall-e; gera e
  edita) e Gemini/Imagen (só gera). Salva no media storage sob
  `pemill-img-<id>.<ext>`, devolve `Image` com `media_reference` e guarda o último id em
  `run_context.session_state["pemill_last_image_id"]` para edições na mesma sessão.
- `app/registry.py` — registro do Studio (ferramentas Jira, ReasoningTools em pt-BR, modelos, DB, agentes).
- `app/config.yaml` — manifesto da UI (descrição + quick prompts) por `id` de componente.
- `db/` — `get_postgres_db()` (memoizado) e `create_knowledge()` (PgVector híbrido).
- JWT ligado sempre que `RUNTIME_ENV != dev`; MCP server ligado; OAuth do MCP quando `MCP_CONNECT_SECRET` existe;
  scheduler ligado (sem schedules registrados por código — crie pela UI/API se precisar).

## Arquivos-chave

| Arquivo | Função |
|---|---|
| `app/main.py` | Entrypoint do AgentOS: Slack condicional, Rocket.Chat condicional, OAuth MCP, media storage, registro dos agentes. |
| `app/settings.py` | Env helpers, fábricas de modelo, configurações de imagem e storage. |
| `app/image_input.py` / `app/image_generation.py` / `app/media_storage.py` | Pipeline de imagens do Assistente Pemill. |
| `app/web_search.py` | Pesquisa na web e de notícias (`WebSearchTools` do agno sobre `ddgs`, sem chave): teto de resultados, segunda tentativa em `auto` e falha devolvida como texto. |
| `app/url_guard.py` | Só deixa passar URLs http(s) públicas: recusa localhost, IPs privados, nomes de container e metadados de nuvem (SSRF). Usado pelo leitor e pelo navegador. |
| `app/web_reader.py` | `read_web_page`: baixa uma URL (cada redirecionamento passa pelo `url_guard`) e extrai o texto com `trafilatura`. Sem JavaScript. |
| `app/web_browser.py` | Ferramentas `browser_*` sobre Playwright/Chromium: um Chromium por processo, um contexto por sessão de chat, em thread própria; fecha sozinho quando ocioso. Sem senhas nem downloads. |
| `app/browser_live.py` | Rotas `/browser/sessions/{session_id}` (estado, `/frame` em JPEG, `/input`) para o usuário ver e operar o navegador do agente no portal. Só o dono da sessão de chat (`user_id`) é atendido. É assim que login, código de verificação e CAPTCHA são feitos pela pessoa. |
| `app/guarded_proxy.py` | Proxy local pelo qual todo o tráfego do Chromium sai; só conecta em endereços aprovados pelo `url_guard` (cobre redirecionamentos, imagens, XHR e WebSocket). |
| `app/media_samples.py` | Geradores de PNG/JPEG/WEBP/GIF mínimos para testes e evals (sem Pillow). |
| `agents/assistente_pemill.py` | Agente de conversa geral multimodal. Modelo de referência para novos agentes. |
| `app/jira_tools.py`, `app/hr_resume_tools.py`, `app/resume_text.py` | Ferramentas dos agentes Jira e RH. |
| `app/rocketchat.py` | Webhook de saída do Rocket.Chat (`ROCKETCHAT_AGENT_ID`). |
| `evals/cases.py` | Casos de avaliação (`python -m evals`). |
| `tests/` | pytest: unitários (sem modelo) + `test_live.py` (opcional, `PEMILL_LIVE_TESTS=1`). |
| `example.env` | Todas as variáveis com defaults. |
| `compose.yaml` / `compose.coolify.yaml` / `Dockerfile` | Dev local / produção (Coolify) / imagem. |
| `scripts/` | `venv_setup.sh`, `format.sh`, `validate.sh`, `generate_requirements.sh`, `railway/*`. |
| `.agents/skills/` | Skills de dev para agentes de código (`create-agent`, `extend-agent`, `improve-agent`, `create-evals`, `eval-and-improve`, `review-and-improve`, `setup-platform`, `deploy-platform`). Alguns exemplos nelas ainda citam agentes do template. |

## Setup de desenvolvimento

```bash
cp example.env .env            # OPENAI_API_KEY + OPENROUTER_API_KEY
docker compose up -d --build   # API em :8000, RUNTIME_ENV=dev (sem JWT), hot-reload
```

Host (format/validate/tests/evals):

```bash
./scripts/venv_setup.sh && source .venv/bin/activate
./scripts/format.sh && ./scripts/validate.sh && python -m pytest
```

`requirements.txt` é o lockfile (gerado por `./scripts/generate_requirements.sh` a partir de `pyproject.toml`);
CI instala o mesmo pin e roda `ruff format --check` + `scripts/validate.sh`.

## Convenções

### Padrão de agente

```python
"""
<Título>
========
"""

from agno.agent import Agent

from app.settings import chat_model  # ou default_model
from db import get_postgres_db

INSTRUCTIONS = """\
<quem é o agente, o que faz, regras de resposta — em pt-BR>
"""

meu_agente = Agent(
    id="meu-agente",          # kebab-case; é a chave em app/config.yaml e na URL /agents/{id}
    name="Meu Agente",
    model=chat_model(),
    db=get_postgres_db(),
    tools=[...],
    instructions=INSTRUCTIONS,
    markdown=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=10,
)
```

- Um arquivo por agente em `agents/`; ferramentas e configurações reutilizáveis em `app/`.
- Configuração por variáveis de ambiente lidas em `app/settings.py`; defaults documentados em `example.env`,
  repassados em `compose.coolify.yaml` e na tabela do `README.md`. Nunca chaves no código.
- Agentes que recebem ou produzem imagens recebem `media_storage=get_media_storage()` e, se recebem imagens
  do usuário, `pre_hooks=[ImageInputGuardrail()]`.
- Memória de usuário: `learning=LearningMachine(db=..., user_profile=..., user_memory=...)`, idealmente atrás
  de uma flag de env (ver `ASSISTENTE_PEMILL_MEMORY`).
- Mensagens ao usuário em pt-BR, inclusive erros de validação.

### Banco

```python
from db import get_postgres_db, create_knowledge
agent_db = get_postgres_db()
my_kb = create_knowledge("Minha Base", "minha_tabela")  # PgVector híbrido, text-embedding-3-small
```

## Adicionando um novo agente

1. `agents/<slug>.py` com o padrão acima.
2. Registrar em `app/main.py` (`agents=[...]`) e, opcionalmente, em `app/registry.py`.
3. Entrada em `app/config.yaml` (descrição + quick prompts).
4. Env novas em `example.env` + `compose.coolify.yaml` + tabela do README.
5. Teste de wiring em `tests/` e, se fizer sentido, `Case` em `evals/cases.py`.
6. `./scripts/format.sh && ./scripts/validate.sh && python -m pytest`.

A skill `/create-agent` guia esses passos; `/extend-agent` e `/improve-agent` iteram sobre um agente existente.

## Testes e evals

- `python -m pytest` — unitários, sem rede: guardrail de imagens, toolkit de geração (backend falso + storage
  local), wiring do Assistente Pemill e do AgentOS, fábricas de configuração.
- `PEMILL_LIVE_TESTS=1 python -m pytest tests/test_live.py` — conversa, análise de imagem e geração reais
  (precisa de chaves e Postgres).
- `python -m evals --tag smoke|release` — juiz LLM (`AgentAsJudgeEval`) e `ReliabilityEval`; resultados no Postgres
  (`eval_db`) e em os.agno.com. Casos que tocam agentes com memória usam `setup=snapshot_learning_state` /
  `teardown=cleanup_new_learning_state` para limpar perfis/memórias criados pelo caso.

## Variáveis de ambiente

Tabela completa em `README.md`; defaults em `example.env`. Resumo das que afetam o Assistente Pemill:
`CHAT_MODEL_PROVIDER`, `CHAT_MODEL_ID`, `ASSISTENTE_PEMILL_MEMORY`, `ASSISTENTE_PEMILL_HISTORY_RUNS`,
`ASSISTENTE_PEMILL_MAX_TOKENS`, `WEB_SEARCH`, `WEB_SEARCH_BACKEND`, `WEB_SEARCH_REGION`, `WEB_READER`, `BROWSER`,
`BROWSER_MAX_SESSIONS`, `BROWSER_IDLE_SECONDS`, `BROWSER_MAX_STEPS`, `IMAGE_PROVIDER`, `IMAGE_MODEL`,
`IMAGE_SIZE`, `IMAGE_QUALITY`, `IMAGE_API_KEY`,
`IMAGE_INPUT_MAX_MB`, `IMAGE_INPUT_FORMATS`, `MEDIA_STORAGE`, `MEDIA_STORAGE_DIR`, `MEDIA_S3_*`.

## Interfaces

- **AgentOS UI:** os.agno.com → Connect OS (local `http://localhost:8000`, ou Live com JWT).
- **MCP:** `/mcp` (ferramentas `run_agent`, `run_team`); `uvx agno connect` registra nos clientes locais;
  claude.ai/ChatGPT usam OAuth com `MCP_CONNECT_SECRET`.
- **Slack:** `SLACK_BOT_TOKEN` + `SLACK_SIGNING_SECRET` → Assistente Pemill.
- **Rocket.Chat:** `ROCKETCHAT_WEBHOOK_TOKEN` → `/rocketchat/webhook`; `ROCKETCHAT_AGENT_ID` em
  `assistente-pemill` (padrão), `jira-ticket-responder` ou `ti-team`.

## Deploy

- Coolify: `compose.coolify.yaml` (JWT em `prd`, volume `media` para `MEDIA_STORAGE=local`).
- Railway: `scripts/railway/up.sh` (pede `JWT_VERIFICATION_KEY`), `env-sync.sh`, `redeploy.sh`, `down.sh`.
- Imagens geradas em produção: prefira `MEDIA_STORAGE=s3` (precisa de `boto3`) ou garanta volume persistente.

## Tarefas comuns

```bash
# Adicionar dependência: editar pyproject.toml e regenerar o lock
./scripts/generate_requirements.sh && uv pip sync requirements.txt

# Subir agno: trocar o pin em pyproject.toml, regenerar requirements, rodar testes
./scripts/generate_requirements.sh agno && uv pip sync requirements.txt && python -m pytest
```

## Links

- [Agno docs](https://docs.agno.com) · [AgentOS](https://docs.agno.com/agent-os/introduction) ·
  [Media storage](https://docs.agno.com/agent-os/media-storage) · [Guardrails](https://docs.agno.com/guardrails)
