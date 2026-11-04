# Pemill AgentOS

Plataforma de agentes de IA da Pemill, construída sobre o [Agno](https://docs.agno.com) (AgentOS 3.1.x).
Um backend FastAPI expõe os agentes como **API REST**, **interface de chat** (AgentOS UI, Slack, Rocket.Chat)
e **MCP** (`/mcp`) para apps de IA como claude.ai, ChatGPT, Cursor e Claude Code. Postgres (pgvector) guarda
sessões, memória de usuário e conhecimento.

## Agentes

| Agente | id | O que faz |
|---|---|---|
| **Assistente Pemill** | `assistente-pemill` | Conversa geral em pt-BR, analisa imagens enviadas (PNG/JPEG/WEBP) e gera/edita imagens sob demanda. Histórico por sessão e memória de usuário no Postgres. |
| Revisor de textos | `crm-note-autofix` | Revisa registros comerciais de ligações e visitas, mantendo o sentido. |
| Atendimento Jira | `jira-ticket-responder` | Lê e comenta chamados Jira com ferramentas guardadas (`JIRA_*`). |
| Analista de Currículos | `hr-resume-analyst` | Apoio à triagem de currículos (PDF/DOCX/texto) para o RH. |
| Time TI (team) | `ti-team` | Coordena Atendimento Jira + Assistente Pemill e gera arquivos. |

## Como rodar

### Com Docker (recomendado)

```bash
cp example.env .env
# edite .env: OPENAI_API_KEY e OPENROUTER_API_KEY são obrigatórios
docker compose up -d --build
```

- API em `http://localhost:8000` (docs em `/docs`, saúde em `/health`).
- `compose.yaml` roda em modo `dev` (sem JWT), com hot-reload de `agents/`, `app/`, `db/` e `evals/`.
- Imagens enviadas/geradas ficam em `storage/media` (montado do repositório).

Para conversar pela interface, abra [os.agno.com](https://os.agno.com), **Connect OS → Local** e aponte para
`http://localhost:8000`. O Assistente Pemill aparece com os quick prompts definidos em `app/config.yaml`.

### Sem Docker (venv)

Requer Python 3.12+ e [uv](https://docs.astral.sh/uv/), além de um Postgres acessível (variáveis `DB_*`).

```bash
./scripts/venv_setup.sh && source .venv/bin/activate   # Windows: .venv\Scripts\activate
cp example.env .env
RUNTIME_ENV=dev uvicorn app.main:app --reload --port 8000
```

### Qualidade

```bash
./scripts/format.sh      # ruff format + import sort
./scripts/validate.sh    # ruff check + mypy
python -m pytest         # testes unitários (sem chamadas a modelos)
```

## Testar o Assistente Pemill localmente

Pela UI (os.agno.com conectado ao OS local) ou pela API. Com `RUNTIME_ENV=dev` não há JWT:

```bash
# Conversa (streaming SSE; use stream=false para JSON único)
curl -s -X POST http://localhost:8000/agents/assistente-pemill/runs \
  -F "message=Olá! Quem é você e como pode me ajudar?" -F "stream=false" \
  -F "user_id=ti@pemill.com.br" -F "session_id=teste-1"
```

```bash
# Análise de imagem (upload PNG/JPEG/WEBP até IMAGE_INPUT_MAX_MB)
curl -s -X POST http://localhost:8000/agents/assistente-pemill/runs \
  -F "message=Descreva esta imagem" -F "stream=false" -F "session_id=teste-1" \
  -F "files=@/caminho/para/foto.jpg"
```

```bash
# Geração e, na mesma sessão, edição da última imagem gerada
curl -s -X POST http://localhost:8000/agents/assistente-pemill/runs \
  -F "message=Gere uma imagem de um caminhão azul em estilo flat" -F "stream=false" -F "session_id=teste-1"
curl -s -X POST http://localhost:8000/agents/assistente-pemill/runs \
  -F "message=Deixe o fundo amarelo" -F "stream=false" -F "session_id=teste-1"
```

A resposta traz `images[]` com uma `media_reference`; a UI exibe a imagem e a API serve os bytes em
`GET /sessions/{session_id}/media/{storage_key}`. Imagens em formato não permitido ou acima do limite são
recusadas antes de chegar ao modelo, com mensagem em português.

Testes que chamam provedores reais (conversa, análise de imagem e pedido de geração):

```bash
PEMILL_LIVE_TESTS=1 python -m pytest tests/test_live.py -v
```

Evals com juiz LLM (resultados em os.agno.com): `python -m evals --tag smoke` ou `--tag release`.

Verificação ponta a ponta **sem chaves de API** (`tests/e2e_stub/`): um servidor local compatível com a API da
OpenAI responde pelo modelo de chat e pela geração/edição de imagens, e o script percorre conversa, análise de
imagem, geração, edição e persistência no Postgres (exige o banco do `docker compose` rodando):

```bash
python tests/e2e_stub/openai_stub.py 8099 &
```

```bash
RUNTIME_ENV=dev OPENAI_API_KEY=sk-stub OPENAI_BASE_URL=http://127.0.0.1:8099/v1 OPENROUTER_API_KEY=sk-stub CHAT_MODEL_PROVIDER=openai ASSISTENTE_PEMILL_MEMORY=false PYTHONPATH=. python tests/e2e_stub/e2e_check.py
```

## Variáveis de ambiente

Valores padrão documentados em [`example.env`](example.env). Nenhuma chave fica no código.

| Variável | Obrigatória | Padrão | Descrição |
|---|---|---|---|
| `OPENAI_API_KEY` | sim | — | Embeddings e provedor padrão de geração de imagens. |
| `OPENROUTER_API_KEY` | sim | — | Provedor padrão de chat de todos os agentes. |
| `OPENROUTER_MODEL` | não | `~openai/gpt-mini-latest` | Modelo OpenRouter padrão (`app.settings.default_model()`). |
| `CHAT_MODEL_PROVIDER` | não | `openrouter` | Provedor de chat do Assistente Pemill: `openrouter`, `openai`, `google`, `anthropic`. Precisa aceitar imagens. |
| `CHAT_MODEL_ID` | não | por provedor | Modelo de chat do Assistente Pemill (ver `example.env`). |
| `ASSISTENTE_PEMILL_MEMORY` | não | `True` | Memória de usuário entre sessões (LearningMachine). |
| `ASSISTENTE_PEMILL_HISTORY_RUNS` | não | `10` | Interações anteriores incluídas no contexto. |
| `ASSISTENTE_PEMILL_MAX_TOKENS` | não | `4096` | Teto de tokens de saída. |
| `IMAGE_PROVIDER` | não | `openai` | `openai` (geração + edição) ou `gemini` (só geração; requer `google-genai`). |
| `IMAGE_MODEL` | não | `gpt-image-1` / `imagen-4.0-generate-001` | Modelo de imagem do provedor. |
| `IMAGE_SIZE` / `IMAGE_QUALITY` | não | `1024x1024` / `auto` | Parâmetros de geração. |
| `IMAGE_API_KEY` | não | — | Chave dedicada para imagens; senão usa `OPENAI_API_KEY` / `GOOGLE_API_KEY`. |
| `IMAGE_INPUT_MAX_MB` | não | `10` | Tamanho máximo de imagem enviada pelo usuário. |
| `IMAGE_INPUT_FORMATS` | não | `png,jpeg,webp` | Formatos aceitos na entrada. |
| `MEDIA_STORAGE` | não | `local` | `local` ou `s3` (requer `boto3`). Onde ficam imagens enviadas e geradas. |
| `MEDIA_STORAGE_DIR` | não | `storage/media` | Pasta do storage local (compose monta um volume). |
| `MEDIA_S3_BUCKET` / `MEDIA_S3_PREFIX` / `MEDIA_S3_REGION` / `MEDIA_S3_ENDPOINT_URL` | se `s3` | — | Bucket S3 compatível; credenciais via `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`. |
| `RUNTIME_ENV` | não | `prd` | `dev` desliga o JWT. O compose local define `dev`; nunca envie para produção. |
| `JWT_VERIFICATION_KEY` / `JWT_JWKS_FILE` | prd | — | Chave pública gerada em os.agno.com. Obrigatória em produção. |
| `AGENTOS_URL` | não | `http://127.0.0.1:8000` | URL pública do OS (scheduler e OAuth do MCP). |
| `MCP_CONNECT_SECRET` / `AGENTOS_MCP_SIGNING_KEY` | não | — | Liga o OAuth 2.1 do `/mcp` para claude.ai e ChatGPT. |
| `JIRA_*` | não | — | Credenciais do Jira (basic, oauth2 ou oauth1); `JIRA_ENABLE_MUTATIONS` libera mutações guardadas. |
| `ROCKETCHAT_WEBHOOK_TOKEN` / `ROCKETCHAT_AGENT_ID` / `ROCKETCHAT_BOT_USERNAME` | não | `assistente-pemill` | Webhook de saída do Rocket.Chat em `/rocketchat/webhook`. Opções de agente: `assistente-pemill`, `jira-ticket-responder`, `ti-team`. |
| `SLACK_BOT_TOKEN` / `SLACK_SIGNING_SECRET` | não | — | Ambas ligam a interface Slack (Assistente Pemill responde). |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASS` / `DB_DATABASE` / `DB_DRIVER` | não | compose | Conexão Postgres. |
| `AGNO_DEBUG` / `WAIT_FOR_DB` | não | `False` | Logs verbosos do Agno / entrypoint espera o banco. |

## Como adicionar um novo agente

1. Crie `agents/<slug>.py` seguindo o padrão do [`agents/assistente_pemill.py`](agents/assistente_pemill.py):
   `INSTRUCTIONS` em pt-BR, `model=chat_model()` (ou `default_model()`), `db=get_postgres_db()`,
   `add_history_to_context=True`, `markdown=True`. Ferramentas e configurações compartilhadas ficam em `app/`
   (`app/settings.py` para env/modelos, `app/image_*.py` para imagens, `app/jira_tools.py` para Jira).
2. Registre o agente em [`app/main.py`](app/main.py) (`AgentOS(agents=[...])`) e, se quiser que apareça no
   Studio como componente reutilizável, em [`app/registry.py`](app/registry.py).
3. Adicione descrição e quick prompts em [`app/config.yaml`](app/config.yaml) (a chave é o `id` do agente).
4. Novas variáveis de ambiente: documente em `example.env`, repasse em `compose.coolify.yaml` e na tabela acima.
5. Cubra com um teste em `tests/` (wiring, sem modelo) e, se fizer sentido, um `Case` em `evals/cases.py`.

Com o hot-reload do compose, o agente aparece na UI assim que o arquivo é salvo. Em uma sessão de Claude Code
neste repositório, a skill `/create-agent` faz esses passos de forma guiada.

## Deploy

- **Coolify / Docker Compose:** [`compose.coolify.yaml`](compose.coolify.yaml) sobe API + Postgres com healthchecks,
  JWT ligado (`RUNTIME_ENV=prd`) e volume `media` para as imagens. Defina as variáveis no painel.
- **Railway:** scripts em [`scripts/railway/`](scripts/railway/) (`up.sh`, `env-sync.sh`, `redeploy.sh`, `down.sh`);
  o `up.sh` pede a `JWT_VERIFICATION_KEY` gerada em os.agno.com (**Connect OS → Live → Token-Based Authorization**).
- **MCP:** `uvx agno connect --url https://<dominio>` registra o OS nos clientes locais; para claude.ai/ChatGPT
  adicione `https://<dominio>/mcp` como conector e informe o `MCP_CONNECT_SECRET` na tela de consentimento.

Em produção o app recusa iniciar sem `JWT_VERIFICATION_KEY` ou `JWT_JWKS_FILE`. Para desligar a autenticação
(não recomendado), ajuste `authorization=False` em `app/main.py`.

## Estrutura

```
agents/        um arquivo por agente (+ ti_team.py)
app/           main.py (AgentOS), settings.py (env/modelos), registry.py, config.yaml,
               image_input.py (validação), image_generation.py (ferramentas), media_storage.py,
               jira_tools.py, hr_resume_tools.py, rocketchat.py
db/            Postgres/pgvector helpers
evals/         casos de avaliação (python -m evals)
tests/         pytest (unitários + live opcionais)
scripts/       venv, format, validate, requirements, railway
```

## Saiba mais

- [Documentação do Agno](https://docs.agno.com) · [AgentOS](https://docs.agno.com/agent-os/introduction)
- [`AGENTS.md`](AGENTS.md) — guia para agentes de código (Claude Code, Codex) trabalhando neste repositório.
