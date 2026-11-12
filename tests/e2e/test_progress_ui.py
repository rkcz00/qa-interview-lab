import os
from pathlib import Path
import re

from playwright.sync_api import expect
import pytest

from tests.e2e.test_auth_ui import check, fill, post, seed, LOGIN
from tests.e2e.test_learning_ui import signed_in
from tests.e2e.test_assessment_ui import request_post, result


def open_progress(page):
    page.goto('/progress')
    expect(page.get_by_role('button', name='Обновить прогресс', exact=True)).to_be_enabled()


def complete(context, topic_id, language='ru', correct=True):
    response = request_post(context, '/api/v1/topics/' + topic_id + '/attempts/', {'language': language})
    check(response.status == 201, 'Real attempt start failed')
    attempt = response.json()['data']
    answers = []
    if correct:
        for question in attempt['questions']:
            positions = {10, 20} if question['question_type'] == 'multiple_choice' else {10}
            answers.append({'question_id': question['question_id'],
                            'choice_ids': [choice['choice_id'] for choice in question['choices'] if choice['position'] in positions]})
    submitted = request_post(context, '/api/v1/attempts/' + attempt['attempt_id'] + '/submit/', {'language': language, 'answers': answers})
    check(submitted.status == 200, 'Real attempt submit failed')
    return attempt['attempt_id']


def card(page, topic_id):
    return page.locator('.topic-progress-list [data-topic-id="' + topic_id + '"]')


def test_guest_progress_returns_after_real_login_without_redirect_parameters(auth_page):
    page = auth_page
    email, password = seed(page.context)
    page.goto('/progress')
    expect(page).to_have_url(re.compile(r'/login$'))
    fill(page, email, password)
    page.get_by_role('button', name='Войти', exact=True).click()
    expect(page).to_have_url(re.compile(r'/progress$'))
    expect(page.get_by_text('Пока нет сохранённого прогресса.', exact=True)).to_be_visible()
    expect(page.get_by_text('Тем для отображения пока нет.', exact=True)).to_be_visible()
    expect(page.get_by_text('Завершённых попыток пока нет.', exact=True)).to_be_visible()


def test_published_untouched_topics_are_unread_without_invented_results(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    open_progress(page)
    expect(page.locator('.topic-progress-list h3')).to_have_text(['Основы тестирования', 'Автоматизация'])
    for topic_id in [learning_topics['first'], learning_topics['second']]:
        expect(card(page, topic_id).locator('dd')).to_have_text(['Не прочитано', 'Ещё не освоена', 'Нет завершённых попыток'])
    expect(page.locator('.attempt-history-list')).to_have_count(0)
    topic_link = page.get_by_role('link', name='Основы тестирования', exact=True)
    topic_link.focus()
    topic_link.press('Enter')
    expect(page).to_have_url(re.compile('/topics/' + learning_topics['first'] + '$'))
    page.go_back()
    expect(page.get_by_role('button', name='Обновить прогресс', exact=True)).to_be_enabled()
    page.go_forward()
    expect(page.locator('.article-body')).to_be_visible()


def test_progress_and_bilingual_history_use_real_saved_results_and_restore_navigation(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics['first']
    check(request_post(page.context, '/api/v1/topics/' + topic_id + '/read/', {}).status == 200, 'Read mark failed')
    first = complete(page.context, topic_id, 'en')
    second = complete(page.context, topic_id, 'ru', correct=False)
    open_progress(page)
    expect(card(page, topic_id).locator('dd')).to_have_text(['Прочитано', 'Освоена', '2 из 2 (100%)'])
    history = page.locator('.attempt-history-list > li')
    expect(history).to_have_count(2)
    check(history.first.get_attribute('data-attempt-id') == second, 'History must retain server newest-first order')
    expect(history.locator('h3')).to_have_text(['Основы тестирования', 'Testing foundations'])
    expect(history.nth(0).locator('dd').nth(1)).to_have_text('Русский')
    expect(history.nth(1).locator('dd').nth(1)).to_have_text('English')
    expect(history.nth(0).locator('dd').nth(4)).to_have_text('0%')
    expect(history.nth(1).locator('dd').nth(4)).to_have_text('100%')
    check(bool(history.first.locator('time').get_attribute('datetime')), 'History needs machine-readable date')
    expect(page.get_by_text('Дата и время показаны по часовому поясу браузера.', exact=True)).to_be_visible()
    expect(page.locator('.question-card')).to_have_count(0)
    history.nth(1).get_by_role('link', name='Открыть сохранённый результат', exact=True).click()
    expect(page).to_have_url(re.compile('/attempts/' + first + r'\?language=en$'))
    result(page)
    page.go_back()
    expect(page.locator('.attempt-history-list > li')).to_have_count(2)
    page.reload()
    expect(card(page, topic_id).locator('dd')).to_have_text(['Прочитано', 'Освоена', '2 из 2 (100%)'])
    check(auth_app.learning_data('info', [topic_id])['submitted_count'] == 2, 'Viewing results must not submit or create history')

    directory = os.environ.get('QIL_PROGRESS_VISUAL_DIR')
    if directory:
        target = Path(directory).resolve()
        check(target.parent == Path(__file__).resolve().parents[2] / '.cache' and target.name.startswith('qil021-'), 'Unsafe screenshot directory')
        target.mkdir(parents=True, exist_ok=True)
        page.set_viewport_size({'width': 1280, 'height': 900})
        page.screenshot(path=str(target / 'progress-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        check(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Progress must fit a mobile viewport')
        page.screenshot(path=str(target / 'progress-mobile.png'), full_page=True)


def test_read_only_and_completed_without_read_are_not_mastered(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    first, second = learning_topics['first'], learning_topics['second']
    check(request_post(page.context, '/api/v1/topics/' + first + '/read/', {}).status == 200, 'Read mark failed')
    complete(page.context, second)
    open_progress(page)
    expect(card(page, first).locator('dd')).to_have_text(['Прочитано', 'Ещё не освоена', 'Нет завершённых попыток'])
    expect(card(page, second).locator('dd')).to_have_text(['Не прочитано', 'Ещё не освоена', '2 из 2 (100%)'])


def test_unpublished_topics_keep_progress_and_history_without_article_links(auth_page, auth_app, learning_topics):
    page = auth_page
    email, password = signed_in(page)
    first, second = learning_topics['first'], learning_topics['second']
    for topic_id in (first, second):
        check(request_post(page.context, '/api/v1/topics/' + topic_id + '/read/', {}).status == 200, 'Read mark failed')
    attempt_id = complete(page.context, first, 'en')
    auth_app.learning_data('draft', [first, second])
    open_progress(page)
    expect(card(page, first).get_by_role('heading', name='Testing foundations', exact=True)).to_be_visible()
    expect(card(page, first).locator('dd')).to_have_text(['Прочитано', 'Освоена', '2 из 2 (100%)'])
    expect(card(page, second).get_by_role('heading', name='Тема № ' + second, exact=True)).to_be_visible()
    expect(card(page, second).get_by_text('Недоступна для чтения · Название недоступно', exact=True)).to_be_visible()
    expect(page.locator('.topic-progress-list a')).to_have_count(0)
    check(page.context.request.get('/api/v1/topics/' + first + '/?language=ru').status == 404, 'Unpublished article must stay forbidden')
    page.get_by_role('link', name='Открыть сохранённый результат', exact=True).click()
    expect(page).to_have_url(re.compile('/attempts/' + attempt_id + r'\?language=en$'))
    result(page)
    check(post(page.context, '/api/v1/auth/logout/').status == 204, 'Synthetic logout failed')
    page.goto('/progress')
    expect(page).to_have_url(re.compile(r'/login$'))
    fill(page, email, password)
    page.get_by_role('button', name='Войти', exact=True).click()
    expect(page).to_have_url(re.compile(r'/progress$'))
    expect(card(page, first).locator('dd')).to_have_text(['Прочитано', 'Освоена', '2 из 2 (100%)'])
    expect(page.locator('.attempt-history-list [data-attempt-id="' + attempt_id + '"]')).to_be_visible()


def test_second_user_cannot_see_first_users_progress_history_or_result(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics['first']
    check(request_post(page.context, '/api/v1/topics/' + topic_id + '/read/', {}).status == 200, 'Read mark failed')
    attempt_id = complete(page.context, topic_id)
    auth_app.learning_data('draft', [topic_id])
    open_progress(page)
    expect(page.locator('.attempt-history-list > li')).to_have_count(1)
    check(post(page.context, '/api/v1/auth/logout/').status == 204, 'Synthetic logout failed')
    signed_in(page)
    # Check backend ownership directly; a hidden UI alone is not security evidence.
    check(page.context.request.get('/api/v1/progress/').json() == {'data': []}, 'Second user must have no foreign progress')
    check(page.context.request.get('/api/v1/attempts/').json() == {'data': []}, 'Second user must have no foreign history')
    check(page.context.request.get('/api/v1/attempts/' + attempt_id + '/').status == 404, 'Foreign result must be hidden by backend')
    open_progress(page)
    expect(card(page, topic_id)).to_have_count(0)
    expect(page.locator('.attempt-history-list')).to_have_count(0)
    expect(page.get_by_text('Завершённых попыток пока нет.', exact=True)).to_be_visible()


def test_pending_load_hides_old_rows_and_has_no_write_requests(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    open_progress(page)
    held, writes = [], []
    page.on('request', lambda request: writes.append(request.method) if '/api/v1/' in request.url and request.method != 'GET' else None)
    page.route('**/api/v1/progress/', lambda route: held.append(route))
    page.get_by_role('button', name='Обновить прогресс', exact=True).click()
    expect(page.get_by_role('status')).to_have_text('Загружаем прогресс и историю…')
    expect(page.locator('.topic-progress-list')).to_have_count(0)
    expect(page.get_by_role('button', name='Обновить прогресс', exact=True)).to_have_count(0)
    page.wait_for_timeout(100)
    check(len(held) == 1, 'Refresh must only make one progress request')
    held[0].continue_()
    expect(page.locator('.topic-progress-list > li')).to_have_count(2)
    check(not writes, 'Read-only progress must never send unsafe requests')


@pytest.mark.parametrize('failure', ['network', 'timeout', 'not_found'])
def test_progress_errors_are_safe_and_retry_does_not_invent_empty_data(auth_page, learning_topics, failure):
    page = auth_page
    signed_in(page)
    open_progress(page)
    pattern = '**/api/v1/attempts/'
    if failure == 'timeout':
        page.evaluate('''() => { const original = AbortSignal.timeout; window.qilOriginalTimeout = original;
            AbortSignal.timeout = () => original.call(AbortSignal, 300); }''')
        page.route(pattern, lambda route: None)
    elif failure == 'not_found':
        page.route(pattern, lambda route: route.continue_(url=route.request.url + '0/'))
    else:
        page.route(pattern, lambda route: route.abort('failed'))
    page.get_by_role('button', name='Обновить прогресс', exact=True).click()
    expect(page.get_by_role('alert')).to_contain_text('Данные прогресса или истории недоступны.' if failure == 'not_found' else 'Не удалось загрузить прогресс и историю.')
    expect(page.locator('.topic-progress-list,.attempt-history-list')).to_have_count(0)
    expect(page.get_by_text('Пока нет сохранённого прогресса.', exact=True)).to_have_count(0)
    page.unroute(pattern)
    if failure == 'timeout':
        page.evaluate('AbortSignal.timeout = window.qilOriginalTimeout')
    page.get_by_role('button', name='Повторить загрузку', exact=True).click()
    expect(page.locator('.topic-progress-list > li')).to_have_count(2)


def test_expired_session_on_refresh_redirects_to_login_without_cached_private_rows(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    complete(page.context, learning_topics['first'])
    open_progress(page)
    expect(page.locator('.attempt-history-list > li')).to_have_count(1)
    check(post(page.context, '/api/v1/auth/logout/').status == 204, 'Synthetic logout failed')
    page.get_by_role('button', name='Обновить прогресс', exact=True).click()
    expect(page).to_have_url(re.compile(r'/login$'))
    expect(page.locator('.topic-progress-list,.attempt-history-list')).to_have_count(0)
