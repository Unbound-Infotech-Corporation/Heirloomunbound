"""Memory Studio v1 — owner-only surface, reuse existing APIs, no heir exposure."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def test_memory_route_is_inside_owner_layout():
    app = (FRONTEND / "App.js").read_text(encoding="utf-8")
    assert 'path="/memory"' in app
    assert "element={<Memory />}" in app
    # Public heir portal stays a sibling route, not inside AppLayout.
    heir_idx = app.index('path="/heir/:token"')
    memory_idx = app.index('path="/memory"')
    layout_idx = app.index("<AppLayout />")
    assert heir_idx < layout_idx < memory_idx


def test_heir_portal_has_no_memory_studio():
    portal = (FRONTEND / "pages" / "HeirPortal.jsx").read_text(encoding="utf-8")
    assert "/memory" not in portal
    assert "/studio/memory" not in portal
    assert "/memory/facts" not in portal
    assert "/auth/me/preferences" not in portal
    assert "Memory Studio" not in portal
    assert "nav-memory" not in portal


def test_sit_twin_settings_link_to_memory_studio():
    owner = (FRONTEND / "pages" / "Owner.jsx").read_text(encoding="utf-8")
    twin = (FRONTEND / "pages" / "Twin.jsx").read_text(encoding="utf-8")
    settings = (FRONTEND / "pages" / "Settings.jsx").read_text(encoding="utf-8")
    layout = (FRONTEND / "components" / "AppLayout.jsx").read_text(encoding="utf-8")
    assert 'to="/memory"' in owner
    assert 'data-testid="owner-link-memory"' in owner
    assert 'to="/memory"' in twin
    assert 'data-testid="twin-link-memory"' in twin
    assert 'to="/memory"' in settings
    assert 'data-testid="settings-memory-studio-link"' in settings
    assert 'to: "/memory"' in layout
    assert 'tid: "nav-memory"' in layout


def test_memory_page_reuses_existing_endpoints():
    page = (FRONTEND / "pages" / "Memory.jsx").read_text(encoding="utf-8")
    assert 'api.get("/memory/facts")' in page
    assert "api.delete(`/memory/facts/${factId}`)" in page
    assert 'api.get("/auth/me")' in page
    assert 'api.put("/auth/me/preferences"' in page
    assert "biography" not in page.lower()
    assert 'data-testid="memory-facts-empty"' in page or "HeldFactsList" in page
    assert 'data-testid="memory-studio-root"' in page


def test_memory_router_still_scopes_facts_to_session_user():
    src = (ROOT / "backend" / "routers" / "memory.py").read_text(encoding="utf-8")
    assert "Depends(get_current_user)" in src
    assert 'delete_one(\n        {"fact_id": fact_id, "user_id": user["user_id"]}' in src
    assert 'find({"user_id": user["user_id"]}' in src
