"""Basic tests: backend serves the frontend static files at /ui."""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from backend.app import create_app


@pytest.fixture()
def client():
    return TestClient(create_app())


def test_ui_serves_index_html(client):
    resp = client.get("/ui/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "ga-panel" in resp.text


def test_ui_serves_css(client):
    resp = client.get("/ui/style.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


def test_ui_serves_js(client):
    resp = client.get("/ui/app.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]


def test_ui_html_references_style_and_script(client):
    resp = client.get("/ui/")
    body = resp.text
    assert "style.css" in body
    assert "app.js" in body


def test_ui_html_has_fab(client):
    resp = client.get("/ui/")
    assert 'id="ga-fab"' in resp.text


def test_ui_html_has_panel(client):
    resp = client.get("/ui/")
    assert 'id="ga-panel"' in resp.text


def test_ui_html_has_hero(client):
    resp = client.get("/ui/")
    assert 'id="ga-hero"' in resp.text


def test_frontend_dir_exists():
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    assert frontend.exists(), "frontend/ directory missing"
    assert (frontend / "index.html").exists()
    assert (frontend / "style.css").exists()
    assert (frontend / "app.js").exists()
