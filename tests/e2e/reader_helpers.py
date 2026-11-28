"""Navigation helpers use the public section API, never a legacy concatenated body."""
from time import monotonic

from playwright.sync_api import expect
from tests.e2e.test_auth_ui import check


def reading(context, topic_id, language="ru"):
    response = context.request.get("/api/v1/topics/" + topic_id + "/reading/?language=" + language)
    check(response.status == 200, "Owned reading metadata must be available")
    return response.json()["data"]


def contents(page, topic_id, language="ru"):
    path = "/topics/" + topic_id + ("?language=en" if language == "en" else "")
    response = page.goto(path)
    check(response is not None and response.status in (200, 304), "Contents SPA route must load")
    expect(page.locator(".section-navigation")).to_be_visible()
    expect(page.locator(".article-body,.article-end")).to_have_count(0)


def open_reader(page, topic_id, language="ru", section_id=None):
    metadata = reading(page.context, topic_id, language)
    section_id = section_id or metadata["sections"][0]["section_id"]
    section = next(row for row in metadata["sections"] if row["section_id"] == section_id)
    path = "/topics/" + topic_id + "/sections/" + section_id + ("?language=en" if language == "en" else "")
    check(page.request.get(path, headers={"Cache-Control": "no-cache"}).status == 200, "Direct section SPA route must return HTTP 200")
    response = page.goto(path)
    check(response is not None and response.status in (200, 304), "Reader route must load or revalidate")
    expect(page.locator("main h1")).to_have_text(section["title"])
    expect(page.locator(".article-body")).to_be_visible()
    expect(page.locator(".article-end")).to_have_count(1)


def read_current(page, topic_id, section_id):
    page.locator(".article-end").scroll_into_view_if_needed()
    deadline = monotonic() + 10
    while True:
        metadata = reading(page.context, topic_id)
        if any(row["section_id"] == section_id and row["read_at"] is not None for row in metadata["sections"]):
            return metadata
        check(monotonic() < deadline, "Visible section end must be saved")
        page.wait_for_timeout(25)
