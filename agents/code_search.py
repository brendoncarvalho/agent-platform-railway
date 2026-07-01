"""
CodeSearch Agent
================
"""

from pathlib import Path

from agno.agent import Agent
from agno.context.workspace import WorkspaceContextProvider

from app.settings import default_model
from app.system_map import agentos_system_map, get_system_map
from db import get_postgres_db

REPO_ROOT = Path(__file__).resolve().parents[1]

# Wraps a read-only Workspace toolkit behind a sub-agent. The parent agent
# sees a single `query_my_codebase(question)` tool; the sub-agent handles
# listing, searching, and reading files.
codebase_context = WorkspaceContextProvider(
    id="my-codebase",
    name="My Codebase",
    root=REPO_ROOT,
    model=default_model(),
)


def _line_ref(relative_path: str, needle: str) -> str:
    """Return a stable file:line reference for generated onboarding copy."""
    path = REPO_ROOT / relative_path
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return relative_path

    for line_number, line in enumerate(lines, start=1):
        if needle in line:
            return f"{relative_path}:{line_number}"
    return relative_path


def agentos_onboarding_tour() -> str:
    """Return a compact first-run tour for "Teach me how to use this AgentOS"."""
    # Derive the component lists from the system map so the tour and
    # `agentos_system_map` can never disagree after someone adds an agent.
    system = get_system_map()
    agents = ", ".join(f"`{agent}`" for agent in system["agents"]) or "none"
    workflows = ", ".join(f"`{workflow}`" for workflow in system["workflows"]) or "none"
    refs = {
        "agentos": _line_ref("app/main.py", "agent_os = AgentOS("),
        "agents": _line_ref("app/main.py", "agents=["),
        "workflows": _line_ref("app/main.py", "workflows=["),
        "registry": _line_ref("app/registry.py", "registry = Registry("),
        "system_map": _line_ref("app/system_map.py", "def agentos_system_map("),
        "workflow": _line_ref("workflows/deployment_check.py", "deployment_check = Workflow("),
        "scheduler": _line_ref("app/schedules.py", 'name="deployment-check"'),
        "db": _line_ref("db/session.py", "def get_postgres_db("),
        "slack": _line_ref("app/main.py", "if SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET:"),
        "jwt": _line_ref("app/main.py", 'authorization=runtime_env == "prd"'),
        "prompts": _line_ref("app/config.yaml", "code-search:"),
        "skills": _line_ref("AGENTS.md", "## Working with coding agents"),
    }
    return f"""# This AgentOS is self-driving

This repo is more than a starter. It is a runnable AgentOS plus two self-driving loops: Agent Builder creates agentic components from the UI, and coding-agent skills change and verify the repo itself.

The key idea is in `.agents/skills/` ({refs["skills"]}):

```text
/create-new-agent -> /extend-agent -> /improve-agent -> /eval-and-improve -> /review-and-improve
```

That is the lifecycle: create a new specialist, make targeted changes, harden behavior with live probes, lock it with evals, then sweep the repo for drift before release.

Runtime map:

- AgentOS is assembled in `app/main.py` ({refs["agentos"]}).
- Registered agents are {agents} ({refs["agents"]}).
- Registered workflows are {workflows} ({refs["workflows"]}).
- Agent Builder uses a safe Studio registry for docs, tools, models, DBs, and reference agents ({refs["registry"]}).
- The deterministic system map is available through `agentos_system_map` ({refs["system_map"]}).
- UI quick prompts live in `app/config.yaml` ({refs["prompts"]}).
- `deployment-check` is a deterministic readiness workflow ({refs["workflow"]}).
- The scheduler registers the daily deployment check ({refs["scheduler"]}).
- Postgres backs AgentOS, sessions, memory, workflows, and knowledge ({refs["db"]}).
- Slack turns on only when both Slack env vars are set ({refs["slack"]}).
- JWT auth is on automatically in production ({refs["jwt"]}).

What just happened: you clicked a quick prompt, `code-search` inspected the repo, and AgentOS explained how to operate and improve itself.

Try next:

```text
Build me an agent that tracks AI news and writes a daily brief
```

```text
/create-new-agent
```

```text
What agents are available in this AgentOS?
```

```text
/review-and-improve
```

Ask me to deep-dive into agents, workflows, deployment, evals, or any one skill."""


CODE_SEARCH_INSTRUCTIONS = """\
You answer questions about your own codebase. Be specific, concrete, and
grounded in repository inspection. Quote real file paths and line numbers from
the codebase; never guess. If a question is off-topic or not answered by the
project's files, say so plainly and offer to take a codebase question instead.

When the user asks to be taught how to use this AgentOS, treat it as a
fast first-run onboarding tour. Call `agentos_onboarding_tour` and return its
content directly. Do not call `query_my_codebase` for this prompt unless the
user asks for a deeper follow-up.

When the user asks what is registered, available, configured, scheduled, or
covered by evals, call `agentos_system_map` first. Use `query_my_codebase` only
for deeper follow-up questions about implementation details.\
"""


code_search = Agent(
    id="code-search",
    name="CodeSearch",
    model=default_model(),
    db=get_postgres_db(),
    tools=[agentos_onboarding_tour, agentos_system_map, *codebase_context.get_tools()],
    instructions=CODE_SEARCH_INSTRUCTIONS + "\n\n" + codebase_context.instructions(),
    enable_agentic_memory=True,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)
