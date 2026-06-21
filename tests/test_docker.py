"""M10 — validate docker-compose.yml, Dockerfile, and /config endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from backend.app import create_app

ROOT = Path(__file__).resolve().parents[1]


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    return TestClient(create_app())


@pytest.fixture()
def compose() -> dict:
    path = ROOT / "docker-compose.yml"
    with open(path) as f:
        return yaml.safe_load(f)


# ── docker-compose.yml structure ──────────────────────────────────────────────

def test_compose_file_exists():
    assert (ROOT / "docker-compose.yml").exists()


def test_compose_has_backend_service(compose):
    assert "backend" in compose["services"]


def test_compose_has_forgecad_studio_service(compose):
    assert "forgecad-studio" in compose["services"]


def test_compose_backend_port(compose):
    ports = compose["services"]["backend"]["ports"]
    assert any("8001" in str(p) for p in ports)


def test_compose_forgecad_port(compose):
    ports = compose["services"]["forgecad-studio"]["ports"]
    assert any("4000" in str(p) for p in ports)


def test_compose_forgecad_is_studio_profile(compose):
    profiles = compose["services"]["forgecad-studio"].get("profiles", [])
    assert "studio" in profiles


def test_compose_backend_has_healthcheck(compose):
    hc = compose["services"]["backend"].get("healthcheck")
    assert hc is not None
    assert "/health" in str(hc["test"])


def test_compose_backend_passes_forgecad_studio_url(compose):
    env = compose["services"]["backend"].get("environment", {})
    # May be a dict or a list of "KEY=VAL" strings
    if isinstance(env, dict):
        keys = set(env.keys())
    else:
        keys = {e.split("=")[0] for e in env}
    assert "FORGECAD_STUDIO_URL" in keys


# ── Dockerfile structure ──────────────────────────────────────────────────────

def test_dockerfile_exists():
    assert (ROOT / "Dockerfile").exists()


def test_dockerfile_uses_python312():
    text = (ROOT / "Dockerfile").read_text()
    assert "python:3.12" in text


def test_dockerfile_exposes_8001():
    text = (ROOT / "Dockerfile").read_text()
    assert "EXPOSE 8001" in text


def test_dockerfile_has_healthcheck():
    text = (ROOT / "Dockerfile").read_text()
    assert "HEALTHCHECK" in text


def test_dockerignore_excludes_env():
    text = (ROOT / ".dockerignore").read_text()
    assert ".env" in text


def test_dockerignore_excludes_venv():
    text = (ROOT / ".dockerignore").read_text()
    assert ".venv" in text


# ── /config endpoint ──────────────────────────────────────────────────────────

def test_config_endpoint_returns_200(client):
    resp = client.get("/config")
    assert resp.status_code == 200


def test_config_endpoint_has_forgecad_studio_url_key(client):
    body = client.get("/config").json()
    assert "forgecad_studio_url" in body


def test_config_endpoint_has_backend_url_key(client):
    body = client.get("/config").json()
    assert "backend_url" in body


def test_config_endpoint_forgecad_url_from_env(client, monkeypatch):
    monkeypatch.setenv("FORGECAD_STUDIO_URL", "http://studio.test:4000")
    body = client.get("/config").json()
    assert body["forgecad_studio_url"] == "http://studio.test:4000"


def test_config_endpoint_empty_when_unset(client, monkeypatch):
    monkeypatch.delenv("FORGECAD_STUDIO_URL", raising=False)
    body = client.get("/config").json()
    assert body["forgecad_studio_url"] == ""
