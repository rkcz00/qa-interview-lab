import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.e2e.test_auth_ui import check
from tests.e2e.test_learning_ui import signed_in, read_article
from tests.e2e.test_assessment_ui import request_post, incorrect_answers, confirm_answers


def article(page, topic_id, language="ru"):
    page.goto("/topics/" + topic_id + ("?language=en" if language == "en" else ""))
    expect(page.locator(".article-body")).to_be_visible()
    read_article(page)


def unlock(page, topic_id):
    article(page, topic_id)
    started = request_post(page.context, f"/api/v1/topics/{topic_id}/attempts/", {"language": "en"})
    check(started.status == 201, "Quiz start failed")
    identifier = started.json()["data"]["attempt_id"]
    check(request_post(page.context, f"/api/v1/attempts/{identifier}/submit/", {"language": "en", "answers": incorrect_answers(started.json()["data"])}).status == 200, "Quiz submit failed")


def begin(page, topic_id, language="ru"):
    page.goto(f"/topics/{topic_id}/practice" + ("?language=en" if language == "en" else ""))
    expect(page.get_by_role("button", name="Начать практику", exact=True)).to_be_enabled()
    page.get_by_role("button", name="Начать практику", exact=True).click()
    expect(page).to_have_url(re.compile(r"/practice-submissions/[0-9]+(?:\?language=en)?$"))
    expect(page.locator("#practice-answer")).to_be_enabled()
    return urlsplit(page.url).path.split("/")[-1]


def result(page, correct=True):
    expect(page.get_by_role("heading", name="Результат практики", exact=True)).to_be_visible()
    notice = page.locator(".practice-result .ui-notice")
    expect(notice).to_have_text("Верно" if correct else "Неверно")
    tone = "success" if correct else "error"
    expect(notice).to_have_attribute("data-tone", tone)
    check(notice.evaluate("""(node, tone) => {
        const probe = document.createElement('span');
        probe.style.color = 'var(--color-' + tone + ')';
        probe.style.backgroundColor = 'var(--color-' + tone + '-bg)';
        document.body.append(probe);
        const actual = getComputedStyle(node), expected = getComputedStyle(probe);
        const matches = actual.color === expected.color && actual.backgroundColor === expected.backgroundColor;
        probe.remove(); return matches;
    }""", tone), "Verdict must use the existing success/error palette")
    expect(page.locator("textarea")).to_have_count(0)
    expect(page.locator(".practice-task")).to_have_count(0)
    check(not any(key in page.locator("main").inner_text() for key in ("expected_answer", "task_snapshot", "source_revision", "submitted_answer")), "Private fields in UI")


@pytest.mark.parametrize("language,width,height", [("ru", 1280, 900), ("en", 390, 844)])
@pytest.mark.cross_browser
def test_article_test_practice_language_reload_keyboard_result_delete(auth_page, auth_app, practice_topics, language, width, height):
    page = auth_page
    page.set_viewport_size({"width": width, "height": height})
    signed_in(page)
    topic_id = practice_topics["enabled"]
    mutations = []
    def observe(request):
        path = urlsplit(request.url).path
        if request.method == "POST" and ("/practice/" in path or "/practice-submissions/" in path):
            keys = set(request.post_data_json)
            expected = {"language", "answer_text"} if path.endswith("/submit/") else set() if path.endswith("/delete/") else {"language"}
            check(keys == expected and bool(request.headers.get("x-csrftoken")), "Practice mutations need exact fields and CSRF")
            mutations.append(path)
    page.on("request", observe)
    article(page, topic_id, language)
    expect(page.locator(".practice-entry a")).to_be_visible()
    page.get_by_role("link", name="Пройти тест", exact=True).click()
    test_language = "en" if language == "ru" else "ru"
    if test_language == "en":
        page.get_by_role("radio", name="English", exact=True).check()
    page.get_by_role("button", name="Начать тест", exact=True).click()
    expect(page.locator(".question-card")).to_be_visible()
    confirm_answers(page)
    page.get_by_role("button", name="Завершить тест", exact=True).click()
    expect(page.get_by_role("heading", name="Результат теста", exact=True)).to_be_visible()
    entry = page.get_by_role("link", name="Открыть практику", exact=True)
    expect(entry).to_have_attribute("href", f"/topics/{topic_id}/practice" + ("?language=en" if language == "en" else ""))
    entry.click()
    page.get_by_role("button", name="Начать практику", exact=True).click()
    expect(page.locator("#practice-answer")).to_be_enabled()
    identifier = urlsplit(page.url).path.split("/")[-1]
    expect(page.get_by_role("heading", level=1)).to_be_focused()
    page.locator("#practice-answer").fill(" raw draft ")
    translated = "English" if language == "ru" else "Русский"
    control = page.get_by_role("radio", name=translated, exact=True)
    control.focus()
    # Test preserved keyboard focus without assuming mouse-click focus on WebKit.
    control.press("Space")
    expect(page.locator(".practice-task h2")).to_have_text("Practice: Python output" if translated == "English" else "Практика: вывод Python")
    expect(control).to_be_focused()
    expect(page.locator("#practice-answer")).to_have_value(" raw draft ")
    page.go_back()
    expect(page.locator(".practice-task h2")).to_have_text("Практика: вывод Python" if language == "ru" else "Practice: Python output")
    expect(page.locator("#practice-answer")).to_have_value(" raw draft ")
    page.go_forward()
    expect(page.locator(".practice-task h2")).to_have_text("Practice: Python output" if translated == "English" else "Практика: вывод Python")
    expect(page.locator("#practice-answer")).to_have_value(" raw draft ")
    check(page.evaluate("!window.qilPracticeInjected"), "Source must remain plain text")
    page.once("dialog", lambda dialog: dialog.accept())
    page.reload()
    expect(page.locator("#practice-answer")).to_have_value("")
    page.locator("#practice-answer").focus()
    page.keyboard.type("2")
    page.keyboard.press("Tab")
    expect(page.get_by_role("button", name="Отправить ответ", exact=True)).to_be_focused()
    page.keyboard.press("Enter")
    result(page)
    saved = page.context.request.get(f"/api/v1/practice-submissions/{identifier}/").json()["data"]
    repeated = request_post(page.context, f"/api/v1/practice-submissions/{identifier}/submit/",
                            {"language": saved["submitted_language"], "answer_text": " \r\n2 "})
    check(repeated.status == 200 and repeated.json()["data"] == saved, "Normalized repeat must preserve the result and date")
    changed = request_post(page.context, f"/api/v1/practice-submissions/{identifier}/submit/", {"language": saved["submitted_language"], "answer_text": "9"})
    check(changed.status == 409, "Changed submit must conflict")
    page.reload()
    result(page)
    before_progress = page.context.request.get("/api/v1/progress/").json()
    check(not any(row["mastered"] for row in before_progress["data"]), "Practice must not replace an 80-percent test")
    check(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile/desktop must not overflow")
    page.get_by_role("button", name="Удалить результат", exact=True).click()
    expect(page.get_by_role("button", name="Подтвердить удаление", exact=True)).to_be_focused()
    page.get_by_role("button", name="Отмена", exact=True).click()
    expect(page.get_by_role("button", name="Удалить результат", exact=True)).to_be_focused()
    page.get_by_role("button", name="Удалить результат", exact=True).click()
    page.get_by_role("button", name="Подтвердить удаление", exact=True).click()
    expect(page).to_have_url(re.compile(r"/topics/" + topic_id + r"/practice(?:\?language=en)?$"))
    check(page.context.request.get(f"/api/v1/practice-submissions/{identifier}/").status == 404, "Deleted submission must disappear")
    check(page.context.request.get("/api/v1/progress/").json() == before_progress, "Practice deletion must preserve progress")
    check(auth_app.practice_data("info", [topic_id])["submission_count"] == 0, "Only the owned work must be deleted")
    check(len(mutations) == 3, "UI must issue exactly start, submit and delete once")


def test_entry_hidden_for_disabled_or_draft_task_and_locked_preview_has_no_start(auth_page, practice_topics):
    page = auth_page
    signed_in(page)
    for key in ("disabled", "draft_task"):
        article(page, practice_topics[key])
        expect(page.get_by_role("link", name="Открыть практику", exact=True)).to_have_count(0)
        page.goto(f"/topics/{practice_topics[key]}/practice")
        expect(page.get_by_role("heading", name="Практика недоступна", exact=True)).to_be_visible()
    page.goto(f"/topics/{practice_topics['enabled']}/practice")
    expect(page.get_by_role("button", name="Начать практику", exact=True)).to_be_disabled()
    expect(page.get_by_text("Сначала дочитайте статью.", exact=True)).to_be_visible()
    check(request_post(page.context, f"/api/v1/topics/{practice_topics['enabled']}/practice/submissions/", {"language": "ru"}).status == 403, "Server must enforce prerequisites")


def test_incorrect_and_empty_answers_are_valid_ui_paths(auth_page, auth_app, practice_topics):
    page = auth_page
    signed_in(page)
    topic = practice_topics["enabled"]
    unlock(page, topic)
    begin(page, topic)
    expect(page.locator("#practice-answer")).not_to_have_attribute("required", "")
    page.get_by_role("button", name="Отправить ответ", exact=True).click()
    expect(page.get_by_text("Проверьте ответ: его формат или пустое значение не подходят заданию.", exact=True)).to_be_visible()
    expect(page.locator("#practice-answer")).to_be_focused()
    page.locator("#practice-answer").fill("wrong")
    page.get_by_role("button", name="Отправить ответ", exact=True).click()
    result(page, False)
    auth_app.practice_data("empty", [topic])
    begin(page, topic)
    expect(page.get_by_role("button", name="Отправить ответ", exact=True)).to_be_enabled()
    page.get_by_role("button", name="Отправить ответ", exact=True).click()
    result(page)


def test_conflict_loads_existing_result_without_overwriting(auth_page, practice_topics):
    page = auth_page
    signed_in(page)
    topic = practice_topics["enabled"]
    unlock(page, topic)
    identifier = begin(page, topic)
    page.locator("#practice-answer").fill("9")
    original = request_post(page.context, f"/api/v1/practice-submissions/{identifier}/submit/", {"language": "en", "answer_text": "2"})
    check(original.status == 200, "Competing submit must succeed")
    page.get_by_role("button", name="Отправить ответ", exact=True).click()
    result(page)
    expect(page.get_by_text("Работа уже отправлена с другим ответом. Показан сохранённый результат.", exact=True)).to_be_visible()
    check(page.context.request.get(f"/api/v1/practice-submissions/{identifier}/").json() == original.json(), "Conflict must not overwrite the saved result")


@pytest.mark.cross_browser
@pytest.mark.parametrize("size", [{"width": 1280, "height": 900}, {"width": 390, "height": 844}], ids=["desktop", "mobile"])
def test_network_failure_requires_get_and_explicit_same_payload_retry(auth_page, practice_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    signed_in(page)
    unlock(page, practice_topics["enabled"])
    identifier = begin(page, practice_topics["enabled"])
    calls = []
    def intercept(route):
        calls.append(route.request.post_data_json)
        if len(calls) == 1:
            route.abort("failed")
        else:
            route.continue_()
    page.route(f"**/api/v1/practice-submissions/{identifier}/submit/", intercept)
    page.locator("#practice-answer").fill(" 2 ")
    page.get_by_role("button", name="Отправить ответ", exact=True).click()
    expect(page.get_by_role("button", name="Повторить тот же ответ", exact=True)).to_be_enabled()
    check(len(calls) == 1, "There must be no automatic POST retry")
    page.get_by_role("button", name="Повторить тот же ответ", exact=True).click()
    result(page)
    check(len(calls) == 2 and calls[0] == calls[1], "Retry must preserve the frozen payload")


def test_lost_submit_and_delete_responses_are_resolved_without_repeating_posts(auth_page, practice_topics):
    page = auth_page
    signed_in(page)
    unlock(page, practice_topics["enabled"])
    identifier = begin(page, practice_topics["enabled"])
    counts = {"submit": 0, "delete": 0}
    def lost_response(route):
        action = "submit" if route.request.url.endswith("/submit/") else "delete"
        counts[action] += 1
        route.fetch()
        route.abort("failed")
    page.route(f"**/api/v1/practice-submissions/{identifier}/submit/", lost_response)
    page.route(f"**/api/v1/practice-submissions/{identifier}/delete/", lost_response)
    page.locator("#practice-answer").fill("2")
    page.get_by_role("button", name="Отправить ответ", exact=True).click()
    result(page)
    page.get_by_role("button", name="Удалить результат", exact=True).click()
    page.get_by_role("button", name="Подтвердить удаление", exact=True).click()
    expect(page.get_by_role("button", name="Начать практику", exact=True)).to_be_enabled()
    check(counts == {"submit": 1, "delete": 1}, "Lost response must not cause automatic duplicate writes")


def test_snapshot_after_unpublish_and_foreign_submission_remain_protected(auth_page, auth_browser, auth_app, practice_topics):
    page = auth_page
    signed_in(page)
    topic = practice_topics["enabled"]
    unlock(page, topic)
    identifier = begin(page, topic)
    auth_app.practice_data("draft", [topic])
    page.reload()
    expect(page.locator("#practice-answer")).to_be_enabled()
    page.locator("#practice-answer").fill("2")
    page.get_by_role("button", name="Отправить ответ", exact=True).click()
    result(page)
    other_context = auth_browser.new_context(base_url=auth_app.url)
    try:
        other = other_context.new_page()
        signed_in(other)
        other.goto(f"/practice-submissions/{identifier}")
        expect(other.get_by_role("heading", name="Практика недоступна", exact=True)).to_be_visible()
        check(other_context.request.get(f"/api/v1/practice-submissions/{identifier}/").status == 404, "B cannot read A's work")
        check(request_post(other_context, f"/api/v1/practice-submissions/{identifier}/delete/", {}).status == 404, "B cannot delete A's work")
    finally:
        other_context.close()
    page.get_by_role("button", name="Удалить результат", exact=True).click()
    page.get_by_role("button", name="Подтвердить удаление", exact=True).click()
    expect(page).to_have_url(re.compile(r"/$"))


def test_unicode_limit_unsaved_leave_and_safe_decoder_errors(auth_page, practice_topics):
    page = auth_page
    signed_in(page)
    unlock(page, practice_topics["enabled"])
    identifier = begin(page, practice_topics["enabled"])
    page.locator("#practice-answer").fill("😀" * 5000)
    expect(page.get_by_text("5000 / 5000", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Отправить ответ", exact=True)).to_be_enabled()
    page.locator("#practice-answer").fill("😀" * 5001)
    expect(page.get_by_role("button", name="Отправить ответ", exact=True)).to_be_disabled()
    page.locator("#practice-answer").fill("draft")
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("link", name="QA Interview Lab", exact=True).click()
    expect(page).to_have_url(re.compile(r"/practice-submissions/" + identifier + r"$"))
    expect(page.locator("#practice-answer")).to_have_value("draft")
    with page.expect_event("dialog") as leaving:
        page.evaluate("setTimeout(() => history.back(), 0)")
    leaving.value.dismiss()
    expect(page).to_have_url(re.compile(r"/practice-submissions/" + identifier + r"$"))
    expect(page.locator("#practice-answer")).to_have_value("draft")
    page.locator("#practice-answer").fill("")
    def malformed(route):
        response = route.fetch()
        payload = response.json()
        payload["data"]["task"]["expected_answer"] = "PRIVATE_TEST_REFERENCE"
        route.fulfill(response=response, json=payload)
    page.route(f"**/api/v1/practice-submissions/{identifier}/**", malformed)
    page.reload()
    expect(page.get_by_text("Не удалось загрузить практику. Попробуйте ещё раз.", exact=True)).to_be_visible()
    check("PRIVATE_TEST_REFERENCE" not in page.locator("body").inner_text(), "Private fields must fail decoding without rendering")


@pytest.mark.parametrize("language,width,height", [("ru", 1280, 900), ("en", 390, 844)])
@pytest.mark.parametrize("first_answer,first_correct", [("wrong", False), ("2", True)])
@pytest.mark.cross_browser
def test_restart_opens_empty_work_preserves_result_language_and_progress(auth_page, auth_app, practice_topics, language, width, height, first_answer, first_correct):
    page = auth_page
    page.set_viewport_size({"width": width, "height": height})
    signed_in(page)
    topic = practice_topics["enabled"]
    unlock(page, topic)
    identifier = begin(page, topic, language)
    page.locator("#practice-answer").fill(first_answer)
    page.get_by_role("button", name="Отправить ответ", exact=True).click()
    result(page, first_correct)
    saved = page.context.request.get(f"/api/v1/practice-submissions/{identifier}/").json()
    progress = page.context.request.get("/api/v1/progress/").json()
    held = []
    starts = []
    path = f"/api/v1/topics/{topic}/practice/submissions/"
    def hold(route):
        starts.append(route.request)
        held.append(route)
    page.route("**" + path, hold)
    page.get_by_role("button", name="Пройти заново", exact=True).click()
    expect(page.get_by_role("button", name="Начинаем заново…", exact=True)).to_be_disabled()
    result(page, first_correct)
    check(len(held) == 1, "Restart must send only one start request")
    check(starts[0].post_data_json == {"language": language} and bool(starts[0].headers.get("x-csrftoken")), "Restart needs only language and CSRF")
    with page.expect_response(lambda response: response.url.endswith(path) and response.request.method == "POST") as restarted:
        held[0].continue_()
    check(restarted.value.status == 201, "Restart must create a new work")
    new_id = restarted.value.json()["data"]["submission_id"]
    check(new_id != identifier, "Restart must have its own stable ID")
    expect(page).to_have_url(re.compile(r"/practice-submissions/" + new_id + (r"\?language=en$" if language == "en" else r"$")))
    expect(page.locator("#practice-answer")).to_be_enabled()
    expect(page.locator("#practice-answer")).to_have_value("")
    expect(page.get_by_role("heading", level=1)).to_be_focused()
    expect(page.locator(".practice-task h2")).to_have_text("Practice: Python output" if language == "en" else "Практика: вывод Python")
    check(page.context.request.get(f"/api/v1/practice-submissions/{identifier}/").json() == saved, "Old result must remain unchanged")
    check(auth_app.practice_data("info", [topic])["submission_count"] == 2, "Restart must preserve the previous work")
    page.locator("#practice-answer").fill("2" if not first_correct else "wrong")
    page.get_by_role("button", name="Отправить ответ", exact=True).click()
    result(page, not first_correct)
    page.go_back()
    expect(page).to_have_url(re.compile(r"/practice-submissions/" + identifier + (r"\?language=en$" if language == "en" else r"$")))
    result(page, first_correct)
    check(page.context.request.get(f"/api/v1/practice-submissions/{identifier}/").json() == saved, "Back must restore the saved old result")
    check(page.context.request.get("/api/v1/progress/").json() == progress, "Restart must not change progress")
    check(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Restart/result must fit desktop and mobile")
    check(len(starts) == 1, "No extra restart is allowed from reload or Back")


def test_restart_after_unpublish_keeps_result_without_creating_work(auth_page, auth_app, practice_topics):
    page = auth_page
    signed_in(page)
    topic = practice_topics["enabled"]
    unlock(page, topic)
    identifier = begin(page, topic)
    page.locator("#practice-answer").fill("2")
    page.get_by_role("button", name="Отправить ответ", exact=True).click()
    result(page)
    saved = page.context.request.get(f"/api/v1/practice-submissions/{identifier}/").json()
    auth_app.practice_data("draft", [topic])
    with page.expect_response(lambda response: response.url.endswith(f"/api/v1/topics/{topic}/practice/submissions/")) as restarted:
        page.get_by_role("button", name="Пройти заново", exact=True).click()
    check(restarted.value.status == 404, "Unpublished topic cannot start a new work")
    expect(page.get_by_text("Новую работу сейчас начать нельзя. Тема или задание недоступны либо не выполнены условия доступа.", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Пройти заново", exact=True)).to_be_disabled()
    result(page)
    check(page.context.request.get(f"/api/v1/practice-submissions/{identifier}/").json() == saved, "Unavailable restart must preserve saved result")
    check(auth_app.practice_data("info", [topic])["submission_count"] == 1, "Failed restart must not create or delete work")


def test_lost_restart_response_warns_before_an_explicit_new_start(auth_page, auth_app, practice_topics):
    page = auth_page
    signed_in(page)
    topic = practice_topics["enabled"]
    unlock(page, topic)
    identifier = begin(page, topic)
    page.locator("#practice-answer").fill("wrong")
    page.get_by_role("button", name="Отправить ответ", exact=True).click()
    result(page, False)
    saved = page.context.request.get(f"/api/v1/practice-submissions/{identifier}/").json()
    starts = []
    def lost(route):
        starts.append(route.request)
        if len(starts) == 1:
            response = route.fetch()
            check(response.status == 201, "First restart reaches the real backend")
            route.abort("failed")
        else:
            route.continue_()
    page.route(f"**/api/v1/topics/{topic}/practice/submissions/", lost)
    page.get_by_role("button", name="Пройти заново", exact=True).click()
    expect(page.get_by_text("Ответ о начале не получен. Работа могла быть создана. Новый явный запуск может создать ещё одну работу.", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Начать новую работу", exact=True)).to_be_enabled()
    result(page, False)
    check(len(starts) == 1, "Lost restart response must not cause an automatic POST")
    check(auth_app.practice_data("info", [topic])["submission_count"] == 2, "Unknown created work and the old result are preserved")
    page.get_by_role("button", name="Начать новую работу", exact=True).click()
    expect(page.locator("#practice-answer")).to_be_enabled()
    expect(page.locator("#practice-answer")).to_have_value("")
    check(len(starts) == 2, "Only the explicit warned action may start another work")
    check(page.context.request.get(f"/api/v1/practice-submissions/{identifier}/").json() == saved, "Old result is never removed by restart")
