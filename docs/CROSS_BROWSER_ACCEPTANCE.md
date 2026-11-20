# Кроссбраузерная приёмка — QIL-031

Пользователь утвердил минимальный scope: Chromium остаётся полным baseline; Firefox и WebKit проверяют критический путь. Источники — [QA-стратегия](QA_STRATEGY.md), [backlog](BACKLOG.md), [Practice UI](PRACTICE_UI.md). Продуктовые frontend/backend/API, миграции, dependencies/lock, mastery, локальный .env и пользовательские helpers сохраняются. Deployment, production hardening, английский UI и новые функции Practice не входят в задачу.

## Движки и конфигурация

Используется существующий Python Playwright 1.65.0. В локальном проектном `.venv/ms-playwright` находятся Chromium headless shell 158.0.8127.18 (build 1254), согласованные Firefox 159.0 (1572) и WebKit 27.2 (2388). Chromium повторно не устанавливается. Разрешённая установка двух новых движков использует `--no-remove`, не меняет Windows, PATH, ExecutionPolicy или lock-файлы. Реальные версии проверяются через Browser.version с немедленным закрытием браузеров и драйвера.

`--qil-browser` принимает только chromium, firefox или webkit и по умолчанию сохраняет Chromium. Общий fixture `qil_browser` обслуживает настоящий `auth_browser` и прежний frontend smoke без DB. Fixtures закрывают context/browser/driver; приложение и данные по-прежнему принадлежат случайной тестовой PostgreSQL и существующему HTTPX/TCP harness. pytest-playwright, JS Playwright config и новые dependencies не добавляются.

## Критический набор

Marker `cross_browser` добавлен к существующим assertions; успешные ответы не подменяются, исходный Chromium набор не исключается и не ослабляется. Practice frozen retry дополнительно параметризован двумя viewport. Сборка содержит 103 Chromium cases и 18 critical cases для каждого другого движка.

| Сценарии | Cases | Покрытие |
| --- | --- | --- |
| MVP learner journey | 4 | Регистрация без auto-login, login/session reload/logout, каталог/статья/словарь RU/EN, все четыре пары языков, radio/checkbox, result/idempotency/409, Progress |
| Material/start focus | 2 | Keyboard RU/EN, однократный h1, Back/Forward, отсутствие лишнего Read/start |
| Attempt navigation | 2 | Ответы и независимый язык теста, focus, контекст результата, AppShell/Progress/session/logout |
| Automatic Read | 2 | Реальная видимость конца статьи, один POST с CSRF, первая дата и общий RU/EN |
| Article/test/practice | 2 | Язык материала отдельно от теста, explicit start, ввод/keyboard/reload, verdict, normalized repeat/409, подтверждённый delete и неизменность Progress |
| Practice frozen retry | 2 | Negative network abort, подтверждающий GET, явный повтор того же payload в настоящий backend, отсутствие автоматического POST |
| Practice restart | 4 | Correct/incorrect, новый ID/пустой ввод/тот же язык, один start, прежний результат и Progress сохранены, Back |

Каждая группа проверяется на desktop 1280×900 и mobile viewport 390×844. Полные критические истории используют реальную SPA/Vite production-сборку, Django и PostgreSQL. Управляемое прерывание запроса в negative retry не подменяет успешный API-ответ. Expected answer, snapshot, cookies, CSRF и пароли не печатаются и не сохраняются в отчёты. Негативные DTO/mocks остальных Chromium-тестов остаются отдельными проверками и не заменяют критический путь.

Первый WebKit-прогон обнаружил два непереносимых предположения тестов: mouse check radio должен сохранять focus. Изолированная HTML-проверка подтвердила, что WebKit снимает focus при mouse click, а клавиатура сохраняет его во всех трёх движках. В двух сценариях выбор языка выполняется Space на заранее сфокусированном radio; прежние assertions focus/перевода/данных сохранены. Это проверяет согласованную keyboard-навигацию, не меняя приложение или критерии и не восстанавливая focus после события искусственно.

## Локальный запуск

Нужны собранный frontend, существующие locked dependencies, доступная локальная PostgreSQL и переменные процесса, загруженные по [README](../README.md#загрузка-настроек-в-новый-powershell). Dev-БД не используется для тестовых данных; не указывайте `--reuse-db`. Новая установка браузеров требует отдельного разрешения по AGENTS.md.

Из корня проекта после подготовки окружения:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = (Resolve-Path '.venv\ms-playwright').Path;
.\.venv\Scripts\python.exe -B -m pytest -c tests/e2e/pytest.ini tests/e2e --qil-browser chromium -q --tb=no --show-capture=no
.\.venv\Scripts\python.exe -B -m pytest -c tests/e2e/pytest.ini tests/e2e --qil-browser firefox -m cross_browser -q --tb=no --show-capture=no
.\.venv\Scripts\python.exe -B -m pytest -c tests/e2e/pytest.ini tests/e2e --qil-browser webkit -m cross_browser -q --tb=no --show-capture=no
```

Каждый процесс Pytest создаёт собственную случайную PostgreSQL; browser contexts закрываются после теста, browser/driver — общей fixture. HTTPX harness завершает свои Django/Vite-процессы до удаления собственной БД. Успешный cleanup обязателен и при падении теста. Рабочие данные и Docker volumes не очищаются. Backend regression, Django/миграции/pip и frontend unit/type-check/build запускаются один раз, без умножения на browser matrix.

## GitHub Actions и безопасные отчёты

Существующие backend_api, frontend_unit, frontend_check_build и playwright_e2e сохраняются. Последний имеет matrix.browser = chromium/firefox/webkit и `fail-fast: false`; у каждой cell свой Ubuntu runner и PostgreSQL 17.11 service. Свежий CI runner устанавливает только выбранный движок и его Linux dependencies; это не изменяет локальную Windows. Chromium запускает весь suite, остальные — `-m cross_browser`. Имена executions содержат движок, pytest получает явный `--qil-browser`.

Для PASS нужны completed/success всех шести executions и совпадение SHA с проверяемым commit. Missing, skipped, cancelled, NOT_RUN/BLOCKED и ошибка любого обязательного case не считаются PASS. Исходные exit codes сохраняются; `continue-on-error`, автоматических retries и скрытого перехода на Chromium нет. При ошибке движка остановка остальных matrix cells не выполняется.

[CI_REPORTS](CI_REPORTS.md) сохраняет обезличенный XML, ready-gate, точный файл, `include-hidden-files: false`, `if-no-files-found: error` и семь дней хранения. Artifact names — backend_api-junit, frontend_unit-junit и playwright_e2e-{chromium,firefox,webkit}-junit: пять XML-артефактов без конфликтов имён. Raw XML/logs, environment, screenshots/trace/HAR/video/HTML/auth state и DB dumps не публикуются. Подробности приватной диагностики воспроизводятся локально на синтетических данных, без вывода ответов и credentials.

## Границы доказательств

Первый опубликованный [run 44783943535](https://github.com/rkcz00/qa-interview-lab/actions/runs/44783943535) для SHA `c727eafab3eeeb6dde08b4a4b6165690c6493396` завершился cancelled: backend_api, frontend_unit, frontend_check_build и Chromium — success; Firefox/WebKit — cancelled. Job/Check Run annotations подтверждают превышение прежнего общего лимита 15 минут. Подготовка Firefox заняла около 13 минут, WebKit — около 14 минут; E2E были начаты, но не завершены к deadline. Это не результат PASS/FAIL самих critical assertions. После отдельного разрешения пользователя бюджет browser job увеличен до 30 минут с сохранением состава тестов, fail-fast=false и правил артефактов. Исправление публикуется дополнительным commit/push; итог CI относится к новому SHA и фиксируется в отчёте. Старый run не перезапускается.

Локальная приёмка окончательной версии — PASS: Chromium full 103, Firefox critical 18 и WebKit critical 18, без skipped в согласованном наборе; 85 остальных случаев намеренно deselected в Firefox/WebKit. Backend regression 332 и 22 подтеста, frontend unit 211, type-check/build, Django checks, makemigrations/migrate --check и pip check — PASS. Временные БД и собственные процессы очищены; .env, приложение, migrations/lock и пользовательские helpers сохранены. Первый WebKit failure и адресная диагностика описаны выше; итоговые три прогона выполнены после исправления взаимодействия.

YAML 1.2 и aliases проверены существующим bundled YAML parser Playwright без установки пакетов; структура matrix/artifacts, 15 Bash syntax checks, Python syntax, Markdown/внутренние ссылки, diff и staged secret scan входят в проверку публикации. CI точного SHA фиксируется в итоговом отчёте после реального запуска; локальный PASS не объявляется CI PASS. Настоящие Firefox/WebKit локально отличаются от Linux-сборок, поэтому CI проверяется отдельно. WebKit на Windows/Ubuntu не подтверждает Safari на macOS/iOS; узкий viewport не является физическим телефоном. Полный WCAG-аудит, pixel-perfect сравнение и расширенная OS/device-матрица не заявляются.
