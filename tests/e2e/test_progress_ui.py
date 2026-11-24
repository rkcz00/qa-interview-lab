import re

from playwright.sync_api import expect
import pytest

from tests.e2e.test_auth_ui import check, fill, post, seed
from tests.e2e.test_learning_ui import signed_in
from tests.e2e.test_assessment_ui import request_post, result


def open_progress(page):
    page.goto('/progress')
    expect(page.locator('main .overall-progress')).to_be_visible()


def overall(page, percentage, count):
    expect(page.locator('main .overall-percentage')).to_have_text(percentage)
    expect(page.locator('main .overall-counter')).to_have_text(count)
    expect(page.locator('.attempt-history-list,.topic-progress-list')).to_have_count(0)


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



def test_guest_progress_opens_home_after_real_login(auth_page):
    page = auth_page
    email, password = seed(page.context)
    page.goto('/progress?next=https://outside.invalid')
    expect(page).to_have_url(re.compile(r'/login$'))
    fill(page, email, password)
    page.get_by_role('button', name='Войти', exact=True).click()
    expect(page).to_have_url(re.compile(r'/$'))


def test_published_untouched_topics_have_zero_overall_progress(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    open_progress(page)
    overall(page, '0%', 'Освоено 0 из 2 тем')
    expect(page.get_by_role('heading', name='История завершённых попыток', exact=True)).to_have_count(0)
    expect(page.get_by_role('button', name='Обновить прогресс', exact=True)).to_have_count(0)


def test_overall_mastery_uses_saved_results_without_ui_history(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics['first']
    check(request_post(page.context, '/api/v1/topics/' + topic_id + '/read/', {}).status == 200, 'Read mark failed')
    first = complete(page.context, topic_id, 'en')
    complete(page.context, topic_id, 'ru', correct=False)
    calls = []
    page.on('request', lambda request: calls.append(1) if request.url.endswith('/api/v1/attempts/') else None)
    open_progress(page)
    overall(page, '50%', 'Освоено 1 из 2 тем')
    check(not calls, 'UI must not fetch history')
    history = page.context.request.get('/api/v1/attempts/').json()['data']
    check(len(history) == 2, 'Both completed results must remain stored')
    page.goto('/attempts/' + first + '?language=en')
    result(page)
    page.go_back()
    overall(page, '50%', 'Освоено 1 из 2 тем')
    page.reload()
    overall(page, '50%', 'Освоено 1 из 2 тем')
    check(auth_app.learning_data('info', [topic_id])['submitted_count'] == 2, 'Viewing progress must not create attempts')


def test_read_only_and_completed_without_read_are_not_mastered(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    first, second = learning_topics['first'], learning_topics['second']
    check(request_post(page.context, '/api/v1/topics/' + first + '/read/', {}).status == 200, 'Read mark failed')
    complete(page.context, second)
    open_progress(page)
    overall(page, '50%', 'Освоено 0 из 2 тем')


def test_unpublished_topics_leave_totals_but_keep_stored_progress_and_results(auth_page, auth_app, learning_topics):
    page = auth_page
    email, password = signed_in(page)
    first, second = learning_topics['first'], learning_topics['second']
    check(request_post(page.context, '/api/v1/topics/' + first + '/read/', {}).status == 200, 'Read mark failed')
    attempt_id = complete(page.context, first, 'en')
    saved = page.context.request.get('/api/v1/progress/').json()
    auth_app.learning_data('draft', [first, second])
    open_progress(page)
    overall(page, '0%', 'Освоено 0 из 0 тем')
    expect(page.locator('main .ui-empty')).to_have_text('Опубликованных тем пока нет.')
    check(page.context.request.get('/api/v1/progress/').json() == saved, 'Unpublication must not change stored mastery')
    check(page.context.request.get('/api/v1/topics/' + first + '/?language=ru').status == 404, 'Draft article remains forbidden')
    page.goto('/attempts/' + attempt_id + '?language=en')
    result(page)
    check(post(page.context, '/api/v1/auth/logout/').status == 204, 'Synthetic logout failed')
    page.goto('/progress')
    expect(page).to_have_url(re.compile(r'/login$'))
    fill(page, email, password)
    page.get_by_role('button', name='Войти', exact=True).click()
    expect(page).to_have_url(re.compile(r'/$'))
    open_progress(page)
    overall(page, '0%', 'Освоено 0 из 0 тем')
    check(page.context.request.get('/api/v1/progress/').json() == saved, 'Relogin must preserve stored data')


def test_second_user_has_no_foreign_progress_history_or_result(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics['first']
    check(request_post(page.context, '/api/v1/topics/' + topic_id + '/read/', {}).status == 200, 'Read mark failed')
    attempt_id = complete(page.context, topic_id)
    open_progress(page)
    overall(page, '50%', 'Освоено 1 из 2 тем')
    check(post(page.context, '/api/v1/auth/logout/').status == 204, 'Synthetic logout failed')
    signed_in(page)
    check(page.context.request.get('/api/v1/progress/').json() == {'data': []}, 'Other progress must be absent')
    check(page.context.request.get('/api/v1/attempts/').json() == {'data': []}, 'Other history must be absent')
    check(page.context.request.get('/api/v1/attempts/' + attempt_id + '/').status == 404, 'Foreign result must stay hidden')
    open_progress(page)
    overall(page, '0%', 'Освоено 0 из 2 тем')


def test_pending_load_hides_old_values_without_writes(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    open_progress(page)
    held, writes = [], []
    page.on('request', lambda request: writes.append(request.method) if '/api/v1/' in request.url and request.method != 'GET' else None)
    page.route('**/api/v1/completion-progress/', lambda route: held.append(route))
    page.reload()
    expect(page.locator('main .ui-loading')).to_have_text('Загружаем прогресс…')
    expect(page.locator('main .overall-progress')).to_have_count(0)
    page.wait_for_timeout(100)
    check(len(held) == 1, 'Shared summary and page use one progress request')
    held[0].continue_()
    overall(page, '0%', 'Освоено 0 из 2 тем')
    check(not writes, 'Progress screen is read-only')


@pytest.mark.parametrize('failure', ['network', 'timeout', 'not_found'])
def test_progress_errors_are_safe_and_retry_never_invents_zero(auth_page, learning_topics, failure):
    page = auth_page
    signed_in(page)
    open_progress(page)
    pattern = '**/api/v1/completion-progress/'
    if failure == 'timeout':
        page.add_init_script("const original = AbortSignal.timeout.bind(AbortSignal); AbortSignal.timeout = () => original(300)")
        page.route(pattern, lambda route: None)
    elif failure == 'not_found':
        page.route(pattern, lambda route: route.continue_(url=route.request.url + '0/'))
    else:
        page.route(pattern, lambda route: route.abort('failed'))
    page.reload()
    expect(page.locator('main').get_by_role('alert')).to_contain_text('Данные прогресса недоступны.' if failure == 'not_found' else 'Не удалось загрузить прогресс.')
    expect(page.locator('main .overall-progress')).to_have_count(0)
    page.unroute(pattern)
    page.locator('main').get_by_role('button', name='Повторить загрузку', exact=True).click()
    overall(page, '0%', 'Освоено 0 из 2 тем')


def test_expired_session_reload_opens_login_without_private_summary(auth_page, learning_topics):
    page = auth_page
    signed_in(page)
    complete(page.context, learning_topics['first'])
    open_progress(page)
    check(post(page.context, '/api/v1/auth/logout/').status == 204, 'Synthetic logout failed')
    page.reload()
    expect(page).to_have_url(re.compile(r'/login$'))
    expect(page.locator('.overall-progress,.topic-sidebar')).to_have_count(0)
