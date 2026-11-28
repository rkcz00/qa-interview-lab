# Оглавление и отдельный section reader — QIL-044

Основания: [sections и section progress](TOPIC_SECTIONS_SPEC.md), [completion/reset](PROGRESS_SPEC.md), [серверный переход и provenance](SECTION_PROGRESS_BACKEND.md), [QA](QA_STRATEGY.md), [backlog](BACKLOG.md).

## Поведение

`/topics/{topic_id}` показывает название темы, упорядоченное оглавление, собственные статусы чтения разделов и общий словарь. Тел разделов и end-marker здесь нет: просмотр оглавления не пишет Read. `/topics/{topic_id}/sections/{section_id}` показывает ровно один plain-text раздел, контекст темы, оглавление и серверные previous/next ID. Reader вызывает `reading()`, `section()` и `terms()` через прежний typed API; legacy Article/SectionsArticle остаются совместимыми, но не строят длинный reader.

RU по умолчанию; `?language=en` сохраняется при внутренних переходах, reload и Back/Forward. Язык теста независим. Новая topic/section page сначала проверяет собственную сессию: до завершения проверки не загружаются её body и controls, ответ проверки уже покинутой страницы игнорируется. Это исключает дублированный GET и взаимодействие с контролом предыдущей страницы. На новой странице h1 получает focus один раз, в том числе после быстрого Back из ещё загружаемого раздела. Выбор языка становится доступен после первоначальной загрузки и фокуса заголовка; последующие смены перевода сохраняют активный LanguageSelector. Активный раздел имеет `aria-current=page`. Старый topic URL с `#section-ID` проверяется по опубликованному оглавлению и заменяется через history.replace на canonical reader URL. Чужой/неизвестный ID или якорь не перенаправляет наружу; Draft/missing/cross-topic detail отображаются безопасно.

## Жизненный цикл чтения

Общий `SectionReads` живёт выше смены reader-страниц. Он хранит только публичные даты/статусы в памяти, раздельно по owner/generation/topic/section. Загрузка контента не владеет POST: RU/EN, ошибка GET, unmount и A→B→A не сбрасывают pending. Ответ A меняет только A; устаревший GET не удаляет подтверждённую первую дату. Если во время pending уже получено оглавление с другим Published-набором, запоздалый POST сохраняет свою дату, но не подменяет более новые серверные агрегаты старым набором. Разные разделы могут сохраняться независимо; один раздел не создаёт два одновременных POST.

Неизменённый `useAutomaticRead` требует активную вкладку, актуальный connected marker, полное пересечение viewport, ненулевую геометрию и CSS-видимость. Marker существует только для успешно загруженного текущего раздела. Промежуточный раздел даёт собственную отметку, а aggregate Read появляется только после всех текущих Published-разделов. Счётчики, completion и mastery берутся с сервера; браузер не считает проценты.

POST получает исходный generation видимого материала, общий CSRF bootstrap и credentials. После ошибки POST автоматического повтора нет: сначала пользователь нажимает «Проверить отметку ещё раз». Если GET подтверждает отсутствие отметки, отдельная «Повторить сохранение» вновь разрешает наблюдение за реально видимым концом. Нажатие само не обходит visibility-проверку. Успешный GET с уже сохранённой датой завершает неопределённость без POST. Session loss/reset/смена владельца очищают private registry и инвалидируют запоздалые ответы.

Успешное сохранение вызывает прежний progress refresh для sidebar и обновляет доступность Practice. До полного Read UI объясняет `section_read_required`; окончательная проверка остаётся на backend. Test/Practice, Answer/Finish, result DTO, ownership и reset-протокол сохранены.

## Проверяемая временная PostgreSQL

Dev-БД в QIL-044 не запрашивается и не мигрируется. E2E создаёт свою пустую `test_qil006_<uuid>` БД, проверяет её имя и отсутствие таблиц. Fixture `tests/e2e/migrate_verified.py` сначала разворачивает историческое состояние и синтетические RU/EN legacy Topic/Read, выполняет learning.0003 и сразу записывает её точный исходный section ID и migration timestamp. Это контролируемый переход, а не вывод происхождения из position/минимального ID/совпадения текста.

Fixture проверяет отказ действующего migration guard без provenance и rollback таблицы SectionProgress. Затем временный manifest и его SHA-256 передаются штатной проверке и migrate. Переносится ровно исходная дата, legacy-дата сохраняется; служебный синтетический набор удаляется перед основными E2E. Manifest не попадает в репозиторий, временная папка удаляется. Backend guard/миграции/loader не меняются. Только собственные дочерние процессы и временные БД удаляются harness при завершении, в том числе при падении теста.

## Проверки и границы

Проверяются metadata-only TOC, selected body, stable order, direct URL/legacy hash, previous/next, RU/EN/history/reload, h1 focus/keyboard, desktop 1280×900 и mobile 390×844. Unit покрывает shared pending, A→B→A, out-of-order ответы разных разделов, stale GET, owner/reset/session, явный GET/retry и исходный generation. E2E удерживает настоящий POST и прерывает только отрицательные загрузки; успешные learner-ответы не подменяются mocks. Hidden/0×0/повторные события не дают лишней записи. Новые тесты дополняют прежние Auth/Learning/Assessment/Practice/Progress сценарии.

28 ноября 2026 года повторно пройдены 304 frontend unit-теста, type-check и production build; 545 backend/HTTPX-тестов и 46 подтестов, Django checks, makemigrations --check, migrate --check и pip check на временной PostgreSQL. Backend cleanup — PASS. После обрыва сессии прежние незавершённые browser runs не засчитаны как PASS; их финальные результаты недоступны. Перед повторным запуском read-only проверено отсутствие оставшихся тестовых процессов и временных БД.

Первый завершённый browser-прогон дал FAIL: лишний GET при проверке сессии нового пути; Firefox также обнаружил гонку быстрого переключения языка. Исправлен порядок session → content, добавлены desktop/mobile проверки с удержанием настоящего /auth/me/ и body GET, быстрым Back/Forward и немедленной сменой языка. Они выявили поздний initial heading focus после уже выбранного языка; до первой загрузки controls теперь disabled. Два итоговых focus-кейса прошли во всех трёх движках. Строгий счётчик GET и прежние сценарии не ослаблены. Ещё один старый Admin-тест полагался на User ID=1: verified fixture создаёт и удаляет синтетическую legacy-строку, поэтому ID больше не существует. Запрет теперь проверяется по реально существующим editor user/group IDs с теми же точными 403; добавлен запрет TopicSectionProgress. Backend permissions не менялись. После исправлений 304 unit и build/type-check повторно PASS; финальная матрица из 165 Chromium и по 83 Firefox/WebKit, включая 16 новых reader-кейсов, прошла полностью.

Финальный Chromium full — 165 PASS, Firefox critical — 83 PASS, WebKit critical — 83 PASS; 82 остальных сценария выполнялись в полном Chromium scope. Все 16 новых reader-кейсов прошли в каждом движке на desktop/mobile. Cleanup каждого прогона и проверка неизменности source/protected files — PASS. Финальная read-only проверка maintenance PostgreSQL подтвердила ноль оставшихся тестовых БД, проверка собственных PID — отсутствие процессов. Dev-БД не подключалась. Markdown/193 внутренние ссылки, 8 JSON-примеров, формулы/DAG, Python AST, diff и secret scan — PASS; YAML workflow неизменён. Ручное одобрение новых страниц в QIL-045 — NOT_RUN, поскольку это следующий отдельный этап.

CI проверяется для точного SHA после единственного разрешённого push; локальный PASS сам по себе не означает зелёный CI. QIL-045 и ручное одобрение новых страниц остаются отдельной задачей. Новые темы, dev-seed, публичное развёртывание и production-настройки не входят в QIL-044.

## Созданные и изменённые файлы

- Frontend: `src/App.tsx`, `src/auth/routing.ts`, `src/api/client.ts`, `src/api/index.ts`; в `src/learning/` — `LearningApplication.tsx`, `model.ts`, `routing.ts`, `texts.ts`, новые `ReadingContext.ts`, `failure.ts`, `reading.ts`; `src/ui/AppShell.tsx`, `src/ui/TopicSidebar.tsx`, `src/styles.css`.
- Unit: `frontend/tests/learning.test.ts`, `section-progress.test.ts`, `sections.test.ts`, новый `reader.test.ts` в той же папке.
- E2E: `tests/e2e/conftest.py`, новые `migrate_verified.py`, `reader_helpers.py`, `test_section_reader.py`; совместимые маршруты и оракулы в `test_assessment_ui.py`, `test_content_admin_acceptance.py`, `test_focus_navigation.py`, `test_learning_ui.py`, `test_learning_workspace.py`, `test_mvp_acceptance.py`, `test_practice_ui.py`, `test_topic_sections.py` в той же папке. Прежние сценарии сохранены; переход «К статье» теперь проверяет оглавление, затем выбранный раздел. Разные документированные 404 у legacy Article и reading проверяются отдельно и точно.
- Документы: корневой `README.md`, `frontend/README.md`, `docs/PRD.md`, `ARCHITECTURE.md`, `QA_STRATEGY.md`, `BACKLOG.md`, `PROGRESS_SPEC.md`, `TOPIC_SECTIONS_SPEC.md`, новый `SECTION_READER_UI.md` в `docs/`.

Backend/API, миграции, package/requirements, CI workflow/sanitizer, `.env` и семь пользовательских скриптов не меняются. Временные локальные status/ownership-файлы проверок лежат только в игнорируемой `.cache`, без raw logs и учётных данных; в commit они не входят.

Для самостоятельного просмотра в следующей QIL-045 нужно использовать отдельное временное окружение с подтверждённой provenance. Проверить оглавление → отдельный раздел → partial Read → remaining sections → Test/Practice и sidebar, RU/EN/history/reload, keyboard/focus и mobile. Dev-перенос старых Read не выполнялся и не разрешается этим отчётом.
