"""Approved post-UAT flow: login, shared topics, automatic reading, overall progress."""
import re

import pytest
from playwright.sync_api import expect

from tests.e2e.test_auth_ui import check, fill, seed
from tests.e2e.test_learning_ui import signed_in, topic_page
from tests.e2e.test_assessment_ui import begin, choose_correct, request_post, result, confirm_answers, read_all_sections
from tests.e2e.test_progress_ui import complete
from tests.e2e.reader_helpers import open_reader


SIZES = [{"width": 1280, "height": 900}, {"width": 390, "height": 844}]


def read_article(page):
    page.locator('.article-end').scroll_into_view_if_needed()
    expect(page.locator('.reading-card .ui-notice--success')).to_have_text('Статья отмечена прочитанной.')


def overall(page, percent, count):
    expect(page.locator('main .overall-percentage')).to_have_text(percent)
    expect(page.locator('main .overall-counter')).to_have_text(count)
    expect(page.locator('.attempt-history-list,.topic-progress-list')).to_have_count(0)


@pytest.mark.parametrize('size', SIZES, ids=['desktop', 'mobile'])
def test_login_first_home_catalog_sidebar_and_selected_topic(auth_page, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    email, password = seed(page.context)
    page.goto('/')
    expect(page).to_have_url(re.compile(r'/login$'))
    expect(page.locator('.topic-sidebar')).to_have_count(0)
    fill(page, email, password)
    page.get_by_role('button', name='Войти', exact=True).click()
    expect(page).to_have_url(re.compile(r'/$'))
    expect(page.locator('.topic-list a')).to_have_text(['Основы тестирования', 'Автоматизация'])
    page.reload()
    expect(page.locator('.topic-list a')).to_have_count(2)
    menu = page.get_by_role('navigation', name='Выбор темы', exact=True)
    if size['width'] < 761:
        expect(menu).not_to_be_visible()
        page.get_by_role('button', name='Темы подготовки', exact=True).click()
    expect(menu.get_by_role('link')).to_have_text(['Основы тестирования', 'Автоматизация'])
    menu.get_by_role('link', name='Основы тестирования', exact=True).click()
    expect(page.locator('main h1')).to_have_text('Основы тестирования')
    if size['width'] < 761:
        page.get_by_role('button', name='Темы подготовки', exact=True).click()
    expect(menu.locator('a[aria-current]')).to_have_attribute('href', '/topics/' + learning_topics['first'])
    check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Shared workspace must fit viewport')


@pytest.mark.parametrize('size', SIZES, ids=['desktop', 'mobile'])
@pytest.mark.cross_browser
def test_end_visibility_automatically_saves_once_with_csrf_and_persists_languages(auth_page, auth_app, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    topic_id = learning_topics['first']
    auth_app.learning_data('long_article', [topic_id])
    signed_in(page)
    held = []
    page.route('**/api/v1/topics/' + topic_id + '/sections/*/read/', lambda route: held.append(route))
    topic_page(page, topic_id)
    check(page.context.request.get('/api/v1/progress/').json() == {'data': []}, 'Opening a long article must not record reading')
    # Keyboard focus is portable; WebKit intentionally blurs radios on mouse clicks.
    english = page.get_by_role('radio', name='English', exact=True)
    english.focus()
    english.press('Space')
    expect(page.locator('.article-body')).to_have_attribute('lang', 'en')
    expect(page.get_by_role('radio', name='English', exact=True)).to_be_focused()
    check(not held, 'Language changes before the end must not save reading')
    page.locator('.article-end').scroll_into_view_if_needed()
    expect(page.locator('.reading-card .ui-loading')).to_have_text('Сохраняем отметку…')
    page.locator('.article-end').scroll_into_view_if_needed()
    page.wait_for_timeout(100)
    check(len(held) == 1, 'One visibility event must only start one POST')
    check(bool(held[0].request.headers.get('x-csrftoken')), 'Automatic read must still require CSRF')
    held[0].continue_()
    expect(page.locator('.reading-card .ui-notice--success')).to_be_visible()
    before = page.context.request.get('/api/v1/progress/').json()
    page.reload()
    expect(page.locator('.reading-card .ui-notice--success')).to_be_attached()
    page.get_by_role('radio', name='Русский', exact=True).check()
    expect(page.locator('.article-body')).to_have_attribute('lang', 'ru')
    page.locator('.article-end').scroll_into_view_if_needed()
    expect(page.locator('.reading-card .ui-notice--success')).to_be_visible()
    check(len(held) == 1 and page.context.request.get('/api/v1/progress/').json() == before, 'Reload and RU/EN must preserve the first saved mark')
    check(auth_app.learning_data('info', [topic_id])['read_count'] == 1, 'One shared read record must exist')
    expect(page.get_by_role('button', name='Отметить «Прочитано»', exact=True)).to_have_count(0)


@pytest.mark.parametrize('size', SIZES, ids=['desktop', 'mobile'])
def test_language_changes_while_read_post_is_pending_do_not_send_another_post(auth_page, auth_app, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    topic_id = learning_topics['first']
    auth_app.learning_data('long_article', [topic_id])
    signed_in(page)
    held = []
    page.route('**/api/v1/topics/' + topic_id + '/sections/*/read/', lambda route: held.append(route))
    topic_page(page, topic_id)
    page.locator('.article-end').scroll_into_view_if_needed()
    expect(page.locator('.reading-card .ui-loading')).to_have_text('Сохраняем отметку…')
    for name, language in [('English', 'en'), ('Русский', 'ru'), ('English', 'en')]:
        page.get_by_role('radio', name=name, exact=True).check()
        expect(page.locator('.article-body')).to_have_attribute('lang', language)
        page.locator('.article-end').scroll_into_view_if_needed()
        expect(page.locator('.reading-card .ui-loading')).to_have_text('Сохраняем отметку…')
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    check(len(held) == 1, 'Translations and visibility triggers must share the pending POST')
    held[0].continue_()
    expect(page.locator('.reading-card .ui-notice--success')).to_be_visible()
    before = page.context.request.get('/api/v1/progress/').json()
    page.get_by_role('radio', name='Русский', exact=True).check()
    expect(page.locator('.article-body')).to_have_attribute('lang', 'ru')
    read_article(page)
    check(len(held) == 1 and page.context.request.get('/api/v1/progress/').json() == before,
          'The successful response and first date must survive both translations')


@pytest.mark.parametrize('size', SIZES, ids=['desktop', 'mobile'])
@pytest.mark.parametrize('initial_language', ['ru', 'en'])
def test_translation_failure_and_retry_keep_the_original_read_post(auth_page, auth_app, learning_topics, size, initial_language):
    page = auth_page
    page.set_viewport_size(size)
    topic_id = learning_topics['first']
    auth_app.learning_data('long_article', [topic_id])
    signed_in(page)
    held = []
    page.route('**/api/v1/topics/' + topic_id + '/sections/*/read/', lambda route: held.append(route))
    topic_page(page, topic_id, initial_language)
    page.locator('.article-end').scroll_into_view_if_needed()
    expect(page.locator('.reading-card .ui-loading')).to_have_text('Сохраняем отметку…')
    translation_pattern = '**/api/v1/topics/' + topic_id + '/sections/*/?*'
    page.route(translation_pattern, lambda route: route.abort('failed'))
    next_language = 'en' if initial_language == 'ru' else 'ru'
    page.get_by_role('radio', name='English' if next_language == 'en' else 'Русский', exact=True).check()
    expect(page.locator('main').get_by_role('alert')).to_have_text('Не удалось загрузить материалы. Проверьте соединение и повторите загрузку.')
    page.unroute(translation_pattern)
    page.locator('main').get_by_role('button', name='Повторить загрузку', exact=True).click()
    expect(page.locator('.article-body')).to_have_attribute('lang', next_language)
    expect(page.locator('.reading-card .ui-loading')).to_have_text('Сохраняем отметку…')
    page.locator('.article-end').scroll_into_view_if_needed()
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    check(len(held) == 1, 'Translation failure and retry must preserve the first pending read POST')
    check(bool(held[0].request.headers.get('x-csrftoken')), 'The original POST must remain CSRF protected')
    held[0].continue_()
    read_article(page)
    before = page.context.request.get('/api/v1/progress/').json()
    page.get_by_role('radio', name='Русский' if initial_language == 'ru' else 'English', exact=True).check()
    expect(page.locator('.article-body')).to_have_attribute('lang', initial_language)
    read_article(page)
    check(len(held) == 1 and page.context.request.get('/api/v1/progress/').json() == before,
          'Both translations must share the successful response and original date')
    check(auth_app.learning_data('info', [topic_id])['read_count'] == 1, 'Only one shared read record may exist')


@pytest.mark.parametrize('size', SIZES, ids=['desktop', 'mobile'])
def test_visibility_return_with_hidden_marker_waits_for_a_real_visible_end(auth_page, auth_app, learning_topics, size):
    page = auth_page
    page.set_viewport_size(size)
    topic_id = learning_topics['first']
    auth_app.learning_data('long_article', [topic_id])
    signed_in(page)
    posts = []
    page.on('request', lambda request: posts.append(1) if request.method == 'POST' and '/topics/' + topic_id + '/sections/' in request.url and request.url.endswith('/read/') else None)
    topic_page(page, topic_id)
    # Control visibility events rather than OS window focus, which is unreliable in headless CI.
    # Geometry, IntersectionObserver, CSRF, HTTP and PostgreSQL remain real.
    page.evaluate("""async () => {
        const marker = document.querySelector('.article-end');
        marker.style.display = 'none';
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
        document.dispatchEvent(new Event('visibilitychange'));
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }""")
    check(not posts, 'A hidden tab and marker must not save reading')
    page.evaluate("""async () => {
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
        document.dispatchEvent(new Event('visibilitychange'));
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        delete document.visibilityState;
    }""")
    check(not posts, 'Returning visibility must not treat a zero-area marker as read')
    check(page.context.request.get('/api/v1/progress/').json() == {'data': []}, 'Hidden marker must leave progress unchanged')
    page.locator('.article-end').evaluate("marker => marker.style.removeProperty('display')")
    read_article(page)
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    check(len(posts) == 1, 'A genuinely visible end must save exactly once')
    check(auth_app.learning_data('info', [topic_id])['read_count'] == 1, 'Reading is shared and stored once')


def test_only_published_mastery_counts_without_history_requests_or_pending_attempts(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    topic_id = learning_topics['first']
    check(request_post(page.context, '/api/v1/topics/' + topic_id + '/read/', {}).status == 200, 'Read prerequisite failed')
    attempt_id = complete(page.context, topic_id)
    read_all_sections(page.context, learning_topics['second'])
    before = page.context.request.get('/api/v1/completion-progress/').json()
    pending = request_post(page.context, '/api/v1/topics/' + learning_topics['second'] + '/attempts/', {'language': 'ru'})
    check(pending.status == 201, 'Pending attempt setup failed')
    check(page.context.request.get('/api/v1/completion-progress/').json() == before, 'An unsubmitted attempt must not add completion')
    history_requests = []
    page.on('request', lambda request: history_requests.append(1) if re.search(r'/api/v1/attempts/\??$', request.url) else None)
    page.goto('/progress')
    overall(page, '65%', 'Освоено 1 из 2 тем')
    check(not history_requests, 'Progress UI must not fetch attempt history')
    page.reload()
    overall(page, '65%', 'Освоено 1 из 2 тем')
    auth_app.learning_data('draft', [topic_id])
    page.reload()
    overall(page, '30%', 'Освоено 0 из 1 тем')
    saved = page.context.request.get('/api/v1/progress/').json()['data']
    check(any(row['topic_id'] == topic_id and row['mastered'] for row in saved), 'Unpublication must preserve stored mastery')
    check(page.context.request.get('/api/v1/attempts/' + attempt_id + '/').status == 200, 'Saved result must remain available by owned URL')


def test_sidebar_updates_after_automatic_read_and_submit_without_reload_or_focus_loss(auth_page, auth_app, learning_topics):
    page = auth_page
    signed_in(page)
    first, second = learning_topics['first'], learning_topics['second']
    complete(page.context, first)
    auth_app.learning_data('long_article', [second])
    open_reader(page, second)
    expect(page.locator('aside .overall-percentage')).to_have_text('50%')
    selector = page.get_by_role('radio', name='Русский', exact=True)
    selector.focus()
    read_article(page)
    expect(page.locator('aside .overall-percentage')).to_have_text('65%')
    expect(selector).to_be_focused()
    begin(page, second)
    choose_correct(page)
    confirm_answers(page)
    page.get_by_role('button', name='Завершить тест', exact=True).click()
    result(page)
    expect(page.locator('aside .overall-percentage')).to_have_text('100%')
