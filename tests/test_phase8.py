import pytest
import re
from pathlib import Path
from fastapi.testclient import TestClient
from backend.main import app
from backend.app.core.config import settings

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

def test_dashboard_root_html_serving(client):
    """Verify that /dashboard/ serves the index.html with correct headers and title."""
    response = client.get("/dashboard/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html_content = response.text
    assert "<title>Google Photos AI Discovery Engine" in html_content
    assert "Cognitive Retrieval Intelligence" in html_content
    # Check core structural anchors
    assert 'id="val-total-conversations"' in html_content
    assert 'id="journey-flow-container"' in html_content
    assert 'id="problems-grid"' in html_content
    assert 'id="discovery-cards-grid"' in html_content
    assert 'id="report-accordion"' in html_content
    assert 'id="evidence-drawer"' in html_content
    assert 'id="pipeline-modal-overlay"' in html_content

def test_dashboard_static_assets_serving(client):
    """Verify that style.css and app.js are served with correct MIME types and content."""
    # CSS
    r_css = client.get("/dashboard/style.css")
    assert r_css.status_code == 200
    assert "text/css" in r_css.headers["content-type"]
    assert "--bg-primary: #090d16" in r_css.text

    # JavaScript
    r_js = client.get("/dashboard/app.js")
    assert r_js.status_code == 200
    assert any(mime in r_js.headers["content-type"] for mime in ["javascript", "application/x-javascript", "text/javascript"])
    assert "API_BASE = '/api/v1'" in r_js.text
    assert "renderJourneyFlow" in r_js.text

def test_root_content_negotiation(client):
    """Verify browser navigation redirects to /dashboard/ while API clients receive JSON."""
    # Browser client requesting text/html
    r_browser = client.get("/", headers={"accept": "text/html,application/xhtml+xml"}, follow_redirects=False)
    assert r_browser.status_code in (302, 307)
    assert r_browser.headers["location"] == "/dashboard/"

    # API client
    r_api = client.get("/", headers={"accept": "application/json"})
    assert r_api.status_code == 200
    data = r_api.json()
    assert "engine" in data
    assert data["dashboard"] == "/dashboard/"

def test_frontend_dom_contract_alignment():
    """Verify that every getElementById call in app.js has a matching id in index.html."""
    app_js_path = settings.FRONTEND_DIR / "app.js"
    index_html_path = settings.FRONTEND_DIR / "index.html"
    
    assert app_js_path.exists(), "frontend/app.js must exist"
    assert index_html_path.exists(), "frontend/index.html must exist"

    js_code = app_js_path.read_text(encoding="utf-8")
    html_code = index_html_path.read_text(encoding="utf-8")

    # Extract all document.getElementById('...') calls
    js_ids = set(re.findall(r"document\.getElementById\(['\"]([^'\"]+)['\"]\)", js_code))
    # Extract all id="..." in index.html
    html_ids = set(re.findall(r'id=["\']([^"\']+)["\']', html_code))

    missing_ids = js_ids - html_ids
    assert not missing_ids, f"app.js references DOM IDs missing in index.html: {missing_ids}"
