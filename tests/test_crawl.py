"""The existing crawler still extracts pages and elements without following links."""

import pytest

from qctool.ui.crawl import crawl
from tests.test_explore import browser_required, exploration_site, _state


@pytest.mark.playwright
@browser_required
def test_existing_crawl_behavior(exploration_site):
    site, counts, _ = exploration_site
    before = dict(counts)
    ui = crawl(site, anonymous_paths=["/login"], follow_links=False, wait_ms=500)
    assert len(ui.pages) == 1
    assert ui.pages[0].url == site + "/login"
    assert any(element.test_id == "btn-login" for element in ui.pages[0].elements)
    assert counts == before


@pytest.mark.playwright
@browser_required
def test_anonymous_redirect_does_not_skip_authenticated_route(exploration_site, tmp_path):
    from qctool.executability import analyze_executability
    from qctool.resolution_context import build_resolution_context
    from qctool.testcase import Step, StepKind, TestCase

    site, counts, _ = exploration_site
    state = _state(tmp_path, site)
    original_state = state.read_bytes()
    original_counts = dict(counts)
    progress = []
    ui = crawl(site, anonymous_paths=["/protected", "/protected"],
               extra_paths=["/protected", "/protected"], storage_state=state,
               follow_links=False, wait_ms=500, on_progress=progress.append)
    assert [page.url for page in ui.pages] == [site + "/login", site + "/protected"]
    assert sum(message == f"  mở {site}/protected" for message in progress) == 2
    assert any(element.test_id == "profile" for element in ui.pages[-1].elements)
    assert state.read_bytes() == original_state
    assert counts == original_counts  # no clicks, submissions or link following
    case = TestCase("TC_ACCOUNT_001", "ACCOUNT", "Account", "View account", steps=[
        Step(1, StepKind.WHEN, "perform.unmapped", {"description": "Open /protected"}),
        Step(2, StepKind.THEN, "assert.unmapped", {"expected": "Account visible"}),
    ])
    context = build_resolution_context(case, analyze_executability(case).gaps, ui_map=ui)
    assert [page["url"] for page in context.observations["ui_pages"]] == [site + "/protected"]
    assert any(element["test_id"] == "profile"
               for element in context.observations["ui_pages"][0]["elements"])
