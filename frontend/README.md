# Frontend: план и API-клиент QIL-016

React-страница пока остаётся стартовым каркасом. Этот этап добавляет клиент уже реализованного backend и его unit-тесты. Контракт взят из [архитектуры](../docs/ARCHITECTURE.md) и сверён с routes, views и serializers.

## Минимальные слои

- `src/api/types.ts` — публичные DTO: объекты данных, которые разрешено получить из API, и входные ответы на вопросы.
- `src/api/decoders.ts` — проверка входящего JSON во время выполнения. TypeScript сам по себе не проверяет сетевые данные. Неожиданные поля или неверные типы дают `ApiError` с `kind=protocol`, без передачи исходного ответа вызывающему коду.
- `src/api/client.ts` — общий Fetch wrapper, CSRF, sessions и четыре группы методов.
- `src/api/index.ts` — готовый экземпляр `api` для будущих React-компонентов; base URL берётся из Vite config.
- Будущие UI-компоненты будут вызывать эти группы. Отображение форм, выбор маршрутизатора и UI-библиотеки в этот этап не входят. OQ-03 о языке интерфейса остаётся открытым до реализации UI.

## Четыре группы и реальные контракты

Все пути ниже относительны к `/api/v1/`. Методы возвращают проверенное содержимое `data`; `bootstrap` и `logout` возвращают `void`.

| Группа / метод | HTTP | Путь | Результат |
| --- | --- | --- | --- |
| `auth.bootstrap()` | GET | `auth/csrf/` | CSRF в памяти клиента |
| `auth.register(email, password)` | POST | `auth/register/` | Account, HTTP 201; без автоматического входа |
| `auth.login(email, password)` | POST | `auth/login/` | Account, HTTP 200 |
| `auth.logout()` | POST | `auth/logout/` | HTTP 204 без тела |
| `auth.currentSession()` | GET | `auth/me/` | Account; гость получает `403 authentication_required` |
| `learning.catalog(language?)` | GET | `topics/` | TopicSummary[] |
| `learning.article(topicId, language?)` | GET | `topics/{topic_id}/` | Article |
| `learning.terms(topicId, language?)` | GET | `topics/{topic_id}/terms/` | Term[] |
| `assessment.start(topicId, language)` | POST | `topics/{topic_id}/attempts/` | PendingAttempt, HTTP 201 |
| `assessment.get(attemptId, language?)` | GET | `attempts/{attempt_id}/` | PendingAttempt или SubmittedAttempt |
| `assessment.submit(attemptId, language, answers)` | POST | `attempts/{attempt_id}/submit/` | SubmittedAttempt |
| `assessment.history()` | GET | `attempts/` | SubmittedAttempt[] |
| `progress.markRead(topicId)` | POST | `topics/{topic_id}/read/` | Progress |
| `progress.current()` | GET | `progress/` | Progress[] |

`language` принимает только `ru` или `en`. В GET он передаётся одноимённым query-параметром, при пропуске действует backend default `ru`. В start/submit язык обязателен в JSON. Язык статьи не хранится глобально в клиенте и не влияет на язык теста. Progress и history не принимают query-параметров языка.

## Настройка и безопасность

`VITE_API_BASE_URL` по умолчанию равен `/api/v1/`; шаблон — `.env.example` в этой папке. Это публичная настройка, Vite включает `VITE_*` в браузерную сборку. Backend-секреты в неё не помещаются. Клиент принимает API того же origin, что и страница; в dev используется существующий Vite proxy.

Каждый запрос использует `credentials: include`, `cache: no-store` и запрещает автоматические redirect. Перед каждым POST выполняется CSRF bootstrap, а токен передаётся через `X-CSRFToken`. Одновременные bootstrap используют один запрос. Токен живёт только в памяти текущего запроса и не возвращается методом `auth.bootstrap()`. Следующий POST получает свежий токен, в том числе после ротации при login.

Пароль передаётся только временным аргументом login/register и в предназначенном для них request body. DTO ответов, клиентское хранилище и ошибки не содержат пароль, hash или session ID. Cookie обрабатывает браузер; клиент не читает их через JavaScript. Правильные ответы и внутренние поля отсутствуют в публичных типах и отклоняются при разборе ответа.

`ApiError` содержит `status`, `code`, `message`, `kind` и необязательные `fields`. HTTP-коды и `error.code` сохраняются. Сообщения `fields` для входных полей нормализуются в массивы строк. Ошибка сети имеет `status=0`, `code=network_error`; неверный контракт — `code=invalid_response`; неверная настройка — `code=invalid_configuration`. Это локальные ошибки клиента, не новые backend-контракты. Raw response, request, headers и исходное исключение не прикладываются. Timeout — 15 секунд на запрос, настраивается при создании клиента. POST автоматически не повторяется.

## Проверки

Из папки `frontend`, в Windows используйте `npm.cmd`:

```powershell
npm.cmd ci --no-audit --no-fund
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
```

Тесты используют встроенный `node:test` Node 24 и подменённый Fetch. Они проверяют клиентский контракт, не заменяя backend HTTPX/DB-тесты. Проверки типов дополнительно подтверждают отсутствие внутренних полей в публичных DTO. Новых npm-зависимостей для тестирования нет.

QIL-017 добавляет отдельный job `frontend_unit` в [workflow CI](../.github/workflows/ci.yml): Node.js 24.22.2, `npm ci` и `npm test` из `frontend`. Он запускается на push и pull request в `main`, а также вручную; ошибка теста завершает job с ошибкой. `frontend_check_build`, `backend_api` и `playwright_e2e` сохраняются. Локальные проверки пройдены; GitHub Actions нового commit — `NOT_RUN` до отдельно согласованного push.

Существующий `tests/e2e/test_frontend_smoke.py` проверяет стартовую production-страницу в Chromium. Этот smoke не является проверкой ещё не реализованных пользовательских UI-сценариев. Браузер для установленного Playwright 1.65.0 размещается в проектной `.venv/ms-playwright`; его установка требует отдельного согласования по AGENTS.md. Переменная ниже задаётся только в текущем PowerShell и не изменяет системный PATH. Запускать smoke нужно из его конфигурации, отдельно от Django:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = (Resolve-Path '..\.venv\ms-playwright').Path
..\.venv\Scripts\python.exe -m pytest -c ..\tests\e2e\pytest.ini ..\tests\e2e -q
```
