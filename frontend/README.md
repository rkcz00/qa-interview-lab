# Frontend: API-клиент, Auth и Learning UI

QIL-016 добавил типизированный клиент, QIL-018 — Auth UI, QIL-019 — каталог, статью, словарь и отметку чтения. Контракт взят из [архитектуры](../docs/ARCHITECTURE.md) и сверён с backend routes, views и serializers. Quiz/attempts/scoring, экран истории и полного прогресса пока не реализованы.

## Минимальные слои

- `src/api/types.ts` — публичные DTO: объекты данных, которые разрешено получить из API, и входные ответы на вопросы.
- `src/api/decoders.ts` — проверка входящего JSON во время выполнения. TypeScript сам по себе не проверяет сетевые данные. Неожиданные поля или неверные типы дают `ApiError` с `kind=protocol`, без передачи исходного ответа вызывающему коду.
- `src/api/client.ts` — общий Fetch wrapper, CSRF, sessions и четыре группы методов.
- `src/api/index.ts` — общий экземпляр `api` для React-компонентов; base URL берётся из Vite config.
- `src/auth/` — формы, проверка сессии, локальная валидация, фиксированные маршруты и русские тексты в `texts.ts`. В MVP используется русский UI без переключателя; будущий английский UI не меняет API и независимые RU/EN материалов и тестирования.
- `src/learning/` — каталог, статья, словарь и состояние чтения; `model.ts` управляет загрузкой и запоздалыми ответами. Сетевые запросы и runtime decoders остаются в общем `api`.

## Маршруты и формы

| Маршрут | Поведение |
| --- | --- |
| `/` | Стартовая страница со ссылками на темы, вход и регистрацию; доступна без API |
| `/register` | Email и пароль; HTTP 201 переводит на `/login`, без автоматического входа |
| `/login` | Только заполненность email/пароля; вход переводит на запрошенную Learning-страницу либо `/session` |
| `/session` | GET `auth/me/`, email, ссылка на темы и выход; гость перенаправляется на `/login` |
| `/topics` | Каталог только Published-тем, русский язык по умолчанию |
| `/topics/{topic_id}` | Статья, отметка «Прочитано» и секция словаря темы |

Используется History API браузера без новой router-библиотеки: ссылки сохраняют обычный `href`, работают Back/Forward, заголовок страницы и переходы с клавиатуры. После выхода открывается `/login`; `next`/`returnTo` не используются. Без ожидаемого Learning-перехода вошедший пользователь на `/login` или `/register` переводится на `/session`.

Гость на Learning-странице направляется на `/login`. Только проверенный внутренний Learning-маршрут держится в памяти текущей вкладки и восстанавливается после входа/подтверждения сессии. Цель не читается из redirect query-параметров и не сохраняется в Web Storage. При обновлении самой `/login` временная цель теряется и после входа открывается `/session`. Переход на главную или страницу аккаунта очищает цель.

## Материалы и чтение — QIL-019

Каталог сохраняет порядок API по `topic_id`; словарь — `position`, затем `term_id`. UI не сортирует ID как строки и не получает внутренний статус публикации: Published отбирает backend. Draft и missing дают одинаковое безопасное сообщение по реальному `404 not_found`.

Словарь — секция под статьёй: отдельный маршрут для этого пути не требуется. Заголовки, статья и термины выводятся React-текстом, без исполнения HTML/Markdown. `?language=en` хранит язык материала для reload и Back/Forward; отсутствие параметра означает `ru`. Статья и словарь используют один язык; параметр не задаёт язык будущего теста. Неизвестный/повторный `language` показывает безопасное UI-сообщение, fallback перевода отсутствует.

GET `progress/` показывает собственную отметку по `topic_id`. Отсутствие записи означает «не отмечено», ошибка GET — «неизвестно» с повторной проверкой. Открытие, прокрутка, словарь и смена языка не делают POST. Кнопка вызывает существующий `progress.markRead()` с CSRF и блокировкой двойной отправки; подтверждённая отметка одна для RU/EN. После прерывания POST сначала предлагается безопасный GET, автоматической повторной записи нет. Освоение и оценка на клиенте не вычисляются.

`authentication_required` скрывает Learning-данные и возвращает к входу; снятие публикации с `404` при `read` убирает статью. Ответы старой страницы/языка не подменяют новые данные. Предусмотрены loading, пустой каталог, недоступная тема и безопасные ошибки сети/отметки. Backend/API и зависимости не менялись.

Каждый прямой вход в auth-маршрут заново проверяет сессию. Только `403 authentication_required` означает гостя. Ошибка сети или сервера оставляет состояние неизвестным и показывает кнопку повторной проверки; она не маскируется под выход. Запоздалые ответы после смены страницы не восстанавливают устаревшее состояние.

У полей есть labels, подсказки и связанные ошибки; фокус переводится на ошибочное поле или сообщение. Во время запроса поля и submit отключаются, повторная отправка блокируется. UI показывает безопасные русские сообщения по `error.code`, без исходного текста исключения. Дубликат email даёт общую `validation_error`, без раскрытия наличия аккаунта. Прерывание POST не вызывает автоматического повтора.

Пароль регистрации проверяется на минимальную длину 8 символов, числовой/распространённый/похожий на email пароль. Для соответствия Django используется его публичный словарь и Unicode-данные, а не новая библиотека; [описание и лицензия](src/auth/POLICY.md). Сервер остаётся окончательной проверкой. При входе правила регистрации не применяются. Пароль хранится в поле формы и временном запросе; после ответа поле очищается. Пароль, CSRF и session ID не сохраняются в Web Storage и не выводятся в UI или логи.

## Локальный запуск и SPA fallback

Запустите backend на `127.0.0.1:8000` по [основной инструкции](../README.md), затем из `frontend` выполните `npm.cmd run dev`. Откройте `http://127.0.0.1:5173/topics` либо существующие `/register`, `/login`, `/session`. Прямые `/topics/{topic_id}` обслуживаются тем же SPA fallback Vite dev/preview; `/api` проксируется с сохранением Host/Origin для Django CSRF. Для production preview: `npm.cmd run build`, затем `npm.cmd run preview -- --port 4173`.

По умолчанию proxy использует `http://127.0.0.1:8000`. `QIL_API_PROXY_TARGET` задаёт адрес backend только процессу Vite; E2E использует случайный loopback-порт. Это не `VITE_*` и не публичный API URL. В будущем публичный веб-сервер также должен обеспечить SPA fallback и раздельную маршрутизацию `/api`; публичный deploy здесь не реализуется.

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

Тесты используют встроенный `node:test` Node 24: API-контракты с подменённым Fetch, Auth, маршруты/язык, безопасные ошибки, гонки загрузки и сессии, явную отметку и двойной submit. Они не заменяют backend HTTPX/DB-тесты. Проверки типов подтверждают отсутствие внутренних полей в DTO. Новых npm-зависимостей нет.

Job `frontend_unit` в [workflow CI](../.github/workflows/ci.yml) выполняет Node.js 24.22.2, `npm ci` и `npm test` из `frontend`. Он запускается на push и pull request в `main`, а также вручную; ошибка теста завершает job с ошибкой. Сохраняются `frontend_check_build`, `backend_api` и `playwright_e2e`. QIL-018/C подтверждён [run #43175377203](https://github.com/rkcz00/qa-interview-lab/actions/runs/43175377203); QIL-019 в GitHub Actions — `NOT_RUN` до отдельно разрешённого push.

Из корня проекта после загрузки существующего `.env` в процесс PowerShell и сборки frontend:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = (Resolve-Path '.venv\ms-playwright').Path
.\.venv\Scripts\python.exe -B frontend/tools/check_password_policy.py
.\.venv\Scripts\python.exe -m pytest -c tests/e2e/pytest.ini tests/e2e -q
```

Проверка политики сравнивает публичный словарь и 218 примеров с установленным locked Django, без DB. После согласованного обновления Django/Python данные можно обновить той же командой с `--write` и повторно проверить; она меняет только публичный JSON и копию лицензии.

`tests/e2e/test_auth_ui.py` проверяет production-сборку через Vite preview, реальный Django и отдельную случайную PostgreSQL-базу. Нужна работающая PostgreSQL и тестовый пользователь БД с правом создания баз. Fixture применяет миграции только в своей базе, завершает оба процесса и удаляет только созданную базу при любом исходе. Browser contexts закрываются после каждого теста. Trace, HAR, video и сохранённые cookies не создаются. В CI этот прогон использует отдельный service container PostgreSQL 17.11.

`test_learning_ui.py` использует ту же связку и отдельный `learning_data.py`: Published RU/EN и Draft создаются только в случайной базе прогона, изменения/удаление разрешены лишь для созданных fixture topic IDs. Проверяются каталог, статья/словарь, переходы и языки, чтение с CSRF, два пользователя, 404/Draft, сеть, клавиатура и узкий viewport. Существующая команда CI собирает всю папку `tests/e2e`, поэтому менять workflow для новых тестов не нужно.

Прежний `tests/e2e/test_frontend_smoke.py` сохранён без изменений: он проверяет `/` без backend и DB. Для запуска только его укажите этот файл вместо папки. Браузер установленного Playwright находится в `.venv/ms-playwright`; новая установка требует согласования. Полные Assessment/Progress/MVP E2E остаются будущими задачами.
