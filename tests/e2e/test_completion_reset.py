"""Real reset API with the existing UI: stale end markers/drafts cannot restore progress."""
import re
from time import monotonic
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from tests.e2e.test_assessment_ui import begin, request_post
from tests.e2e.test_auth_ui import check
from tests.e2e.test_learning_ui import signed_in, topic_page


@pytest.mark.cross_browser
@pytest.mark.parametrize("size", [{"width": 1280, "height": 900}, {"width": 390, "height": 844}], ids=["desktop", "mobile"])
def test_reset_rejects_held_read_clears_two_tabs_and_requires_explicit_reopening(auth_page, auth_app, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    signed_in(page)
    topic_id = learning_topics["first"]
    auth_app.learning_data("long_article", [topic_id])
    held, generations = [], []

    def intercept(route):
        generations.append(route.request.headers.get("x-progress-generation"))
        if len(generations) == 1:
            held.append(route)
        else:
            route.continue_()

    page.route("**/api/v1/topics/" + topic_id + "/sections/*/read/", intercept)
    topic_page(page, topic_id)
    page.locator(".article-end").scroll_into_view_if_needed()
    expect(page.locator(".reading-card .ui-loading")).to_have_text("Сохраняем отметку…")
    deadline = monotonic() + 8
    while not held and monotonic() < deadline:
        page.wait_for_timeout(25)
    check(len(held) == 1, "The first automatic read must be held before reset")

    sibling = page.context.new_page()
    try:
        sibling.set_viewport_size(size)
        identifier = begin(sibling, topic_id)
        sibling.locator(".question-card input").first.check()
        # Its AppShell has loaded progress and opened the client's signal channel.
        expect(sibling.locator(".overall-percentage")).to_be_visible()
        reset = request_post(page.context, "/api/v1/progress/reset/", {
            "confirmation": "reset_all_progress", "request_id": str(uuid4()),
        })
        check(reset.status == 200 and reset.json() == {"data": {"progress_generation": "2"}}, "Reset API must commit generation two")
        held[0].continue_()
        expect(page).to_have_url(re.compile(r"/progress$"))
        expect(sibling).to_have_url(re.compile(r"/progress$"))
        expect(sibling.locator(".question-card")).to_have_count(0)
        check(len(generations) == 1, "Old end marker must not replay the rejected POST")
        current = page.context.request.get("/api/v1/completion-progress/")
        check(current.status == 200 and current.json()["data"]["overall_completion_progress"] == 0,
              "Reset must not recreate progress from old UI state")
        check(page.context.request.get("/api/v1/attempts/" + identifier + "/").status == 404, "The removed work must stay unavailable")

        page.bring_to_front()
        topic_page(page, topic_id)
        page.locator(".article-end").scroll_into_view_if_needed()
        expect(page.locator(".reading-card .ui-notice--success")).to_have_text("Статья отмечена прочитанной.")
        check(generations == ["1", "2"], "Only explicit reopening may read under the new generation")
        check(page.context.request.get("/api/v1/progress/").json()["data"][0]["article_read_at"] is not None,
              "New explicit reading must save a new first mark")
    finally:
        sibling.close()
