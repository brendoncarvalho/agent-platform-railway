"""
Studio Components
=================

Small, dependency-free examples that make the Studio registry richer without
forcing clone users into third-party integrations.
"""

import fnmatch
import os
from pathlib import Path
from typing import Iterator, Literal

from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[1]
BLOCKED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
SECRET_FILENAMES = {"id_rsa", "id_ed25519"}
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


class AgentSpec(BaseModel):
    """Structured input for a proposed agent, team, or workflow."""

    name: str = Field(description="Human-readable component name.")
    purpose: str = Field(description="One sentence describing the job to be done.")
    component_type: Literal["agent", "team", "workflow"] = Field(description="Best-fit component type.")
    required_tools: list[str] = Field(default_factory=list, description="Registry tool names the component needs.")


class EvalReport(BaseModel):
    """Structured output for eval regression summaries."""

    profile: str = Field(description="Eval profile that ran, such as smoke, release, or live.")
    total: int = Field(description="Total cases selected.")
    passed: int = Field(description="Cases that passed.")
    failed: int = Field(description="Cases that failed.")
    status: Literal["PASS", "FAIL"] = Field(description="Overall eval status.")


def route_component_type(request: str) -> str:
    """Suggest agent, team, or workflow from a plain-language request."""
    lower = request.lower()
    if any(word in lower for word in ("daily", "schedule", "pipeline", "approval", "steps", "workflow")):
        return "workflow"
    if any(word in lower for word in ("team", "specialists", "debate", "reviewers", "coordinate")):
        return "team"
    return "agent"


def score_eval_status(passed: int, total: int) -> str:
    """Return PASS only when every selected eval case passed."""
    if total <= 0:
        return "FAIL"
    return "PASS" if passed == total else "FAIL"


def _resolve_repo_path(relative_path: str) -> Path | None:
    path = (REPO_ROOT / relative_path).resolve()
    if path == REPO_ROOT or not path.is_relative_to(REPO_ROOT):
        return None
    return path


def _is_blocked_path(path: Path) -> bool:
    relative = path.relative_to(REPO_ROOT)
    if any(part in BLOCKED_DIRS for part in relative.parts):
        return True
    name = path.name
    if name == ".env" or name.startswith(".env."):
        return True
    if name in SECRET_FILENAMES or path.suffix in SECRET_SUFFIXES:
        return True
    return False


def _is_text_file(path: Path) -> bool:
    # example.env is the committed credentials template (no real secrets);
    # the literal name is allowed while .env / .env.* stay blocked.
    return path.name in ("Dockerfile", "example.env") or path.suffix in TEXT_SUFFIXES


def _can_expose_file(path: Path) -> bool:
    return path.is_file() and not _is_blocked_path(path) and _is_text_file(path) and path.stat().st_size <= 200_000


def _matches_pattern(path: Path, pattern: str) -> bool:
    if pattern in ("", "*", "**/*"):
        return True
    return fnmatch.fnmatch(str(path.relative_to(REPO_ROOT)), pattern)


def _iter_safe_files(pattern: str = "**/*") -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [dirname for dirname in dirnames if dirname not in BLOCKED_DIRS]
        for filename in filenames:
            path = Path(dirpath) / filename
            if _matches_pattern(path, pattern) and _can_expose_file(path):
                yield path


def list_project_files(pattern: str = "**/*", limit: int = 80) -> list[str]:
    """List safe text files in the template repository."""
    files: list[str] = []
    for path in _iter_safe_files(pattern):
        files.append(str(path.relative_to(REPO_ROOT)))
        if len(files) >= limit:
            break
    return files


def read_project_file(relative_path: str, max_chars: int = 12_000) -> str:
    """Read one safe text file from the template repository."""
    path = _resolve_repo_path(relative_path)
    if path is None or not path.exists():
        return f"Not found or outside repository: {relative_path}"
    if not _can_expose_file(path):
        return f"Refused to read blocked, binary, large, or secret-like path: {relative_path}"

    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[truncated]"


def search_project_text(query: str, pattern: str = "**/*", limit: int = 40) -> list[str]:
    """Search safe text files for a literal query."""
    needle = query.strip()
    if not needle:
        return []

    results: list[str] = []
    for path in _iter_safe_files(pattern):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if needle.lower() in line.lower():
                snippet = line.strip()[:240]
                results.append(f"{path.relative_to(REPO_ROOT)}:{line_number}: {snippet}")
                if len(results) >= limit:
                    return results
    return results
