"""
System Map
==========

Deterministic helpers that summarize the live template surface without
calling a model or reaching outside the repository.
"""

from __future__ import annotations

import ast
from os import getenv
from pathlib import Path

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_yaml(relative_path: str) -> dict:
    path = REPO_ROOT / relative_path
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_module(relative_path: str) -> ast.Module | None:
    path = REPO_ROOT / relative_path
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return None


def _slug_from_name(name: str) -> str:
    return name.replace("_", "-")


def _keyword_list(node: ast.Call, keyword_name: str) -> list[str]:
    for keyword in node.keywords:
        if keyword.arg == keyword_name and isinstance(keyword.value, ast.List):
            return [_slug_from_name(element.id) for element in keyword.value.elts if isinstance(element, ast.Name)]
    return []


def _agentos_components() -> tuple[list[str], list[str]]:
    """Return the registered agent and workflow ids.

    Reads the live ``AgentOS`` instance so the map reports what the runtime
    actually registered, regardless of variable naming or list style in
    ``app/main.py``. The import is deferred to call time because ``app.main``
    imports this module's consumers; the source parse stays as a fallback for
    contexts where the app can't be imported.
    """
    try:
        import app.main

        agents = [
            str(getattr(agent, "id", "")) for agent in app.main.agent_os.agents or [] if getattr(agent, "id", None)
        ]
        workflows = [
            str(getattr(workflow, "id", ""))
            for workflow in app.main.agent_os.workflows or []
            if getattr(workflow, "id", None)
        ]
        return agents, workflows
    except Exception:
        return _agentos_components_from_source()


def _agentos_components_from_source() -> tuple[list[str], list[str]]:
    tree = _parse_module("app/main.py")
    if tree is None:
        return [], []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "AgentOS":
            return _keyword_list(node, "agents"), _keyword_list(node, "workflows")
    return [], []


def _eval_profiles() -> dict[str, list[str]]:
    tree = _parse_module("evals/cases.py")
    if tree is None:
        return {}

    profiles: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Case"):
            continue
        case_name = ""
        case_profiles = ["release"]
        for keyword in node.keywords:
            if (
                keyword.arg == "name"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                case_name = keyword.value.value
            elif keyword.arg == "profiles" and isinstance(keyword.value, ast.Tuple):
                case_profiles = [
                    item.value
                    for item in keyword.value.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                ]
        for profile in case_profiles:
            profiles.setdefault(profile, []).append(case_name)
    return profiles


def _skills() -> list[str]:
    skills_dir = REPO_ROOT / ".agents/skills"
    if not skills_dir.exists():
        return []
    return sorted(path.name for path in skills_dir.iterdir() if path.is_dir())


def _schedule_names() -> list[str]:
    tree = _parse_module("app/schedules.py")
    if tree is None:
        return []

    names: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "create"):
            continue
        for keyword in node.keywords:
            if (
                keyword.arg == "name"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                names.append(keyword.value.value)
    return sorted(names)


def _schedule_statuses() -> dict[str, str]:
    statuses: dict[str, str] = {}
    for name in _schedule_names():
        if name == "deployment-check":
            statuses[name] = "enabled" if getenv("ENABLE_DEPLOY_CHECK", "True") == "True" else "disabled"
        elif name == "eval-regression":
            statuses[name] = "enabled" if getenv("ENABLE_EVAL_REGRESSION", "False") == "True" else "disabled"
        else:
            statuses[name] = "defined"
    return statuses


def _function_list_returns(tree: ast.Module) -> dict[str, list[ast.expr]]:
    """Map local helper-function name -> elements of every list literal it returns."""
    returns: dict[str, list[ast.expr]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        elements: list[ast.expr] = []
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and isinstance(child.value, ast.List):
                elements.extend(child.value.elts)
        if elements:
            returns[node.name] = elements
    return returns


def _component_names(elements: list[ast.expr], helpers: dict[str, list[ast.expr]], depth: int = 0) -> list[str]:
    names: list[str] = []
    for element in elements:
        if isinstance(element, ast.Starred):
            element = element.value
        target = element.func if isinstance(element, ast.Call) else element
        name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
        if not name:
            continue
        if name in helpers and depth < 3:
            names.extend(_component_names(helpers[name], helpers, depth + 1))
        else:
            names.append(name)
    return names


def _component_name(component: object) -> str:
    for attr in ("id", "name", "__name__"):
        value = getattr(component, attr, None)
        if isinstance(value, str) and value:
            return value
    return ""


def _registry_components() -> dict[str, list[str]]:
    """Summarize the Studio registry contents by their runtime names.

    Imports the live registry so names match what StudioTool actually resolves
    (toolkit names, agent ids); the source parse below stays as a fallback for
    contexts where the registry can't be imported.
    """
    try:
        from app.registry import registry

        components: dict[str, list[str]] = {}
        for kind in ("tools", "models", "dbs", "schemas", "functions", "agents"):
            names = [_component_name(item) for item in getattr(registry, kind, None) or []]
            names = [name for name in names if name]
            if names:
                components[kind] = names
        return components
    except Exception:
        return _registry_components_from_source()


def _registry_components_from_source() -> dict[str, list[str]]:
    """Derive the Studio registry contents from app/registry.py without importing it."""
    tree = _parse_module("app/registry.py")
    if tree is None:
        return {}

    helpers = _function_list_returns(tree)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Registry"):
            continue
        components: dict[str, list[str]] = {}
        for keyword in node.keywords:
            if keyword.arg is None or keyword.arg in ("name", "description"):
                continue
            value = keyword.value
            if isinstance(value, ast.List):
                elements = value.elts
            elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in helpers:
                elements = helpers[value.func.id]
            else:
                continue
            names = _component_names(elements, helpers)
            if names:
                components[keyword.arg] = names
        # Reference agents are declared by variable name; report them as the
        # agent ids used everywhere else in the map.
        if "agents" in components:
            components["agents"] = [_slug_from_name(name) for name in components["agents"]]
        return components
    return {}


def get_system_map() -> dict:
    """Return the deterministic system map used by the CodeSearch agent."""
    config = _read_yaml("app/config.yaml")
    quick_prompts = config.get("chat", {}).get("quick_prompts", {})
    agents, workflows = _agentos_components()
    return {
        "agents": agents,
        "workflows": workflows,
        "schedules": _schedule_statuses(),
        "quick_prompts": {slug: len(prompts) for slug, prompts in quick_prompts.items()},
        "eval_profiles": {profile: sorted(cases) for profile, cases in _eval_profiles().items()},
        "skills": _skills(),
        "registry": {
            "file": "app/registry.py",
            "components": _registry_components(),
        },
    }


def agentos_system_map() -> str:
    """Return a compact markdown map of this self-driving AgentOS."""
    system = get_system_map()
    eval_lines = [
        f"- `{profile}`: {len(cases)} case(s) — {', '.join(cases)}"
        for profile, cases in sorted(system["eval_profiles"].items())
    ]
    prompt_lines = [f"- `{slug}`: {count} quick prompt(s)" for slug, count in sorted(system["quick_prompts"].items())]
    registry_lines = [
        f"- {kind}: {', '.join(f'`{name}`' for name in names)}"
        for kind, names in sorted(system["registry"]["components"].items())
    ] or ["- (could not derive from app/registry.py)"]
    return "\n".join(
        [
            "# Self-Driving Agent Platform Map",
            "",
            f"Agents: {', '.join(f'`{agent}`' for agent in system['agents']) or 'none'}",
            f"Workflows: {', '.join(f'`{workflow}`' for workflow in system['workflows']) or 'none'}",
            "Schedules: "
            + (
                ", ".join(f"`{name}` ({status})" for name, status in sorted(system["schedules"].items()))
                if system["schedules"]
                else "none"
            ),
            "",
            "Quick prompts:",
            *prompt_lines,
            "",
            "Eval profiles:",
            *eval_lines,
            "",
            f"Coding-agent skills: {', '.join(f'`/{skill}`' for skill in system['skills']) or 'none'}",
            "",
            f"Studio registry ({system['registry']['file']}) — the safe component catalog Agent Builder"
            " composes from (AgentOS also mirrors every registered agent into it at runtime):",
            *registry_lines,
        ]
    )
