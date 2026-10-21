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
