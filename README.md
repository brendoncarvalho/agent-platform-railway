# Self-Driving Agent Platform

An agent platform you build, run, and improve with coding agents.

Built on [Agno](https://docs.agno.com). Everything runs in your cloud. Your data lives in your database.

## Driven by coding agents

This codebase is designed to be used by coding agents.
- Trace data, agent code, system logs are all accessible to coding agents like Claude Code, allowing them to read, update, and improve the system end-to-end.
- The Agno docs MCP is loaded so SDK knowledge is grounded in the real API.
- 5 skills are included that cover the full agent development lifecycle.

### Skills

This codebase includes five skills that cover the full agent development lifecycle:

1. `/create-new-agent`: Your coding agent asks a few questions to clarify requirements, creates the agent using research grounded in the Agno SDK docs, and smoke-tests it by running it in the live container.
2. `/improve-agent`: Your coding agent fine-tunes your agent by running simulations in a loop. Claude derives probes from the agent's `INSTRUCTIONS`, runs them against the live container, judges the responses, and edits until they pass.
3. `/extend-agent`: Extend your agents with new features. Add tools, refine prompts, fix bugs. The Agno docs MCP is loaded so SDK knowledge is grounded in the real API.
4. `/eval-and-improve`: Run the eval suite, diagnose failures, and fix until all cases pass.
5. `/review-and-improve`: Sweep the entire repo for drift between docs, code, and config. Auto-fixes mechanical drift like stale paths and missing env vars; flags anything bigger.

Using these skills, your entire agent platform becomes self-driving, no manual intervention needed.

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

Connect the the AgentOS UI:
1. Open [os.agno.com](https://os.agno.com?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway) and sign-in
2. Click on **Connect OS**, enter `http://localhost:8000` as the URL, name it **Local AgentOS** and connect.
3. Click on **Chat** on the **Code Search Agent**, then click on the middle prompt: "Teach me how to use this AgentOS".

### Step 2: Create your first agent

Open your coding agent of choice (Claude Code, Codex, Cursor, etc.) and run the skill:

```
/create-new-agent
```

(Or just say "create a new agent in a new branch" — Claude Code matches the skill automatically.) Claude asks a few questions, generates the agent file in `agents/`, registers it in `app/main.py`, adds prompts to `app/config.yaml`, restarts the container, and smoke-tests via cURL. Usually 5-10 minutes for a simple agent.

Two reference agents are available in the template for you to study and copy from:

| Agent | Pattern | Tools |
|---|---|---|
| WebSearch | Direct tools | `parallel_search` / `parallel_extract` (needs `PARALLEL_API_KEY`); `web_search` / `web_fetch` keyless |
| CodeSearch | Context provider sub-agent | `query_my_codebase` |

### Step 3: Chat with your agent

Chat with your agents at [os.agno.com](https://os.agno.com?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway). Run realistic prompts. Try edge cases. Watch the traces and sessions in the UI.

### Step 4: Improve your agent

To improve your agents, use one of these recursive loops:

1. **`/improve-agent`**. Hardens and fine-tunes your agent based on its existing spec. Claude derives probes from the agent's `INSTRUCTIONS`, runs them against the live container, judges responses, and edits until it passes.

2. **`/extend-agent`**. Add a new feature to an agent. You direct, Claude executes. Add tools, refine prompts, fix bugs. The Agno docs MCP is loaded so toolkit research is grounded in the real API.

Both run in Claude Code against `http://localhost:8000` with hot-reload. These are [coding-agent skills](AGENTS.md#working-with-coding-agents) — invoke by name or describe the task.

### Step 5: Lock in behavior with evals

The extend and improve loops are great for improving the agents. Evals are the regression suite that makes sure your agent continues to perform as designed.

The eval surface is two files: [`evals/cases.py`](evals/cases.py) (declarative cases) and [`evals/__main__.py`](evals/__main__.py) (runner). Evals use Agno's built-in [`AgentAsJudgeEval`](https://docs.agno.com/evals/agent-as-judge?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway) (LLM judge against a rubric, binary pass/fail) and/or [`ReliabilityEval`](https://docs.agno.com/evals/reliability?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway) (tool-call assertion).

```bash
python -m evals                # run the suite (concise)
python -m evals -v             # stream the full agent run with rich panels
python -m evals --case <name>  # run one case
```

Results log to Postgres via `db=eval_db`. Connect your AgentOS at [os.agno.com](https://os.agno.com?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway) to explore eval history over time.

Run the `/eval-and-improve` skill in Claude Code to run the suite, diagnose failures, and fix in scope.

### Step 6: Sweep for drift

Because the repo is managed primarily by coding agents, it moves fast. Run:

```
/review-and-improve
```

Claude sweeps the whole repo for drift between docs, code, and config. Every agent file on disk should be registered in `app/main.py`. Every env var the code reads should be in `example.env` and the AGENTS.md table. Every path in a markdown doc should still exist. Every script mentioned in docs should do what's claimed.

Mechanical drift gets auto-fixed in place. Anything bigger gets flagged with a recommended next step. Best run before a release or after a refactor.

## Run in production

You can run the platform anywhere that supports containerized images.

For the lightest lift, the codebase comes with one-command-deploy scripts to run the platform on Railway.

Requires the [Railway CLI](https://docs.railway.com/cli#installing-the-cli) and `railway login`.

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

Token-Based Authorization is on by default. Without `JWT_VERIFICATION_KEY` or `JWT_JWKS_FILE`, the app refuses to serve traffic. The platform's job is to keep your data off the public web, so the safe default is "refuse to start" with an authentication token.

Token-Based Auth gives you three things:

1. **No public access.** The server rejects requests without a valid token.
2. **Per-request identity.** Middleware parses the token and injects `user_id`, `session_id`, and custom claims into your endpoints. Each request is tied to a user and session.
3. **Granular permissions.** User tokens can run an agent and view their own sessions. Admin tokens read everyone's sessions and test any agent.

During `./scripts/railway/up.sh`, the script creates your Railway domain before the first deploy. If production auth is missing, it prints that domain and pauses so you can mint the key before the app starts.

> **Heads up.** Live AgentOS Connections are a paid feature. Use `PLATFORM30` to get 1 month off.

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

You can also save it in `.env.production` yourself and press Enter at the prompt. Either way, the script re-reads the env file and pushes `JWT_VERIFICATION_KEY` or `JWT_JWKS_FILE` before deploying. If you run non-interactively or skip the prompt, you can still sync later with `./scripts/railway/env-sync.sh`.

### 4. Verify

`scripts/railway/up.sh` already set `AGENTOS_URL` to your Railway domain (on the service and in `.env.production`) so the in-cluster scheduler's cron triggers reach AgentOS — no action needed unless you're fronting it with a custom domain or tunnel, in which case set it by hand:

```sh
# .env.production — only for a custom domain / tunnel; up.sh fills this in otherwise
AGENTOS_URL=https://<your-app>.up.railway.app
```

For later env changes, push every variable to Railway:

```sh
./scripts/railway/env-sync.sh
```

Railway auto-deploys when env values change. Watch the logs and confirm the platform is serving:

```sh
railway logs --service agent-os
```

Once you see successful requests, AgentOS will connect through your Railway domain and you're live.

### 5. Redeploy after code changes

For one-off updates from your machine:

```sh
./scripts/railway/redeploy.sh
```

To auto-deploy on every push to `main`:

1. Open the Railway dashboard, your project, the agent-os service, **Settings**.
2. Under **Source**, click **Connect Repo** and pick your repo.
3. Set the deploy branch to `main` and save.

Push to `main` triggers a build and rolling deploy. `./scripts/railway/env-sync.sh` is still how you sync env changes.

### Opting out of JWT (not recommended)

Set `authorization=False` in [`app/main.py`](app/main.py) and redeploy. Use this only inside a private VPC behind another auth layer. Without it, anyone who guesses your Railway domain can read your sessions and run your agents.

### Scaling

The default deploy is two replicas at 4Gi memory and 2 vCPU each (zero-downtime rolling deploys plus basic fault tolerance). Bump `numReplicas` and `limits` in [`railway.json`](railway.json) as your usage grows.

## Extending the platform

### Multi-agent teams and workflows

For most things one agent is enough. When it isn't:

- **[Multi-agent teams](https://docs.agno.com/teams/overview?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway).** Coordinate (a leader plans and synthesizes), route (a router picks the right specialist), or broadcast (run everyone in parallel). Use when the right specialist isn't known up front.
- **[Agentic workflows](https://docs.agno.com/workflows/overview?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway).** Deterministic step-by-step pipelines. Use when a process needs to run the same way every time.

Rule of thumb: agents for open questions, teams for routing, workflows for processes.

### Scheduled tasks

`scheduler=True` is on in [`app/main.py`](app/main.py); [`app/schedules.py`](app/schedules.py) registers schedules from the lifespan (idempotent, fail-soft). The template ships a reference: [`workflows/deployment_check.py`](workflows/deployment_check.py) is a deterministic one-step workflow (no LLM, no token cost) that returns a deployment readiness report. It checks DB connectivity and tables, JWT config, scheduler URL, Slack env consistency, and reference component imports. Because it's deterministic and free, the daily cron is on by default; set `ENABLE_DEPLOY_CHECK=False` to disable it. The workflow is always runnable on demand at `POST /workflows/deployment-check/runs`.

To build your own, define a `Workflow` in [`workflows/`](workflows/), import it into [`app/main.py`](app/main.py) and add it to `AgentOS(workflows=[...])`, then register a cron for it. Common uses:

- **Maintenance.** Purge sessions older than 90 days. Vacuum tables.
- **Proactive runs.** Every weekday morning, summarize overnight news for your portfolio and send to Slack.
- **Periodic re-evaluation.** Wrap the eval suite as a scheduled workflow to catch behavior drift before users do.

See [Agno scheduler docs](https://docs.agno.com/agent-os/scheduler?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway) for the cron API.

### Interfaces

Agents should live where your users are. Slack, Discord, Telegram, custom UIs in your product.

**Slack** is pre-wired. Set `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` in your env and the interface lights up automatically. See [`app/main.py`](app/main.py):

```python
interfaces: list = []
if SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET:
    from agno.os.interfaces.slack import Slack

    interfaces.append(
        Slack(
            agent=code_search,
            streaming=True,
            token=SLACK_BOT_TOKEN,
            signing_secret=SLACK_SIGNING_SECRET,
            resolve_user_identity=True,
        )
    )
```

Swap the `agent=` arg to route Slack to a different agent. For the Slack-side app setup, see the [Agno Slack interface docs](https://docs.agno.com/agent-os/interfaces/overview?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway).

For Discord, Telegram, WhatsApp, or a custom UI, mirror the same conditional with the relevant interface from Agno. See the [Agno interfaces guide](https://docs.agno.com/agent-os/interfaces/overview?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway).

### Tools and MCP servers

The WebSearch agent in [`agents/web_search.py`](agents/web_search.py) shows the MCPTools pattern (URL plus transport). Copy it to wire any MCP server.

For built-in toolkits, Agno ships 100+. A typical wire-up is three lines:

```python
from agno.tools.linear import LinearTools

linear_agent = Agent(
    id="linear",
    model=default_model(),
    tools=[LinearTools()],
    instructions="You triage issues in Linear.",
    db=get_postgres_db(),
)
```

See [Agno tools](https://docs.agno.com/tools/toolkits?utm_source=github&utm_medium=example-repo&utm_campaign=agent-platform&utm_content=agent-platform&utm_term=railway) for the full catalog.

## Environment variables

`compose.yaml` sets the dev defaults (`RUNTIME_ENV=dev`, `AGNO_DEBUG=True`, `WAIT_FOR_DB=True`) so local Docker runs hot-reload and skips JWT. Production reads everything from `.env.production` via `./scripts/railway/env-sync.sh`.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | yes | none | OpenAI key for models and embeddings. |
| `RUNTIME_ENV` | no | `prd` | `dev` enables hot-reload and disables JWT. Compose sets this to `dev` for local. |
| `JWT_VERIFICATION_KEY` | prd | none | Public key from os.agno.com. Required when `RUNTIME_ENV=prd`, unless `JWT_JWKS_FILE` is set. |
| `JWT_JWKS_FILE` | prd | none | Path to a JWKS file; alternative to `JWT_VERIFICATION_KEY` for production JWT verification. |
| `AGENTOS_URL` | no | `http://127.0.0.1:8000` | Scheduler base URL. `scripts/railway/up.sh` auto-sets it to your Railway domain; set by hand only for a custom domain or tunnel. |
| `ENABLE_DEPLOY_CHECK` | no | `True` | The reference deployment-check cron runs daily by default. Set `False` to disable; the workflow is runnable on demand regardless. |
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
