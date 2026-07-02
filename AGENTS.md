# Self-Driving Agent Platform

This file is the source of truth for any agent (Claude Code, Codex, others) working in this repo. `CLAUDE.md` is a symlink to this file — edit one, both update.

## Project Overview

A self-driving agent platform built on [Agno](https://docs.agno.com), shipped as a copy-pasteable starting point. Three reference agents demonstrate web search, codebase search, and UI-driven agent/team/workflow creation. Postgres (pgvector) handles persistence for sessions, memory, and knowledge. Designed to run locally via Docker and deploy to Railway with a single script.

## Architecture

```
AgentOS  (app/main.py)
├── WebSearch    (agents/web_search.py)   — Parallel SDK or keyless MCPTools
├── CodeSearch   (agents/code_search.py)  — WorkspaceContextProvider
├── Agent Builder (agents/agent_builder.py) — Agno docs MCP + StudioTool
├── DeployCheck  (workflows/deployment_check.py) — deterministic readiness workflow
└── EvalRegression (workflows/eval_regression.py) — opt-in eval profile workflow
```

Shared:
- PostgreSQL + pgvector for sessions, memory, knowledge.
- `app.settings.default_model()` returns `OpenAIResponses(id="gpt-5.5")` — bump the model in one place.
- `app.registry.registry` exposes the safe Studio registry Agent Builder can use: Agno docs MCP, web search, read-only code search, reasoning/calculator tools, schemas/functions, the default model, the shared DB, and reference agents.
- Scheduler enabled by default (`scheduler=True`); `app/schedules.py` registers schedules from the lifespan. Deployment check runs daily **on** by default — set `ENABLE_DEPLOY_CHECK=False` to disable it. Eval regression is **off** by default — set `ENABLE_EVAL_REGRESSION=True` to schedule it.
- Slack interface lights up automatically when both `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` are set.
- JWT auth on whenever `RUNTIME_ENV == "prd"` (so production deploys are gated by default).

## Key Files

| File | Purpose |
|------|---------|
| [`app/main.py`](app/main.py) | AgentOS entrypoint — lifespan hook, conditional Slack, JWT gate. |
| [`app/settings.py`](app/settings.py) | `default_model()` factory. |
| [`app/agno_docs.py`](app/agno_docs.py) | Agno docs MCP helper. |
| [`app/registry.py`](app/registry.py) | Safe Studio registry used by Agent Builder. |
| [`app/studio_components.py`](app/studio_components.py) | Lightweight schemas/functions exposed through the Studio registry. |
| [`app/config.yaml`](app/config.yaml) | Quick prompts per agent (keyed by agent `id`). |
| [`agents/web_search.py`](agents/web_search.py) | Reference agent — direct tools (Parallel SDK or MCP). |
| [`agents/code_search.py`](agents/code_search.py) | Reference agent — context provider. |
| [`agents/agent_builder.py`](agents/agent_builder.py) | Reference agent — creates agents, teams, and workflows through StudioTool with HITL gates. |
| [`workflows/deployment_check.py`](workflows/deployment_check.py) | Reference workflow — a deterministic `Step` that checks DB, auth, scheduler URL, Slack config, and component imports; imported into `app/main.py` and passed to `AgentOS(workflows=[...])`. |
| [`workflows/eval_regression.py`](workflows/eval_regression.py) | Optional workflow — runs a bounded eval profile and returns a compact report. Registered but not scheduled unless `ENABLE_EVAL_REGRESSION=True`. |
| [`app/schedules.py`](app/schedules.py) | `register_schedules()` — cron registration, called from the lifespan (idempotent, fail-soft). |
| [`db/session.py`](db/session.py) | `get_postgres_db()`, `create_knowledge()`. |
| [`db/url.py`](db/url.py) | Builds the database URL from env. |
| [`evals/cases.py`](evals/cases.py) | Eval cases (each is a `Case` with optional judge + reliability checks). |
| [`evals/__main__.py`](evals/__main__.py) | `python -m evals` runner — wraps agno's `AgentAsJudgeEval` + `ReliabilityEval`. |
| [`.agents/skills/`](.agents/skills/) | Dev-time **coding-agent workflows** (`create-new-agent`, `extend-agent`, `improve-agent`, `eval-and-improve`, `review-and-improve`) — slash commands coding agents run *on this repo*. `.claude/skills` is a committed symlink into it — see [Working with coding agents](#working-with-coding-agents). |
| [`compose.yaml`](compose.yaml) | Docker Compose for local development. |
| [`railway.json`](railway.json) | Railway deploy config (Docker + 1 replica + 4Gi/2vCPU). |

## Development Setup

### Local with Docker

```bash
cp example.env .env
# Edit .env and set OPENAI_API_KEY

docker compose up -d --build
```

`compose.yaml` sets `RUNTIME_ENV=dev`, `AGNO_DEBUG=True`, and `WAIT_FOR_DB=True` so JWT is off and the API blocks on the DB before serving. Because this template uses MCPTools inside AgentOS, do not run uvicorn with `--reload`; restart `agentos-api` after code changes.

### Format & Validate

The format / validate / eval scripts run on the host, so they need a venv. Set one up once:

```bash
./scripts/venv_setup.sh
source .venv/bin/activate
```

Then:

```bash
./scripts/format.sh     # ruff format + import sort
./scripts/validate.sh   # ruff check + mypy (runs both, summarizes)
```

CI installs the same pinned `requirements.txt` and runs the same `scripts/validate.sh` — local and CI never drift.

## Conventions

### Agent pattern

Every agent file has the same shape:

```python
"""
<Title> Agent
=============
"""

from agno.agent import Agent

from app.settings import default_model
from db import get_postgres_db

INSTRUCTIONS = """\
<one short paragraph: what the agent does, which tools it uses, the
rules to follow when answering>
"""

my_agent = Agent(
    id="my-agent",
    name="My Agent",
    model=default_model(),
    db=get_postgres_db(),
    tools=[...],
    instructions=INSTRUCTIONS,
    enable_agentic_memory=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)
```

Three patterns to copy from:

- **Direct tools** — see [`agents/web_search.py`](agents/web_search.py). The agent sees each tool individually. Best when the user knows which tools the agent needs.
- **Context provider** — see [`agents/code_search.py`](agents/code_search.py). The agent sees one `query_<thing>` tool that hands off to a sub-agent. Best for one-source agents and when collapsing many tools into one keeps the model focused.
- **Studio builder** — see [`agents/agent_builder.py`](agents/agent_builder.py). The agent sees StudioTool, a safe `Registry`, Agno docs MCP, and Studio confirmation gates. Best when the user should create or refine components from the AgentOS UI.

### Database

```python
# Plain agent — sessions, memory, agentic memory live here
from db import get_postgres_db
agent_db = get_postgres_db()

# Agent with a Knowledge base (RAG) — pass through `knowledge=`
from db import create_knowledge
my_kb = create_knowledge("My Knowledge", "my_vectors")
```

Knowledge bases use PgVector with `SearchType.hybrid` and `text-embedding-3-small`. Document contents go into `<table_name>_contents`.

## Adding a new agent

Two options:

1. **Hand it to Claude Code** — run the `/create-new-agent` skill (or just ask to "create a new agent") in a Claude Code session pointed at this repo. Claude asks the user what the agent should do, generates the file, registers it, smoke-tests it. See [Working with coding agents](#working-with-coding-agents).
2. **Do it manually** — create `agents/<slug>.py`, register in `app/main.py`, add prompts to `app/config.yaml`. Then `docker compose restart agentos-api`. This template uses MCPTools inside AgentOS, so do not rely on uvicorn reload.

## Iterating on an agent

Two recursive loops over the same agent. Use them together.

- **`/extend-agent`** ([`.agents/skills/extend-agent`](.agents/skills/extend-agent/SKILL.md)) — **you drive.** Add a tool, add a capability, refine the prompt, fix a known bug. Claude is the Agno-aware pair-programmer (uses the `agno-docs` MCP for any toolkit research). Loop: change → smoke-test → "anything else?".
- **`/improve-agent`** ([`.agents/skills/improve-agent`](.agents/skills/improve-agent/SKILL.md)) — **Claude drives.** Derives probes from the agent's `INSTRUCTIONS`, judges, edits, re-runs. No user input needed. Loop: probe → judge → edit → re-probe.

Use `/extend-agent` to *change* the agent; use `/improve-agent` to *harden* it against its stated intent. Most fixes from either loop are one sentence in `INSTRUCTIONS`.

## Evals

The eval suite lives in [`evals/`](evals/). Each case wraps agno's [`AgentAsJudgeEval`](https://docs.agno.com/evals/agent-as-judge) (LLM judge against a rubric, binary pass/fail) and/or [`ReliabilityEval`](https://docs.agno.com/evals/reliability) (tool-call assertion). Cases are tagged with profiles:

- `smoke` — fast checks that prove the template's self-driving surfaces still work.
- `release` — broader checks for pre-release confidence.
- `live` — current web/source checks that are useful but should not be deterministic release gates.

Run with `python -m evals --profile smoke`, `python -m evals --profile release`, or `python -m evals --case <name>`. Add `--json-output out.json` when a workflow or coding agent needs machine-readable results. Results log to Postgres via `db=eval_db` so history is visible at os.agno.com.

To diagnose failures and fix in scope, run the `/eval-and-improve` skill ([`.agents/skills/eval-and-improve`](.agents/skills/eval-and-improve/SKILL.md)) in Claude Code.

## Reviewing the repo

Run the `/review-and-improve` skill ([`.agents/skills/review-and-improve`](.agents/skills/review-and-improve/SKILL.md)). A recurring sweep that diffs docs against code: every agent registered, every env var documented, every path in a doc still exists, every script behaves as advertised. Auto-fixes mechanical drift; flags anything bigger. Best run before a public-facing release or after a refactor.

## Working with coding agents

Dev-time **coding-agent workflows** live in [`.agents/skills/`](.agents/skills/) — the vendor-neutral home for coding-agent assets, mirroring how `CLAUDE.md` symlinks to `AGENTS.md`. `.claude/skills` is a committed symlink into it, so Claude Code picks the skills up on every clone with no setup step; other harnesses (Codex, Cursor, …) can symlink the same folder. (Windows needs developer mode or `core.symlinks=true` for the symlink to materialize.) Claude-specific config like `.claude/settings.json` stays a real file in `.claude/`.

These workflows cover the agent-development lifecycle in this template:

- **`/create-new-agent`** — scaffold a new agent: guided discovery or from a concrete idea → generate `agents/<slug>.py`, register it, smoke-test it live.
- **`/extend-agent`** — you drive. Add a tool/source, refine `INSTRUCTIONS`, fix a known bug. Uses the `agno-docs` MCP for grounded toolkit research.
- **`/improve-agent`** — Claude drives. Derives probes from the agent's `INSTRUCTIONS`, judges, edits, re-runs. No user input needed.
- **`/eval-and-improve`** — run the eval suite, diagnose failures, fix in scope until green.
- **`/review-and-improve`** — repo-wide drift sweep (docs vs code vs config).

Invoke a skill by name (`/extend-agent`) or just describe the task — Claude Code matches it from the skill's `description`.

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | yes | — | OpenAI key for models + embeddings. |
| `RUNTIME_ENV` | no | `prd` | `dev` disables JWT. Compose sets this to `dev` for local — never put it in an env file that syncs to Railway, or production deploys unauthenticated. |
| `JWT_VERIFICATION_KEY` | prd | — | Public key from os.agno.com. Required when `RUNTIME_ENV=prd` and `authorization=True`, unless `JWT_JWKS_FILE` is set. |
| `JWT_JWKS_FILE` | prd | — | Path to a JWKS file; alternative to `JWT_VERIFICATION_KEY` for production JWT verification. |
| `AGENTOS_URL` | no | `http://127.0.0.1:8000` | Scheduler base URL — cron triggers reach AgentOS over this. `scripts/railway/up.sh` auto-sets it to the created Railway domain (and writes it back into your env file); only set it by hand for custom domains or tunnels. Left at the localhost default in prod, scheduled jobs silently never fire. |
| `INTERNAL_SERVICE_TOKEN` | no | auto-generated | Token the scheduler uses to call back into AgentOS. Auto-generated per process when unset — fine for a single replica. Running more than one replica, set one shared value everywhere, or scheduled runs 401 whenever a callback lands on a replica that didn't fire them. |
| `ENABLE_DEPLOY_CHECK` | no | `True` | The reference deployment-check cron (`app/schedules.py`) runs daily by default. Set `False` to disable; the workflow stays runnable on demand regardless. |
| `ENABLE_EVAL_REGRESSION` | no | `False` | If `True`, schedules the eval-regression workflow. Off by default because it uses model calls. |
| `EVAL_REGRESSION_PROFILE` | no | `smoke` | Eval profile used by the scheduled eval-regression workflow. |
| `EVAL_REGRESSION_TIMEOUT_SECONDS` | no | `90` | Default per-case timeout for eval-regression runs; applies only to cases that don't set their own `timeout_seconds`. |
| `EVAL_REGRESSION_SUITE_TIMEOUT_SECONDS` | no | `600` | Whole-suite timeout for eval-regression runs. The default fits the `smoke` profile; raise it (e.g. `900`) when scheduling `release`. |
| `PARALLEL_API_KEY` | no | — | Authenticates the WebSearch Agent's Parallel SDK / MCP connection (raises rate ceiling). |
| `SLACK_BOT_TOKEN` | no | — | Bot token. Set with signing secret to enable the Slack interface. |
| `SLACK_SIGNING_SECRET` | no | — | Signing secret. Both it and the bot token must be set for the interface to load. |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASS` / `DB_DATABASE` | no | matches compose | Postgres connection. |
| `DB_DRIVER` | no | `postgresql+psycopg` | SQLAlchemy driver. |
| `AGNO_DEBUG` | no | `False` | If `True`, agno emits verbose debug logs. Compose sets this for dev. |
| `WAIT_FOR_DB` | no | `False` | If `True`, the entrypoint blocks on the DB before starting. Compose sets this. |

## Ports

- API: `8000`
- Database: `5432`

## Scheduler

`scheduler=True` is on in [`app/main.py`](app/main.py). A schedule is a cron expression + an HTTP endpoint (a workflow or agent run); the poller fires due jobs in the background. Registration lives in [`app/schedules.py`](app/schedules.py)'s `register_schedules()`, called from the lifespan — idempotent (`if_exists="update"`, safe on every boot) and fail-soft (a bad schedule logs a warning rather than crashing startup).

**Reference examples.** [`workflows/deployment_check.py`](workflows/deployment_check.py) is a one-step, **deterministic** workflow — no LLM, no token cost — that returns a deployment readiness report. It checks DB connectivity and tables, JWT config, scheduler URL, Slack env consistency, schedule flags, and reference component imports. [`app/schedules.py`](app/schedules.py) registers a daily cron that hits its endpoint (`POST /workflows/deployment-check/runs`). Because it's deterministic and free, the cron runs **on** by default (daily at 13:00 UTC); disable it with `ENABLE_DEPLOY_CHECK=False`.

[`workflows/eval_regression.py`](workflows/eval_regression.py) runs a bounded eval profile and returns a compact report. It is registered in AgentOS for on-demand use, but its cron is **off** by default because it uses model calls. Set `ENABLE_EVAL_REGRESSION=True` to schedule the smoke profile daily at 14:00 UTC.

To add your own: define a `Workflow` in `workflows/`, import it into [`app/main.py`](app/main.py) and add it to `AgentOS(workflows=[...])`, and register a schedule for it in `register_schedules()`. Other common uses: **maintenance** (purge old sessions, vacuum tables), **periodic re-evaluation** (run `python -m evals` weekly to catch regressions).

See [agno scheduler docs](https://docs.agno.com/agent-os/scheduler) for the cron API.

## Optional Platform Steward

Keep this template light by default. For production operations, add a Platform Steward agent or workflow as an opt-in layer. It should read deployment-check output, eval-regression reports, traces, logs, and recent diffs; diagnose likely causes; then recommend or prepare a fix behind approval. Do not register it by default in this template.

Good first tools:

- read eval JSON reports
- read recent deployment-check results
- inspect trace/log summaries
- inspect `git diff`
- propose a patch or PR, but require human approval before mutation or deploy

## Slack

Set `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` and restart. The default wiring in `app/main.py` routes Slack messages to `agent_builder` so users can request new components from chat. Change the `agent=` arg to point at another agent. See the [agno Slack interface docs](https://docs.agno.com/agent-os/interfaces/overview) for the Slack-side app setup.

For Discord, Telegram, WhatsApp, and custom UIs, mirror the Slack conditional pattern with the relevant agno interface — see [agno interfaces overview](https://docs.agno.com/agent-os/interfaces/overview).

## Deploying to Railway

```bash
./scripts/railway/up.sh        # provision Postgres + agent-os service
./scripts/railway/env-sync.sh  # sync .env.production (default) or .env
./scripts/railway/redeploy.sh  # redeploy after code changes
```

`up.sh` creates the domain before deploying and sets `AGENTOS_URL` to it (on Railway and in your env file), so the scheduler is reachable in prod out of the box.

JWT auth is on by default. After creating the Railway domain, `up.sh` pauses if `JWT_VERIFICATION_KEY` or `JWT_JWKS_FILE` is missing, so you can connect the OS at os.agno.com (Connect OS → Live, name it `Live Self-Driving Agent Platform`, then Settings → OS & Security → Token-Based Authorization (JWT)), paste the full PEM into the prompt, and let the script save it to the env file. Live AgentOS Connections are a paid feature; use `PLATFORM30` to get 1 month off. The script re-reads the env file and pushes the key before the first deploy. If you skip the prompt or run non-interactively, add the key later and run `./scripts/railway/env-sync.sh`.

The Railway *project* is `agent-platform`; the app *service* is `agent-os`.

## Common Tasks

```bash
# Add a dependency
# 1. Edit pyproject.toml
./scripts/generate_requirements.sh upgrade
docker compose up -d --build

# Build a multi-arch image (maintainer-only)
./scripts/build_image.sh

# Tail Railway logs
railway logs --service agent-os
```

## Documentation Links

- [Agno docs](https://docs.agno.com) — full framework reference.
- [Agno LLM-friendly docs](https://docs.agno.com/llms.txt) — concise overview, good for fetching.
- [AgentOS introduction](https://docs.agno.com/agent-os/introduction).
- [Agno tools / toolkits](https://docs.agno.com/tools/toolkits) — 100+ integrations.
- [Agno model providers](https://docs.agno.com/models) — OpenAI, Anthropic, Google, Ollama, Bedrock, Azure, etc.
- [Agno teams](https://docs.agno.com/teams/overview) — multi-agent routing/coordination.
- [Agno workflows](https://docs.agno.com/workflows/overview) — deterministic step-by-step pipelines.
- [Agno interfaces](https://docs.agno.com/agent-os/interfaces/overview) — Slack, Discord, Telegram, WhatsApp, custom UIs.
