"""
Test configuration
==================

Unit tests never call a model provider or the database. The environment below is set before
any project module is imported so agents can be built with placeholder keys and media lands
in a temporary directory.
"""

import os
import tempfile
from pathlib import Path

import pytest

_MEDIA_DIR = Path(tempfile.mkdtemp(prefix="pemill-media-"))

os.environ.setdefault("RUNTIME_ENV", "dev")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-test-placeholder")
os.environ.setdefault("MEDIA_STORAGE", "local")
os.environ.setdefault("MEDIA_STORAGE_DIR", str(_MEDIA_DIR))
os.environ.setdefault("IMAGE_INPUT_MAX_MB", "1")

LIVE = os.getenv("PEMILL_LIVE_TESTS", "").strip().lower() in ("1", "true", "yes")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: calls real model providers (set PEMILL_LIVE_TESTS=1)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if LIVE:
        return
    skip = pytest.mark.skip(reason="live test: set PEMILL_LIVE_TESTS=1 (and real API keys) to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def media_dir(tmp_path: Path) -> Path:
    return tmp_path / "media"
