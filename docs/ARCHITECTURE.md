# Архитектура QA Interview Lab

Статус: архитектура MVP; пользовательский сценарий уточнён в QIL-027. Контракт Practice согласован в QIL-028, backend принят в QIL-029; UI реализован в QIL-030, полный ручной PostgreSQL/Playwright-прогон — PASS. Существующие API и архитектурные решения сохранены. [Backend](PRACTICE_BACKEND.md), [UI и runner](PRACTICE_UI.md).

QIL-033 фиксирует утверждённую целевую архитектуру [progress/reset/test flow](PROGRESS_SPEC.md) и [sections](TOPIC_SECTIONS_SPEC.md). Backend completion/reset, UserProgressState и необходимая совместимость клиента реализованы в серверном этапе QIL-034. Визуальный completion/reset UI и QIL-035/QIL-036 **NOT_IMPLEMENTED**: текущий UI ещё показывает долю mastered/Published, одиночное article_body и допускает пропуски. [Границы и проверки backend](COMPLETION_BACKEND.md).

Связанные документы: [PRD](PRD.md), [QA-стратегия](QA_STRATEGY.md), [backlog](BACKLOG.md), [правила Codex](../AGENTS.md), [точный контракт Practice](PRACTICE_SPEC.md).

## 1. Архитектурные границы

Используется модульный монолит в одном репозитории. Монолит означает один Django backend и общую PostgreSQL; модульность означает разделение кода по ответственности внутри backend. React — отдельный браузерный клиент этого API.

```text
Браузер: React + TypeScript
    ├── /api/v1/ → Django + Django REST Framework
    └── /admin/  → Django Admin
                         │
                         └── PostgreSQL
```

Frontend и API планируются под одним origin: общей схемой, доменом и портом с точки зрения браузера. Это упрощает sessions и CSRF. В разработке Vite проксирует запросы к backend. Конкретный способ раздачи frontend и маршрутизации в публичном окружении пока не выбран.

В QIL-018 Auth UI использует фиксированные `/register`, `/login`, `/session` и History API браузера без новой router-библиотеки. Vite dev/preview обеспечивают SPA fallback и proxy `/api` с сохранением Host/Origin. Прямой переход и обновление auth-страницы заново проверяют `auth/me/`; только `authentication_required` означает гостя, ошибки связи оставляют сессию неизвестной. Русские тексты отделены от компонентов для будущего английского UI; язык учебных материалов не связан с языком UI. Публичная раздача SPA требует отдельного решения; backend/API-контракты этим этапом не меняются.

Главная `/` — защищённый каталог Published-тем; `/topics` сохраняется как совместимый адрес каталога. Общий `ProtectedGate` проверяет сессию до показа learner-экранов. Гость направляется на `/login`; успешный login всегда открывает `/`. `next`/`returnTo` не используются. Статья `/topics/{topic_id}` и её словарь сохраняют независимый `language=ru|en`; reload и Back/Forward работают через History API.

Vite нужен для разработки и сборки React. PostgreSQL хранит пользователей, контент, сессии, попытки и отметки чтения. Для MVP не нужны отдельные сервисы авторизации, очереди или дополнительные хранилища.

QIL-020 добавляет UI-маршруты `/topics/{topic_id}/test` (явный start) и `/attempts/{attempt_id}` (вопросы или серверный результат). На этих адресах `language` относится только к тесту. Выбор по ID и текущий вопрос хранятся в памяти экрана и переживают перевод/Back/Forward внутри попытки; GET после reload восстанавливает вопросы либо завершённый результат, но не неотправленные ответы. На неопределённом submit payload блокируется, состояние подтверждается GET; явный повтор использует тот же payload. После 409 допустим только GET сохранённого результата. UI-роуты не являются новыми API endpoints, backend/scoring и контракт snapshot не меняются.

`AppShell` объединяет header, меню Published-тем и прогресс. На mobile меню раскрывается с aria-expanded, выбранная тема имеет aria-current. В QIL-034 OverviewContext/ProgressStore переходят на новый completion-progress API для общего процента и статусов; mastered остаётся отдельным серверным признаком. История в UI не загружается; loading/ошибка не подменяются нулём. На `/login` в QIL-035 убирается «На главную», без изменения перехода после входа.

`useAutomaticRead` наблюдает конец последнего Published-раздела полностью загруженного единого reader. Сохраняются pending, hidden/0x0/stale-marker проверки, первая дата и общий RU/EN. POST read требует CSRF и поколение прогресса; после reset старый marker не инициирует повторную запись. Обновление общего прогресса после read/submit/delete/reset сохраняет DOM и фокус; фонового polling нет. Точные правила — в двух спецификациях QIL-033.

## 2. Стек и решения

| Область | Решение | Обоснование |
| --- | --- | --- |
| Frontend | React + TypeScript + Vite | Компонентный UI, проверка типов, сборка frontend |
| Backend | Python + Django + Django REST Framework | Модели, миграции, auth, Admin и REST API в одном приложении |
| База | PostgreSQL | Одна целевая СУБД для разработки, интеграционных тестов и приложения |
| Аутентификация | Django sessions + CSRF | Подходит браузерному приложению с общим origin; не требует отдельного token-сервиса |
| Admin | Django Admin | Управление контентом без разработки собственного редакторского frontend |
| API-тесты | Pytest + HTTPX | Проверка HTTP-контракта через реальную сеть и работающий backend |
| E2E | Playwright + Python + Pytest | Проверка пользовательских сценариев с тем же языком автоматизации |
| Инфраструктура | Docker + Docker Compose | Повторяемое локальное окружение |
| CI/CD | GitHub Actions | Автоматические проверки, сборка и диагностические артефакты |

Версии и необходимые адаптеры/драйверы согласуются в QIL-002. Ссылки на документацию Django 5.2 в этом документе объясняют механизм и не фиксируют runtime-версию проекта.

## 3. Будущая структура репозитория

```text
QA Interview Lab/
├── README.md
├── AGENTS.md
├── docs/
├── backend/
│   ├── config/             # Настройки Django и маршруты
│   └── apps/
│       ├── accounts/       # Пользователи и аутентификация
│       ├── learning/       # Темы, переводы, статьи, словарь
│       └── assessments/    # Вопросы, попытки, оценивание, прогресс
├── frontend/
│   └── src/                # React-компоненты и клиент API
├── tests/
│   ├── api/                # Pytest + HTTPX против поднятого backend
│   └── e2e/                # Playwright + Python + Pytest
├── compose.yaml            # Будущая локальная инфраструктура
└── .github/workflows/ci.yml # Проверки GitHub Actions
```

На QIL-001 существуют только шесть Markdown-документов. Остальные пути — план, а не готовые файлы. Модульные и интеграционные тесты Django будут размещаться внутри соответствующих backend-модулей в каталогах `tests/`.

## 4. Ответственность модулей

- `accounts`: custom User, нормализация email, регистрация, login/logout, bootstrap CSRF и определение текущего пользователя.
- `learning`: Topic, статья в переводе темы, словарь и проверка наличия обязательных текстов.
- `assessments`: вопросы и варианты, снимки попыток, проверка ответов, история и вычисление прогресса.
- Общая операция публикации вызывает проверки `learning` и `assessments`; управляется через Django Admin.

Направление связей: `assessments` ссылается на Topic и User; `learning` не импортирует модель попытки. Правило сохранности темы реализуется связями в `assessments`. Не вводятся дополнительные уровни абстракций без конкретной необходимости.

## 5. Первоначальная модель данных

`ID` — стабильный первичный идентификатор сущности. Его точный тип выбирается при реализации модели; доступ к данным определяется правами пользователя, а не сложностью угадывания ID. Время сохраняется с timezone, в UTC.

| Сущность / модуль | Основные поля | Связи и ограничения |
| --- | --- | --- |
| User / accounts | `id`, `email`, `password`, `is_active`, `is_staff`, `is_superuser`, служебные поля Django | Email уникален без учёта регистра; `password` содержит только хеш Django |
| Topic / learning | `id`, `status`, `revision`, `created_at`, `updated_at` | `status` принимает `draft` или `published`. `revision` начинается с 1 |
| TopicTranslation / learning | `id`, `topic_id`, `language`, `title`, legacy `article_body` | Уникальна пара `(topic_id, language)`; после QIL-036 тело собирается из sections, legacy-поле read-only |
| Term / learning | `id`, `topic_id`, `position` | Термин относится к одной теме |
| TermTranslation / learning | `id`, `term_id`, `language`, `name`, `definition` | Уникальна пара `(term_id, language)` |
| Question / assessments | `id`, `topic_id`, `question_type`, `position` | Тип `single_choice` или `multiple_choice`; ID общий для переводов |
| QuestionTranslation / assessments | `id`, `question_id`, `language`, `text` | Уникальна пара `(question_id, language)` |
| Choice / assessments | `id`, `question_id`, `position`, `is_correct` | Правильность хранится один раз, не зависит от языка; поле только для backend/Admin |
| ChoiceTranslation / assessments | `id`, `choice_id`, `language`, `text` | Уникальна пара `(choice_id, language)` |
| Attempt / assessments | `id`, `user_id`, `topic_id`, `status`, `created_at`, `submitted_at`, `submitted_language`, `content_snapshot`, `submitted_answers`, `correct_count`, `total_count` | `in_progress` или `submitted`; ответы и результат фиксируются при отправке; владелец неизменяем |
| TopicProgress / assessments | `id`, `user_id`, `topic_id`, `article_read_at` | Уникальна пара `(user_id, topic_id)`; язык не входит в ключ |

QIL-033 задаёт будущие TopicSection/TopicSectionTranslation с FK/UNIQUE/CHECK и сохранением legacy article_body по [TOPIC_SECTIONS_SPEC](TOPIC_SECTIONS_SPEC.md#1-состав-темы). Техническое UserProgressState содержит поколение и квитанцию последнего reset по [PROGRESS_SPEC](PROGRESS_SPEC.md#4-поколение-прогресса-и-порядок-блокировок); оно не содержит проценты/баллы и не является доступным редактору прогрессом. Этих моделей пока нет в коде.

Хранилище sessions — штатная таблица Django. Модель User задаётся через `AUTH_USER_MODEL` до первых миграций: основа `AbstractUser`, email вместо username, минимальный manager и совместимая конфигурация Admin.

`content_snapshot` и `submitted_answers` — внутренние JSON-поля PostgreSQL через Django JSONField. Снимок создаётся при начале попытки и включает названия темы, стабильные ID, порядок и типы вопросов, ID и порядок вариантов, тексты RU/EN и серверные ключи правильности. Он привязан к конкретной попытке и неизменяем. Это небольшой снимок для воспроизводимости, без отдельной системы версий контента.

Ответы содержат пары логических `question_id` и выбранных `choice_id`. Они проверяются относительно снимка, поэтому изменение исходных вопросов не ломает старые попытки. Learner API никогда не возвращает правильные ответы, `content_snapshot` или `submitted_answers` — ни до, ни после submit. До submit публичные поля вопросов формируются отдельным serializer по разрешённому списку; после submit выдаётся только агрегированный результат и метаданные истории по разделу 9.

Ограничения базы защищают FK, уникальность и допустимые значения полей. Межстрочные правила, например число правильных вариантов вопроса, проверяются серверной операцией публикации. Внешние ключи попыток и прогресса защищают Topic от физического удаления при наличии пользовательских данных.

## 6. Email, пароли и сессии

### 6.1. Email и пароль

- Одна функция нормализации email для регистрации и входа: удаление внешних пробелов и приведение к нижнему регистру в рамках политики MVP.
- Обычная уникальность сохранённого email дополняется DB-ограничением уникальности без учёта регистра. Ошибка гонки регистрации превращается в контролируемую ошибку API.
- Штатное `normalize_email` Django само по себе не является реализацией всей политики: оно приводит к нижнему регистру только доменную часть.
- Пользователь создаётся через manager, пароль устанавливается через `set_password`, проверяется штатной аутентификацией Django. Валидаторы пароля вызываются явно в регистрации.
- Сохраняется штатный безопасный hasher выбранной поддерживаемой версии Django; собственные криптографические схемы не вводятся.
- Пароль и его хеш отсутствуют в пользовательских serializers, логах и тестовых отчётах.

### 6.2. Поток сессии и CSRF

1. Frontend получает CSRF-токен через безопасный bootstrap endpoint.
2. Передаёт токен в заголовке изменяющих запросов и отправляет cookies того же origin.
3. Backend проверяет CSRF, проверяет учётные данные и создаёт Django session при login.
4. После login клиент обновляет CSRF-токен: Django может ротировать CSRF-секрет при входе.
5. После logout сервер инвалидирует session; повторное использование старой сессии не даёт доступ.

Session cookie — HttpOnly, SameSite=Lax; в HTTPS-окружении — Secure. CSRF-токен предназначен клиенту и не является паролем или session ID; его нельзя включать в отчёты. Django middleware и защита login/registration применяются также к анонимным запросам: одной DRF SessionAuthentication для этого недостаточно.

Learner API требует аутентификации по умолчанию; исключения только bootstrap CSRF, регистрация и login. Штатный `Set-Cookie` для session cookie и выдача CSRF-токена собственному клиенту по назначению разрешены. Сессионные секреты и CSRF-токены не попадают в логи, отчёты, диагностические артефакты и непредназначенные для них ответы. Django Admin использует штатную отдельную проверку staff/permissions.

### 6.3. Изоляция данных

`user_id` определяется из `request.user`, не из тела запроса. Queryset попыток и прогресса ограничен владельцем для списков и доступа по ID. Endpoint отправки также проверяет владельца до сравнения повторных payload. Эти правила действуют для learner, staff, Content Admin и superuser; административный статус не расширяет Learner API. Чужая попытка выглядит как отсутствующая; клиент не может менять readonly-поля результата или владельца.

При переходе Published → Draft тема исчезает из каталога; запрос статьи, словаря, новой отметки чтения или новой попытки возвращает `404 Not Found`. Сам переход не пересчитывает историю, прогресс и освоение. Собственные история и сохранённый прогресс остаются доступны без актуальных Draft-текстов. Для ранее начатой попытки разрешены получение публичных вопросов её snapshot до submit и отправка по нему. Внутренний snapshot клиенту не выдаётся.

### 6.4. Content Admin и permissions

Content Admin — отдельная Django-группа. У обычной учётной записи этой роли `is_staff=True`, `is_superuser=False`; права выдаются через группу, без дополнительных прямых или унаследованных grants на пользовательские данные. Superuser используется отдельно для технического администрирования и не заменяет Content Admin в работе или проверках.

| Модели | Permissions группы Content Admin |
| --- | --- |
| `Topic`, `TopicTranslation`, `Question`, `QuestionTranslation`, `Choice`, `ChoiceTranslation`, `Term`, `TermTranslation` | Только стандартные `view`, `add`, `change`, `delete` для этих моделей |
| `TopicPractice`, `PracticeTask`, `PracticeTaskTranslation` | Контентные permissions QIL-029; без PracticeSubmission |
| `TopicSection`, `TopicSectionTranslation` | Контентные permissions после QIL-036; пока NOT_IMPLEMENTED |
| `User`, `Attempt`, `TopicProgress`, `PracticeSubmission`, `UserProgressState` | Нет permissions; запрещены списки, отдельные записи, изменение и административные actions |
| Группы, permissions, sessions и прочие модели | Нет permissions; роль не может расширить собственные права |

Доступ к Admin по is_staff сам по себе не даёт модельных permissions. Запреты проверяются и по прямому URL. Публикация требует change и общей проверки полноты; delete не обходит защиту темы с историей. Тело статьи переносится из TopicTranslation в переводы sections; TopicProgress по-прежнему хранит только Read. UserProgressState — отдельный технический mutex/generation, а не редактируемые проценты.

После QIL-029 allowlist содержит 11 контентных моделей, после QIL-036 — 13. PracticeSubmission/UserProgressState не регистрируются для Content Admin. Полные ограничения — в [Practice](PRACTICE_SPEC.md#9-content-admin) и спецификации sections; документация сама permissions не меняет.

## 7. Языки и публикация

Логические Topic, Question и Choice существуют независимо от перевода. `language` хранится только в таблицах переводов и языке отправки Attempt. У TopicProgress языкового поля нет.

Языковые переключатели frontend держат два отдельных состояния: язык статьи и язык тестирования. Словарь следует языку статьи. Выбранные варианты хранятся по ID, а не по переведённому тексту. Смена языка текущей попытки запрашивает другой перевод того же снимка и сохраняет ответы.

После QIL-036 публикация проверяет название темы RU/EN, минимум один Published-раздел и оба его перевода, все вопросы/варианты и полный словарь с хотя бы одним термином. Draft-разделы скрыты и могут быть неполными. FR-11 и прежняя атомарная операция записи сохраняют проверки структуры вопросов и пробельных строк. Published-раздел parent Draft не выдаётся learner API.

Запись в Admin передаёт `expected_revision` темы из формы или подтверждения. Операция блокирует строку Topic в PostgreSQL и сверяет ревизию перед записью. Успешное изменение статуса или дочернего контента увеличивает ревизию темы. При устаревшей ревизии Admin возвращает `409 edit_conflict`, сохраняя уже записанную версию. Родитель дочерней записи выбирается при создании.

Published-тему можно редактировать с проверкой итогового содержимого внутри той же транзакции. Если публикация или правка нарушает полноту, Admin возвращает `400 incomplete_content` с деталями и откатывает запись. Подтверждённое массовое действие проверяет ревизии всех выбранных тем и применяется атомарно ко всему набору.

Смысловую эквивалентность переводов подтверждает администратор, а не проверка непустого поля. Перевод не создаёт новый ID и не меняет правильность варианта.

Статья и словарь в MVP хранятся и отображаются как текст. Редактор HTML, загрузка файлов и исполнение пользовательской разметки не требуются.

## 8. Оценивание и жизненный цикл попытки

### 8.1. Создание и отправка

1. Начало теста создаёт `in_progress` Attempt только для Published-темы со снимком всех её текущих вопросов и переводов. Проверка статуса и создание снимка выполняются в одной транзакции, согласованно со снятием публикации и редактированием. Для Draft возвращается 404; попытка не создаётся.
2. Пользователь получает только публичные поля снимка на выбранном языке: ID, тип и текст вопросов, ID и тексты вариантов. Ключи правильности отсутствуют.
3. При отправке backend проверяет владельца, CSRF, структуру ответа, язык и принадлежность ID снимку.
4. QIL-035: первый submit требует непустого ответа на каждый вопрос snapshot; неполнота даёт 400 incomplete_answers. Single-choice с несколькими ID, неизвестные ID/дубли и неверные типы дают прежний validation_error. Для исторических submitted сохраняются нормализация пропусков и идемпотентные повторы.
5. Backend в транзакции фиксирует нормализованные ответы, `submitted_language`, время, числа верных/всех вопросов и статус `submitted`.
6. Пользователь получает результат только из `correct_count`, `total_count`, `percentage` и отдельные метаданные истории. Вопросы, варианты, выбранные ответы, ключи и внутренний snapshot после submit не возвращаются. Нельзя принять клиентский процент или оценивать по изменившемуся текущему контенту.

Повтор submit с тем же attempt_id и нормализованным payload возвращает 200 с прежним результатом/датой; изменённый допустимый payload submitted даёт 409 attempt_already_submitted. Сначала блокируется текущий User по протоколу поколения, затем owned Attempt. Сравниваются язык и нормализованные наборы: порядок полей/вопросов/вариантов незначим, дубли не принимаются. Пустые ответы старых submitted нормализуются как раньше; для первого in_progress действуют новые правила полноты. После reset удалённый ID даёт 404. Точный порядок — [PROGRESS_SPEC](PROGRESS_SPEC.md#61-incomplete_answers-и-совместимость-истории).

Незавершённая попытка не участвует в истории результатов или освоении. Отдельный сценарий возобновления теста после закрытия браузера не включён в MVP.

### 8.2. Формула

Single-choice: один балл при совпадении выбранного и единственного правильного варианта. Multiple-choice: один балл при точном равенстве наборов выбранных и правильных вариантов, иначе ноль. Частичных баллов нет; порядок не важен.

`percentage = 100 * correct_count / total_count`. Для API это число с ROUND_HALF_UP до двух знаков: например, 1/32 даёт 3,13%. Все вопросы равновесны. Пропуски исторических submitted остаются в знаменателе; новый первый неполный submit после QIL-035 отклоняется, а total_count=0 не публикуется и не запускается.

Освоение: `article_read_at` задано и существует `submitted` Attempt с `100 * correct_count >= 80 * total_count` при `total_count > 0`. Условие проверяется по целым числам, не по округлённому отображаемому проценту.

### 8.3. Прогресс без дублирования

TopicProgress хранит только отметку чтения. Лучший результат и `mastered` вычисляются по завершённым Attempt; отдельные изменяемые копии этих значений не хранятся. Это исключает рассинхронизацию счётчиков на старте проекта.

До отметки может не быть TopicProgress. Старый API возвращает сохранённые собственные записи; новый completion-progress дополнительно включает все не начатые Published-темы. Read идемпотентен и не меняет первую дату; явный полный reset удаляет отметку и разрешает новую дату в новом поколении.

completion_progress вычисляется отдельно: при M>0 — 30*R + 70*S/M, при M=0 — 30*R; общий процент — среднее неокруглённых значений Published-тем, пустой каталог 0. С Practice веса 30/35/35, без неё 30/70; статусы unattempted/failed/passed и лучший сохранённый результат определены в [PROGRESS_SPEC](PROGRESS_SPEC.md#2-формулы-и-изменяемый-набор-activity). Practice не входит в is_mastered, но участвует в новом completion calculator. Текущие веса могут изменяться при публикации/удалении activity, без пересчёта snapshots/истории.

Успех на любом языке подходит для общей темы. Низкий последующий результат, изменение контента и переход в Draft не отменяют историческое выполнение условий. Расчёт использует сохранённые завершённые Attempt независимо от текущего статуса Topic. Просмотр словаря не записывает прогресс. Завершение ранее начатой попытки после снятия публикации добавляет её результат и может обновить освоение по прежнему правилу 80%; сам переход в Draft ничего не пересчитывает.

## 9. Минимальный API-контракт

Это обязательный контракт будущего Learner API с префиксом `/api/v1`; endpoints ещё не реализованы. Content Admin работает с контентом через `/admin/`, а не через изменяющие learner endpoints.

### 9.1. Общие правила, авторизация и CSRF

- Requests и responses используют JSON. Для POST требуется `Content-Type: application/json`; тело пустой операции — `{}`. GET не изменяет прогресс или результат.
- Успех: объект `data`; для списка `data` содержит массив. Исключение — `204 No Content`, у которого нет тела.
- ID в JSON передаются как непрозрачные строки; тип PK в PostgreSQL выбирается при реализации модели. Время — ISO 8601 с UTC.
- Для GET локализованного контента `language=ru` или `language=en`, по умолчанию `ru`; другое значение даёт 400. Язык start/submit задаётся в теле явно. После submit запрос языка не меняет сохранённый язык отправки.
- Аутентификация — только Django session. Session cookie передаётся штатным `Set-Cookie`, без session ID в JSON. Клиент отправляет cookie того же origin; свойства cookie заданы в разделе 6.2.
- CSRF обязателен для всех POST, включая анонимные register/login. Bootstrap выдаёт `data.csrf_token` и необходимую CSRF cookie; клиент отправляет `X-CSRFToken`. После login токен обновляется. Секреты не попадают в диагностику.
- До обработки действия проверяются сессия, CSRF и ownership. `user_id` всегда берётся из `request.user`; клиентские владельцы, баллы, ключи и неизвестные поля отклоняются. Staff/superuser не обходят ownership в Learner API.

### 9.2. Формы данных

| Имя | Разрешённые поля |
| --- | --- |
| Account | `user_id`, `email` только текущего пользователя |
| TopicSummary / Article | Сводка: `topic_id`, `title`; статья дополнительно содержит `language`, `article_body` |
| Term | `term_id`, `position`, `language`, `name`, `definition` |
| PublicQuestion | `question_id`, `position`, `question_type`, `text`, `choices`; каждый вариант: `choice_id`, `position`, `text` |
| PendingAttempt | `attempt_id`, `topic_id`, `status=in_progress`, `language`, `questions` из PublicQuestion; только до submit |
| Result | Ровно `correct_count`, `total_count`, `percentage`. Первые два — целые, `0 <= correct_count <= total_count`, `total_count > 0`; `percentage` — число 0–100 |
| SubmittedAttempt | Метаданные `attempt_id`, `topic_id`, `topic_title`, `status=submitted`, `submitted_language`, `submitted_at` и объект `result` формы Result |
| Progress | `topic_id`, `article_read_at` или `null`, `best_result` формы Result или `null`, `mastered` |

Новый CompletionProgress имеет отдельный endpoint/DTO: progress_generation, overall_completion_progress и topics с article_read_at, test/practice-статусами, completion_progress и mastered. Точные поля и JSON — [PROGRESS_SPEC](PROGRESS_SPEC.md#3-api-состояния-прогресса). SectionsArticle — отдельный DTO по [TOPIC_SECTIONS_SPEC](TOPIC_SECTIONS_SPEC.md#3-точные-learner-маршруты). Прежние Article/Progress/Result/PracticeResult не расширяются.

Result содержит только три агрегата. Метаданные SubmittedAttempt сохраняют прежние требования к истории; `topic_title` берётся из сохранённого текста темы, без текущей Draft-статьи или словаря. Лучший результат выбирается по точному отношению верных/всех вопросов отдельной попытки. Если завершённых попыток нет, `best_result=null` и `mastered=false`.

Правильные ответы тестов и Practice, ключ Choice.is_correct, внутренний snapshot, content_snapshot, task_snapshot, submitted_answers/submitted_answer и по-вопросные тестовые оценки запрещены во всех learner responses, включая ошибки, историю и ответы после submit. После submit теста не возвращаются также PublicQuestion, варианты и выбранные ответы. Serializers имеют явный разрешённый список полей и не выдают внутренний JSON целиком.

Отдельный новый PracticeResult содержит только verdict=correct|incorrect по [PRACTICE_SPEC.md](PRACTICE_SPEC.md). Он не расширяет тестовый Result и не разрешает выдачу expected_answer либо собственного сохранённого ответа. Preview/start/submit/delete практики определены отдельно; существующие endpoints и DTO этого раздела остаются прежними.

### 9.3. Endpoints и request/response

Все пути таблицы относительны к `/api/v1`. «Пользователь» означает аутентифицированного пользователя; все POST дополнительно требуют CSRF.

| Метод и путь | Доступ | Request | Успешный response |
| --- | --- | --- | --- |
| `GET /auth/csrf/` | Гость/пользователь | Без тела | `200`, `data.csrf_token` и CSRF cookie |
| `POST /auth/register/` | Гость | `email`, `password` | `201`, Account; без автоматического login |
| `POST /auth/login/` | Гость | `email`, `password` | `200`, Account и session cookie через Set-Cookie |
| `POST /auth/logout/` | Пользователь | `{}` | `204`, session инвалидирована, тела нет |
| `GET /auth/me/` | Пользователь | Без тела | `200`, Account |
| `GET /topics/` | Пользователь | Query `language` | `200`, массив TopicSummary только Published-тем |
| `GET /topics/{topic_id}/` | Пользователь | Query `language` | `200`, Article; для Draft — 404 |
| `GET /topics/{topic_id}/terms/` | Пользователь | Query `language` | `200`, массив Term; для Draft — 404 |
| `POST /topics/{topic_id}/read/` | Пользователь | `{}` | `200`, Progress после идемпотентной отметки; для Draft — 404 |
| `POST /topics/{topic_id}/attempts/` | Пользователь | `language` | `201`, PendingAttempt; только Published, иначе 404 без создания Attempt |
| `GET /attempts/{attempt_id}/` | Владелец | Query `language` применяется до submit | `200`, PendingAttempt до submit или SubmittedAttempt после него |
| `POST /attempts/{attempt_id}/submit/` | Владелец | `language`, массив `answers` | `200`, SubmittedAttempt; идентичный повтор даёт тот же результат |
| `GET /attempts/` | Пользователь | Без тела | `200`, массив только своих SubmittedAttempt, новые первыми |
| `GET /progress/` | Пользователь | Без тела | `200`, массив Progress; сохранённые собственные записи для Draft не скрываются |
| `GET /completion-progress/` | Пользователь | Без query/body | `200`, новый CompletionProgress со всеми Published-темами и поколением |
| `POST /progress/reset/` | Пользователь | confirmation, request_id | `200`, новое progress_generation; собственные Read/Attempt/PracticeSubmission удалены атомарно |
| `GET /topics/{topic_id}/sections/` | Пользователь | Query language | `200`, SectionsArticle; parent Draft → 404, Draft-разделы исключены |

answers содержит только question_id/choice_ids из snapshot. После QIL-035 первый in_progress требует все вопросы и непустые наборы; пропуски дают incomplete_answers. Для submitted нормализация и 200/409 сохранены, включая старые пропуски. Дубли/несколько вариантов Single-choice невалидны. Старый Article GET собирает текст sections с прежними четырьмя полями; тело POST read остаётся {}.

После QIL-034 все семь mutating learner POST требуют X-Progress-Generation и общего User-lock, включая Test/Practice start/submit/delete и read/reset. Header не нужен Auth/GET/Admin и не заменяет session/CSRF. До проверки generation выполняется owned lookup: старые удалённые ID дают 404, а stale create/read — 409 progress_reset. Точные поля, последние reset receipts и порядок — [PROGRESS_SPEC](PROGRESS_SPEC.md#4-поколение-прогресса-и-порядок-блокировок). Это явное изменение POST-протокола; старые GET DTO сохранены.

Для Draft запрещено создание новых попыток и чтение статьи/словаря. Чтение публичных вопросов уже начатой попытки и её submit остаются разрешёнными владельцу по snapshot. Ответы истории и прогресса не раскрывают актуальное Draft-содержимое.

### 9.4. Ошибки и HTTP-статусы

Ошибка имеет объект `error` с обязательными строками `code`, `message` и необязательным объектом `fields` с сообщениями по входным полям. Ошибки не содержат ключей правильности, snapshot, паролей, токенов или stack trace. Стандартные редиректы Django Admin не являются контрактом REST API.

| HTTP | `error.code` | Условие |
| --- | --- | --- |
| `400 Bad Request` | `validation_error` | Невалидный JSON/язык/структура ответов, неизвестные ID для начатой попытки, дубли, readonly или неизвестные поля |
| `400 Bad Request` | `invalid_credentials` | Неверный login или неактивный аккаунт; сообщение не раскрывает существование email |
| `400 Bad Request` | `incomplete_answers` | Неполный первый submit in_progress по snapshot; без записи результата |
| `403 Forbidden` | `authentication_required` или `csrf_failed` | Нет допустимой session для защищённого запроса либо не пройдена CSRF-проверка |
| `404 Not Found` | `not_found` | Объект отсутствует/чужой; статья, словарь, отметка или новая попытка для Draft |
| `409 Conflict` | `attempt_already_submitted` | Валидный изменённый payload завершённой попытки; данные остаются прежними |
| `409 Conflict` | `progress_reset` | Устаревшее поколение progress-записи; без автоматического повтора |
| `409 Conflict` | `reset_request_conflict` | UUID последнего reset повторён с другим generation |
| `405 Method Not Allowed` | `method_not_allowed` | Метод не предусмотрен контрактом |
| `415 Unsupported Media Type` | `unsupported_media_type` | Неподдерживаемый Content-Type |
| `500 Internal Server Error` | `internal_error` | Непредвиденный сбой с безопасным сообщением без внутренних данных |

При ошибке не создаётся частичный результат и не меняется чужое состояние. Проверка владельца предшествует идемпотентному повтору: знание ID не даёт возможность получить агрегаты чужой попытки.

## 10. Инфраструктура и CI

Локально планируются Compose-сервисы PostgreSQL, backend и frontend для разработки. Данные PostgreSQL сохраняются в именованном volume. Тестовые базы и окружения изолируются от базы разработки; удалять пользовательские volumes ради тестов нельзя.

Будущие настройки поступают из окружения. В репозиторий попадёт только шаблон с фиктивными значениями; реальные секреты не коммитятся. Конкретный DB-драйвер, адаптеры Pytest и способ установки Python/Node-зависимостей согласуются до добавления.

GitHub Actions запускает `backend_api`, `frontend_unit`, `frontend_check_build` и `playwright_e2e` на GitHub-hosted Ubuntu. `backend_api` использует отдельный PostgreSQL service container и временное окружение. `frontend_unit` проверяет frontend unit-тесты, `frontend_check_build` — типы и production build. QIL-018 добавил Auth E2E с реальным Django/PostgreSQL 17.11, сохранив исходный smoke; QIL-019/QIL-020 добавляют Learning/Assessment в существующий сбор тестов без изменения workflow. Полная приёмка истории/прогресса и MVP ещё предстоит. Все четыре job и критерии описаны в разделе 8 [QA-стратегии](QA_STRATEGY.md).

Jobs сохраняют JUnit-отчёты, а E2E при сбоях — очищенную диагностику только с синтетическими данными и без session/CSRF-секретов по правилам QA-стратегии. Ненулевой код проверки должен проваливать job: наличие XML-отчёта само по себе этого не обеспечивает. Автоматический deploy в текущий объём не входит.

## 11. Основные риски и ограничения

| Риск | Решение / проверка |
| --- | --- |
| Смена User после первых миграций | Email-модель определить до начальных миграций; тест Admin и создания пользователя |
| Утечка правильности или snapshot через вложенный JSON | Явные публичные serializers, негативные API-проверки всех ответов до и после submit |
| Доступ к чужому прогрессу по ID | Фильтр владельца и проверки двух пользователей на чтение/запись |
| Оценка по округлённым значениям | Целочисленное сравнение порога 80%, граничные unit-тесты |
| Редактирование вопроса во время попытки | Неизменяемый двуязычный снимок и транзакции |
| Структурно полный, но неверный перевод | Ручная содержательная проверка администратором |
| Доступность GitHub Actions и service container PostgreSQL | Подтвердить реальным запуском на GitHub-hosted Ubuntu |

Настройки времени жизни sessions, версии и точные DB-типы будут выбраны в соответствующих задачах. Архитектура не утверждает их проверенную совместимость на текущем компьютере.

## 12. Объективная практика после MVP — QIL-028

[PRACTICE_SPEC.md](PRACTICE_SPEC.md) определяет четыре новые модели внутри того же Django/PostgreSQL-монолита, ограничения FK/UNIQUE/CHECK, нормализацию, immutable snapshot, пять GET/POST-операций, ownership и удаление. Новый сервис, исполнитель кода, sandbox, внешняя проверка и зависимости не требуются. Backend реализован в apps.practice в QIL-029; PostgreSQL/HTTPX и существующая Playwright-регрессия подтверждены ручным прогоном по [PRACTICE_BACKEND](PRACTICE_BACKEND.md). Typed клиент и UI входят в QIL-030, а не в серверный этап.

TopicPractice имеет OneToOne-связь с Topic и единственный kind=single_correct_answer. PracticeTask имеет OneToOne-связь с TopicPractice, поэтому задача без включения и вторая задача на тему исключены связями БД. Перевод title/prompt отделён от общего технического контекста и канонического expected_answer. PracticeSubmission имеет собственный жизненный цикл и не использует тестовую Attempt с её счётчиками.

Изменения контентных сущностей используют существующий Topic.revision/expected_revision и блокировку Topic. Start согласован с этой же блокировкой и фиксирует версию нормализации/эталон/RU/EN. Submit/delete блокируют строку собственной PracticeSubmission. Проверка ответа выполняет только явные строковые преобразования и сравнение, не вызывает eval/exec/SQL-исполнение/сеть. Исторический verdict не пересчитывается при edit/unpublish.

Практика не участвует в is_mastered и старом Progress; QIL-033 включает её в отдельный completion_progress, не меняя правило 80% или Result. Reset становится явным owner-only исключением из сохранности работ. Account deletion остаётся отдельной возможностью; FK User CASCADE сохраняется, автоматического retention нет. POST Practice также участвуют в новом generation/mutex-протоколе.

QIL-033 не добавляет сервисы или dependencies. UserProgressState реализована additive-миграцией assessments 0004 в QIL-034. Общий User-lock охватывает все learner-записи и reset; completion GET получает согласованный снимок одной PostgreSQL-командой. Отсутствующая строка состояния означает generation=1 без записи из GET. Две контентные модели sections и их миграции остаются задачей QIL-036.

## 13. Первичные источники

- [Django: custom User до первых миграций](https://docs.djangoproject.com/en/5.2/topics/auth/customizing/#using-a-custom-user-model-when-starting-a-project).
- [Django: хранение и проверка паролей](https://docs.djangoproject.com/en/5.2/topics/auth/passwords/).
- [DRF: SessionAuthentication и CSRF](https://www.django-rest-framework.org/api-guide/authentication/#sessionauthentication).
- [DRF: ограничения object permissions для списков и создания объектов](https://www.django-rest-framework.org/api-guide/permissions/#limitations-of-object-level-permissions).
- [Playwright Python: интеграция с Pytest](https://playwright.dev/python/docs/test-runners).
- [GitHub Actions — PostgreSQL service container](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers).
