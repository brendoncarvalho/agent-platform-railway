# Self-Driving Agent Platform

A platform that builds, runs, evaluates, and improves agents with agents.

Built on [Agno](https://docs.agno.com). Everything runs in your cloud. Your data lives in your database.

## Driven by agents

This codebase has two self-driving loops:

- **Coding-agent skills** let Claude Code, Codex, Cursor, and other coding agents build, test, and harden the platform itself. Five skills cover the full agent development lifecycle — see [Using the platform](#using-the-platform).
- **Agent Builder in the UI** creates agents, teams, and workflows through AgentOS Studio tools, grounded by the Agno docs MCP and a safe registry.

Trace data, agent code, evals, and system logs are all available to coding agents, so the platform can inspect and improve itself end to end.

## Get Started

### Step 1: Run locally

> **Prerequisite:** [Docker](https://www.docker.com/get-started/) installed and running.

```sh
git clone https://github.com/agno-agi/agent-platform-railway.git agent-platform
cd agent-platform

# Configure credentials
cp example.env .env
# Open .env and set OPENAI_API_KEY

# Run the platform on docker
docker compose up -d --build
```

Confirm your AgentOS is running at [http://localhost:8000/docs](http://localhost:8000/docs).

### Step 2: Connect the AgentOS UI

1. Open [os.agno.com](https://os.agno.com?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway) and sign in.
2. Click **Connect OS**, enter `http://localhost:8000` as the URL, name it **Local Agent Platform**, and connect.

### Step 3: Build your first agent

1. Click **Chat** under the **Agent Builder** agent and try the first prompt: "Build an agent that tracks AI news and writes a daily brief". Go through the agent development process.
2. Once created, click the **Refresh** button on the top right. You should now see the "Daily AI News Brief" agent in the **Agents** dropdown. Click the newly created agent.
3. Ask: "What's new with Anthropic?"

## Run in production

You can run the platform anywhere that supports containerized images. For the lightest lift, the codebase comes with scripts to deploy the platform to [Railway](https://railway.com).

> **Prerequisite:** [Railway CLI](https://docs.railway.com/cli#installing-the-cli) installed and `railway login` completed.

### 1. Set up your production env

Create a new `.env.production` file for production credentials.

```sh
cp .env .env.production
# Edit .env.production with production values
```

The deploy scripts read `.env.production` first and fall back to `.env`. This lets you keep separate values for local and production: different OpenAI keys, production-only credentials, a different Slack workspace. `.env.production` is gitignored.

### 2. Deploy

```sh
./scripts/railway/up.sh
```

This provisions Postgres and the app service on the same private network.

### 3. Set production auth

Token-Based Authorization is on by default. Without `JWT_VERIFICATION_KEY` or `JWT_JWKS_FILE`, the app refuses to serve traffic. The platform's job is to keep your data private, so the safe default is "refuse to start" without an authentication token.

Token-Based Auth gives you three things:

1. **No public access.** The server rejects requests without a valid token.
2. **Per-request identity.** Middleware parses the token and extracts the `user_id`, `session_id`, and custom claims. Each request is tied to a user and session, giving you auditability and traceability.
3. **Granular permissions.** User tokens can run an agent and view their own sessions. Admin tokens read everyone's sessions and test any agent.

During `./scripts/railway/up.sh`, the script creates your Railway domain and pauses so you can mint the key before the app starts.

1. Open [os.agno.com](https://os.agno.com?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway), click **Connect OS** → **Live**, enter your Railway domain, and connect.
2. Name it **Live Agent Platform**.
3. Go to **Settings** → **OS & Security**.
4. Turn **Token-Based Authorization (JWT)** on.
5. Copy the public key.
6. Paste the full public key into the `up.sh` prompt. The script saves it into your env file for future syncs:

```sh
JWT_VERIFICATION_KEY=-----BEGIN PUBLIC KEY-----
MIIBIjANBgkq...
-----END PUBLIC KEY-----
```

> **Heads up.** Live AgentOS Connections are a paid feature. Use `PLATFORM30` to get 1 month off. We are working on a free trial so you don't have to pay to try.

If you run non-interactively or skip the prompt, you can sync environment variables later with `./scripts/railway/env-sync.sh`.

### 4. Verify

You can check the logs on the Railway dashboard, or by running the following command:

```sh
railway logs --service agent-os
```

### 5. Redeploy after code changes

For one-off updates from your machine, run the following command:

```sh
./scripts/railway/redeploy.sh
```

To auto-deploy on every push to `main`, follow these steps:

1. Open the Railway dashboard, your project, the agent-os service, **Settings**.
2. Under **Source**, click **Connect Repo** and pick your repo.
3. Set the deploy branch to `main` and save.

Push to `main` triggers a build and rolling deploy. `./scripts/railway/env-sync.sh` is still how you sync env changes.

### 6. Sync environment variables

To re-sync environment variables, run the following command:

```sh
./scripts/railway/env-sync.sh
```

### Opting out of JWT (not recommended)

Set `authorization=False` in [`app/main.py`](app/main.py) and redeploy. Use this only inside a private VPC behind another auth layer. Without it, anyone who guesses your Railway domain can access your platform.

## Using the platform

This platform is designed around the **create → improve → evaluate → maintain** workflow.

Create agents/teams/workflows from the UI or using a coding agent, improve and evaluate with the skills, and maintain with a recurring drift sweep.

### Create

**From the UI.** Open **Agent Builder** and describe the job, as in the quickstart. Agent Builder pulls framework details from the Agno docs MCP, picks tools and models from the safe Studio registry, and creates components behind confirmation gates — approving the create publishes version 1 immediately, later edits stay drafts until you approve publishing, and it runs the component only when you ask.

**From a coding agent.** For agents that live in the repo, open your coding agent of choice (Claude Code, Codex, Cursor) and run:

```
/create-new-agent
```

It asks a few questions, generates the agent file in `agents/`, registers it in `app/main.py`, adds quick prompts to `app/config.yaml`, restarts the container, and smoke-tests it live.

### Improve

Chat with your agent at [os.agno.com](https://os.agno.com?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway). Run realistic prompts, try edge cases, watch the traces and sessions.

Then improve your agents by running the following skills:

- **`/extend-agent`** — Add a tool, add a capability, refine the instructions, fix a known bug.
- **`/improve-agent`** — Claude simulates scenarios from the agent's `INSTRUCTIONS`, runs them against the live container, judges the responses, and edits until they pass.

### Evaluate

Run the eval suite to check for regressions. The eval cases live in [`evals/cases.py`](evals/cases.py), tagged with profiles. The evals run on the host machine, so set up the venv with `./scripts/venv_setup.sh && source .venv/bin/activate`, then:

```sh
python -m evals --profile smoke     # fast checks of the self-driving surfaces
```

### Maintain

Because the repo is managed primarily by coding agents, it moves fast. Run `/review-and-improve` before a release or after a refactor: it sweeps for drift between docs, code, and config, auto-fixes mechanical drift like stale paths and missing env vars, and flags anything bigger.

## Environment variables

`compose.yaml` sets the dev defaults (`RUNTIME_ENV=dev`, `AGNO_DEBUG=True`, `WAIT_FOR_DB=True`) so local Docker skips JWT and waits for Postgres before serving.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | yes | none | OpenAI key for models and embeddings. |
| `RUNTIME_ENV` | no | `prd` | `dev` disables JWT. Compose sets this to `dev` for local — never put it in an env file that syncs to Railway, or production deploys unauthenticated. |
| `JWT_VERIFICATION_KEY` | prd | none | Public key from os.agno.com. Required when `RUNTIME_ENV=prd`, unless `JWT_JWKS_FILE` is set. |
| `JWT_JWKS_FILE` | prd | none | Path to a JWKS file; alternative to `JWT_VERIFICATION_KEY` for production JWT verification. |
| `AGENTOS_URL` | no | `http://127.0.0.1:8000` | Scheduler base URL. `scripts/railway/up.sh` auto-sets it to your Railway domain; set by hand only for a custom domain or tunnel. |
| `INTERNAL_SERVICE_TOKEN` | no | auto-generated | Scheduler-to-AgentOS callback token. Auto-generated per process — fine for one replica; set one shared value when running several. |
| `ENABLE_DEPLOY_CHECK` | no | `True` | The reference deployment-check cron runs daily by default. Set `False` to disable; the workflow is runnable on demand regardless. |
| `ENABLE_SCHEDULED_EVALS` | no | `False` | If `True`, schedules the run-evals workflow daily. Off by default because it uses model calls. |
| `EVALS_PROFILE` | no | `smoke` | Eval profile used by the run-evals workflow. |
| `EVALS_CASE_TIMEOUT_SECONDS` | no | `90` | Default per-case timeout for run-evals runs; applies only to cases that don't set their own `timeout_seconds`. |
| `EVALS_SUITE_TIMEOUT_SECONDS` | no | `600` | Whole-suite timeout for run-evals runs. The default fits the `smoke` profile; raise it (e.g. `900`) when scheduling `release`. |
| `PARALLEL_API_KEY` | no | none | Authenticates the WebSearch Agent's Parallel SDK / MCP connection. |
| `SLACK_BOT_TOKEN` / `SLACK_SIGNING_SECRET` | no | none | Both must be set to enable the Slack interface. |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASS` / `DB_DATABASE` | no | matches compose | Postgres connection. |
| `DB_DRIVER` | no | `postgresql+psycopg` | SQLAlchemy driver. |
| `AGNO_DEBUG` | no | `False` | If `True`, Agno emits verbose debug logs. Compose sets this for dev. |
| `WAIT_FOR_DB` | no | `False` | If `True`, the entrypoint blocks on the DB before starting. Compose sets this. |

## Learn more

- [Agno documentation](https://docs.agno.com?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway)
- [AgentOS introduction](https://docs.agno.com/agent-os/introduction?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway)
- [Agno on GitHub](https://github.com/agno-agi/agno). Drop a star if this is useful.
