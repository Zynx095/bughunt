from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.core.contracts import ExecutionContext  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import build_services  # noqa: E402


def make_settings(tmp_path: Path) -> Settings:
    # Explicitly disable remote providers so tests never make network calls.
    return Settings(data_dir=tmp_path, ai_provider="local", gemini_api_key=None, google_api_key=None,
                    openai_api_key=None, master_key=None, _env_file=None)


@pytest.fixture
def services(tmp_path):
    svc = build_services(make_settings(tmp_path))
    yield svc
    svc.store.engine.dispose()


@pytest.fixture
def run(services):
    """Execute an engine operation as a given role: run('crypto', 'hash', {...}, role='viewer')."""

    def _run(engine: str, op: str, payload: dict, role: str = "analyst", actor: str = "tester", actor_type: str = "human"):
        return services.registry.execute(engine, op, payload, ExecutionContext(actor=actor, role=role, actor_type=actor_type))

    return _run


@pytest.fixture
def client(tmp_path):
    app = create_app(make_settings(tmp_path), serve_frontend=False)
    with TestClient(app) as c:
        yield c
