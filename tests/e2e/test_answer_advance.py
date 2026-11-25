"""Answer advances once locally, with a prefilled next question over real HTTP."""
import pytest
from playwright.sync_api import expect

from tests.e2e.test_auth_ui import check
from tests.e2e.test_learning_ui import signed_in
from tests.e2e.test_assessment_ui import begin, result


pytestmark = pytest.mark.cross_browser


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("activation", ["Enter", "Space"])
@pytest.mark.parametrize("size", [{"width": 1280, "height": 900}, {"width": 390, "height": 844}], ids=["desktop", "mobile"])
def test_answer_double_click_back_edit_language_focus_and_explicit_finish(auth_page, auth_app, learning_topics, size, language, activation):
    page = auth_page
    page.set_viewport_size(size)
    topic = learning_topics["first"]
    check(auth_app.learning_data("three_questions", [topic])["three_questions"] == "PASS", "Own three-question fixture")
    signed_in(page)
    begin(page, topic, language)
    posts = []
    page.on("request", lambda request: posts.append(1) if request.method == "POST" and request.url.endswith("/submit/") else None)
    following = page.get_by_role("button", name="Следующий вопрос", exact=True)
    previous = page.get_by_role("button", name="Предыдущий вопрос", exact=True)
    answer = page.get_by_role("button", name="Ответить", exact=True)
    finish = page.get_by_role("button", name="Завершить тест", exact=True)

    # All three questions are prefilled, so an unintended second advance would be observable.
    options = page.locator(".question-card input")
    options.nth(0).check()
    options.nth(1).check()
    following.click()
    options.nth(0).check()
    following.click()
    options.nth(0).check()
    previous.click()
    previous.click()
    page.evaluate("""() => {
        const heading = document.querySelector('.question-card h2');
        const answer = document.querySelector('.question-navigation button:nth-child(2)');
        const sequence = [];
        const record = event => {
            if (event.target === heading) sequence.push('heading');
            if (event.target === answer) sequence.push('answer');
        };
        const leaving = event => {
            if (event.target === heading) sequence.push('left-heading');
        };
        document.addEventListener('focusin', record);
        document.addEventListener('focusout', leaving);
        window.answerFocusSequence = () => {
            document.removeEventListener('focusin', record);
            document.removeEventListener('focusout', leaving);
            return sequence;
        };
    }""")
    answer.dblclick(delay=80)
    expect(page.locator(".question-card legend")).to_have_text("Вопрос 2 из 3")
    expect(page.locator(".question-card h2")).to_be_focused()
    focus_sequence = page.evaluate("window.answerFocusSequence()")
    check("heading" in focus_sequence and "answer" not in focus_sequence[focus_sequence.index("heading") + 1:],
          "Repeated Answer mousedown must not take focus back from the new heading")
    check("left-heading" not in focus_sequence[focus_sequence.index("heading") + 1:],
          "Repeated Answer must not blur the new heading, including to the document body")
    expect(options.nth(0)).to_be_checked()
    expect(page.locator("#answer-confirmation")).to_have_text("Ответ ещё не подтверждён.")
    expect(finish).to_have_count(0)
    check(posts == [], "Double Answer must not submit")

    answer.focus()
    page.keyboard.press(activation)
    expect(page.locator(".question-card legend")).to_have_text("Вопрос 3 из 3")
    expect(page.locator(".question-card h2")).to_be_focused()
    expect(finish).to_have_count(0)
    answer.dblclick(delay=80)
    expect(page.locator(".question-card legend")).to_have_text("Вопрос 3 из 3")
    expect(finish).to_be_enabled()
    check(posts == [], "The last Answer is local, including double click")

    previous.click()
    previous.click()
    options.nth(1).uncheck()
    expect(page.locator("#answer-confirmation")).to_have_text("Ответ ещё не подтверждён.")
    expect(page.get_by_text("Подтверждено ответов: 2 из 3", exact=True)).to_be_visible()
    options.nth(1).check()
    answer.click()
    expect(page.locator(".question-card legend")).to_have_text("Вопрос 2 из 3")
    expect(page.locator(".question-card h2")).to_be_focused()
    expect(page.locator("#answer-confirmation")).to_have_text("Ответ подтверждён.")

    other = "en" if language == "ru" else "ru"
    language_control = page.get_by_role("radio", name="English" if other == "en" else "Русский", exact=True)
    language_control.focus()
    language_control.check()
    expect(language_control).to_be_focused()
    expect(page.locator(".question-card legend")).to_have_text("Вопрос 2 из 3")
    expect(options.nth(0)).to_be_checked()
    page.go_back()
    expect(page.get_by_role("radio", name="Русский" if language == "ru" else "English", exact=True)).to_be_checked()
    page.go_forward()
    expect(language_control).to_be_checked()
    expect(page.locator("#answer-confirmation")).to_have_text("Ответ подтверждён.")
    answer.click()
    expect(page.locator(".question-card h2")).to_have_text(other + " question 30")
    expect(page.locator(".question-card h2")).to_be_focused()
    expect(finish).to_be_enabled()
    check(posts == [], "No automatic submit after navigation or Answer")
    check(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Flow fits the viewport")
    finish.click()
    result(page, "3", "3", "100%")
    check(len(posts) == 1, "Only explicit Finish submits")
