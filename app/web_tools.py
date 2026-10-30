"""
Web Tools
=========

Parallel web tools shared by the registry and the web-facing agents.
"""

from typing import Any

from agno.tools.parallel import ParallelTools


class SharedParallelTools(ParallelTools):
    """ParallelTools shared across runs instead of deep-copied per run.

    AgentOS deep-copies each agent's tools for every run. The Parallel client holds
    thread locks that can't be copied, so the copy fails, agno falls back to sharing
    the original toolkit, and the half-built httpx client logs an ignored
    ``AttributeError: ... no attribute '_state'`` from its ``__del__`` on every run.
    Sharing up front keeps the same behavior without the copy attempt or the noise.
    """

    def __deepcopy__(self, memo: dict[int, Any]) -> "SharedParallelTools":
        return self
