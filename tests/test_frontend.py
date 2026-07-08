"""Frontend contract tests for the single-file React + Tailwind UI.

The UI is one self-contained ``frontend/index.html`` (React 18 UMD +
Babel-standalone + Tailwind, all via CDN — no build step). Because the JSX
source ships inside the served HTML, we can assert on its string literals:
the hero copy, the four nav controls, and the gated-handoff state.
"""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from backend.app import create_app


@pytest.fixture()
def client():
    return TestClient(create_app())


def test_frontend_dir_exists():
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    assert frontend.exists(), "frontend/ directory missing"
    assert (frontend / "index.html").exists()


def test_ui_serves_index_html(client):
    resp = client.get("/ui/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_ui_has_hero_text(client):
    resp = client.get("/ui/")
    assert "What can I design for you" in resp.text


def test_ui_loads_react_and_babel(client):
    body = client.get("/ui/").text
    assert "react@18" in body
    assert "babel" in body.lower()


def test_ui_loads_tailwind(client):
    body = client.get("/ui/").text
    assert "tailwindcss" in body


def test_ui_has_all_four_nav_controls(client):
    body = client.get("/ui/").text
    assert "Previous Run" in body
    assert "New Run" in body
    assert "Temporal UI" in body
    assert "Handoff to ForgeCAD" in body


def test_ui_has_cancel_control(client):
    body = client.get("/ui/").text
    assert "Cancel" in body


def test_ui_handoff_defaults_gated(client):
    """Handoff must start disabled and only enable after a success event."""
    body = client.get("/ui/").text
    # State flag that gates the Handoff button, initialised false.
    assert "canHandoff" in body
    assert "useState(false)" in body


def test_ui_persists_design_id_in_localstorage(client):
    body = client.get("/ui/").text
    assert "localStorage" in body
