# Архитектура QA Interview Lab

Статус: архитектура MVP; пользовательский сценарий уточнён в QIL-027. Контракт Practice согласован в QIL-028, backend принят в QIL-029; UI реализован в QIL-030, полный ручной PostgreSQL/Playwright-прогон — PASS. Существующие API и архитектурные решения сохранены. [Backend](PRACTICE_BACKEND.md), [UI и runner](PRACTICE_UI.md).

QIL-033 фиксирует [архитектуру progress/reset/test flow](PROGRESS_SPEC.md) и [sections](TOPIC_SECTIONS_SPEC.md). Backend completion/reset и UserProgressState реализованы в QIL-034, UI — в QIL-035 с [отдельной приёмкой](COMPLETION_UI.md). QIL-038 добавляет локальные подтверждения и проверку полноты первого submit; [реализация и приёмка](ANSWER_FINISH.md). QIL-041 добавляет единый reader разделов и сохраняет форму legacy Article GET; TFL-06/login остаётся NOT_IMPLEMENTED. QIL-036 относится только к CI. [Границы backend](COMPLETION_BACKEND.md).

QIL-042 утвердила [section-level Read/отдельный reader](TOPIC_SECTIONS_SPEC.md). QIL-043 реализует TopicSectionProgress, новые learner endpoints/гейт start, reset и additive/data migration с проверенным provenance; [инструкция](SECTION_PROGRESS_BACKEND.md). Минимальная адаптация текущего длинного reader отдельно разрешена пользователем; отдельные страницы — QIL-044, сквозная приёмка — QIL-045. Новые правила имеют приоритет над прежними topic-level Read и неизменностью mastery при новом разделе.

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

Уточнение QIL-038: AttemptStore локально подтверждает ожидаемый question ID и открывает ровно следующий вопрос. Без выбора остаётся текущий экран с ошибкой; устаревший ID игнорируется. UI фокусирует новый заголовок, отбрасывает второй native click двойного нажатия и восстанавливает focus, если повторный mousedown вернул его на кнопку. Та же защита не допускает случайного Finish после последнего перехода; таймер задержки не используется. Последний Answer не отправляет HTTP. Выбор/подтверждения привязаны к ID, смена языка их не пересоздаёт. [Правила клиента](PROGRESS_SPEC.md#6-тест-локальное-подтверждение-и-финальная-отправка).

`AppShell` объединяет header, меню Published-тем и прогресс. На mobile меню раскрывается с aria-expanded, выбранная тема имеет aria-current. В QIL-035 OverviewContext/ProgressStore используют completion-progress API для процентов и статусов без клиентского расчёта; mastered остаётся отдельным серверным признаком. История в UI не загружается; loading/ошибка не подменяются нулём. Reset 200 подтверждается GET, до него удерживается прежний read-only view. Session change всегда очищает приватный экран, даже при активном reset. Изменение ссылки «На главную» на /login остаётся отдельным отложенным TFL-06, вне QIL-038.

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
- QIL-043: TopicSectionProgress, персональные reading endpoints и агрегатор Read относятся к assessments; learning предоставляет контент разделов и не импортирует пользовательские модели прогресса/Attempt.
- Общая операция публикации вызывает проверки `learning` и `assessments`; управляется через Django Admin.

Направление связей: `assessments` ссылается на Topic и User; `learning` не импортирует модель попытки. Правило сохранности темы реализуется связями в `assessments`. Не вводятся дополнительные уровни абстракций без конкретной необходимости.

## 5. Первоначальная модель данных

`ID` — стабильный первичный идентификатор сущности. Его точный тип выбирается при реализации модели; доступ к данным определяется правами пользователя, а не сложностью угадывания ID. Время сохраняется с timezone, в UTC.

| Сущность / модуль | Основные поля | Связи и ограничения |
| --- | --- | --- |
| User / accounts | `id`, `email`, `password`, `is_active`, `is_staff`, `is_superuser`, служебные поля Django | Email уникален без учёта регистра; `password` содержит только хеш Django |
| Topic / learning | `id`, `status`, `revision`, `created_at`, `updated_at` | `status` принимает `draft` или `published`. `revision` начинается с 1 |
| TopicTranslation / learning | `id`, `topic_id`, `language`, `title`, legacy `article_body` | Уникальна пара `(topic_id, language)`; после QIL-041 тело собирается из sections, legacy-поле read-only |
| TopicSection / learning | `id`, `topic_id`, `position`, `status`, `created_at`, `updated_at` | position >=1; порядок position/id; отложенная UNIQUE(topic, position); родитель неизменяем |
| TopicSectionTranslation / learning | `id`, `section_id`, `language`, `title`, `article_body` | UNIQUE(section, language); ru/en; Published требует полный RU/EN; родитель неизменяем |
| Term / learning | `id`, `topic_id`, `position` | Термин относится к одной теме |
| TermTranslation / learning | `id`, `term_id`, `language`, `name`, `definition` | Уникальна пара `(term_id, language)` |
| Question / assessments | `id`, `topic_id`, `question_type`, `position` | Тип `single_choice` или `multiple_choice`; ID общий для переводов |
| QuestionTranslation / assessments | `id`, `question_id`, `language`, `text` | Уникальна пара `(question_id, language)` |
| Choice / assessments | `id`, `question_id`, `position`, `is_correct` | Правильность хранится один раз, не зависит от языка; поле только для backend/Admin |
| ChoiceTranslation / assessments | `id`, `choice_id`, `language`, `text` | Уникальна пара `(choice_id, language)` |
| Attempt / assessments | `id`, `user_id`, `topic_id`, `status`, `created_at`, `submitted_at`, `submitted_language`, `content_snapshot`, `submitted_answers`, `correct_count`, `total_count` | `in_progress` или `submitted`; ответы и результат фиксируются при отправке; владелец неизменяем |
| TopicProgress / assessments | `id`, `user_id`, `topic_id`, `article_read_at` | UNIQUE(user, topic); legacy первая дата; наличие строки не означает текущий полный Read |
| TopicSectionProgress / assessments, план QIL-043 | `id`, `user_id`, `section_id`, `read_at` | UNIQUE(user, section); FK User CASCADE, section PROTECT; первая серверная UTC-дата, общий RU/EN |

QIL-041 реализует TopicSection/TopicSectionTranslation с FK/UNIQUE/CHECK и сохранением legacy article_body по [TOPIC_SECTIONS_SPEC](TOPIC_SECTIONS_SPEC.md#1-состав-темы). Техническое UserProgressState содержит поколение и квитанцию последнего reset по [PROGRESS_SPEC](PROGRESS_SPEC.md#4-поколение-прогресса-и-порядок-блокировок); оно не содержит проценты/баллы и недоступно редактору.

Хранилище sessions — штатная таблица Django. Модель User задаётся через `AUTH_USER_MODEL` до первых миграций: основа `AbstractUser`, email вместо username, минимальный manager и совместимая конфигурация Admin.

`content_snapshot` и `submitted_answers` — внутренние JSON-поля PostgreSQL через Django JSONField. Снимок создаётся при начале попытки и включает названия темы, стабильные ID, порядок и типы вопросов, ID и порядок вариантов, тексты RU/EN и серверные ключи правильности. Он привязан к конкретной попытке и неизменяем. Это небольшой снимок для воспроизводимости, без отдельной системы версий контента.

Ответы содержат пары логических `question_id` и выбранных `choice_id`. Они проверяются относительно снимка, поэтому изменение исходных вопросов не ломает старые попытки. Learner API никогда не возвращает правильные ответы, `content_snapshot` или `submitted_answers` — ни до, ни после submit. До submit публичные поля вопросов формируются отдельным serializer по разрешённому списку; после submit выдаётся только агрегированный результат и метаданные истории по разделу 9.

Ограничения базы защищают FK, уникальность и допустимые значения полей. Межстрочные правила, например число правильных вариантов вопроса, проверяются серверной операцией публикации. Внешние ключи попыток и прогресса защищают Topic от физического удаления при наличии пользовательских данных. TopicSectionProgress защищает использованный section через PROTECT; используется Draft/unpublish, включая каскадное удаление родителя. Admin не раскрывает список пользователей или ID их отметок при таком отказе.

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

При переходе Published → Draft тема исчезает из каталога; запрос статьи, словаря, новой отметки чтения или новой попытки возвращает `404 Not Found`. Даты/история/результаты не удаляются. Сам root unpublish без смены статусов разделов не меняет section Read/mastery; изменение текущего набора Published-разделов может изменить их по QIL-042. Собственные история и сохранённый прогресс остаются доступны без актуальных Draft-текстов. Для ранее начатой попытки разрешены получение публичных вопросов её snapshot до submit и отправка по нему. Внутренний snapshot клиенту не выдаётся.

### 6.4. Content Admin и permissions

Content Admin — отдельная Django-группа. У обычной учётной записи этой роли `is_staff=True`, `is_superuser=False`; права выдаются через группу, без дополнительных прямых или унаследованных grants на пользовательские данные. Superuser используется отдельно для технического администрирования и не заменяет Content Admin в работе или проверках.

| Модели | Permissions группы Content Admin |
| --- | --- |
| `Topic`, `TopicTranslation`, `Question`, `QuestionTranslation`, `Choice`, `ChoiceTranslation`, `Term`, `TermTranslation` | Только стандартные `view`, `add`, `change`, `delete` для этих моделей |
| `TopicPractice`, `PracticeTask`, `PracticeTaskTranslation` | Контентные permissions QIL-029; без PracticeSubmission |
| `TopicSection`, `TopicSectionTranslation` | Стандартные контентные permissions в QIL-041, всего 13 моделей |
| `User`, `Attempt`, `TopicProgress`, `TopicSectionProgress`, `PracticeSubmission`, `UserProgressState` | Нет permissions; запрещены списки, отдельные записи, изменение и административные actions |
| Группы, permissions, sessions и прочие модели | Нет permissions; роль не может расширить собственные права |

Доступ к Admin по is_staff сам по себе не даёт модельных permissions. Запреты проверяются и по прямому URL. Публикация требует change и общей проверки полноты; delete не обходит защиту темы с историей. Тело статьи переносится из TopicTranslation в переводы sections; TopicProgress сохраняет историческую дату; источником текущего Read после QIL-043 становится TopicSectionProgress и общая серверная агрегация. UserProgressState — отдельный технический mutex/generation, а не редактируемые проценты.

После QIL-029 allowlist содержит 11 контентных моделей, после QIL-041 — 13. PracticeSubmission/UserProgressState не регистрируются для Content Admin. Полные ограничения — в [Practice](PRACTICE_SPEC.md#9-content-admin) и спецификации sections; документация сама permissions не меняет.

## 7. Языки и публикация

Логические Topic, Question и Choice существуют независимо от перевода. `language` хранится только в таблицах переводов и языке отправки Attempt. У TopicProgress/TopicSectionProgress языкового поля нет.

Языковые переключатели frontend держат два отдельных состояния: язык статьи и язык тестирования. Словарь следует языку статьи. Выбранные варианты хранятся по ID, а не по переведённому тексту. Смена языка текущей попытки запрашивает другой перевод того же снимка и сохраняет ответы.

В QIL-041 публикация проверяет название темы RU/EN, минимум один Published-раздел и оба его перевода, все вопросы/варианты и полный словарь с хотя бы одним термином. Draft-разделы скрыты и могут быть неполными. FR-11 и прежняя атомарная операция записи сохраняют проверки структуры вопросов и пробельных строк. Published-раздел parent Draft не выдаётся learner API.

Запись в Admin передаёт `expected_revision` темы из формы или подтверждения. Операция блокирует строку Topic в PostgreSQL и сверяет ревизию перед записью. Успешное изменение статуса или дочернего контента увеличивает ревизию темы. При устаревшей ревизии Admin возвращает `409 edit_conflict`, сохраняя уже записанную версию. Родитель дочерней записи выбирается при создании.

Published-тему можно редактировать с проверкой итогового содержимого внутри той же транзакции. Если публикация или правка нарушает полноту, Admin возвращает `400 incomplete_content` с деталями и откатывает запись. Подтверждённое массовое действие проверяет ревизии всех выбранных тем и применяется атомарно ко всему набору.

Смысловую эквивалентность переводов подтверждает администратор, а не проверка непустого поля. Перевод не создаёт новый ID и не меняет правильность варианта.

Статья и словарь в MVP хранятся и отображаются как текст. Редактор HTML, загрузка файлов и исполнение пользовательской разметки не требуются.

## 8. Оценивание и жизненный цикл попытки

### 8.1. Создание и отправка

1. Начало теста создаёт `in_progress` Attempt только для Published-темы со снимком всех её текущих вопросов и переводов. Проверка статуса и создание снимка выполняются в одной транзакции, согласованно со снятием публикации и редактированием. Для Draft возвращается 404; после QIL-043 Published Topic с неполным section Read даёт 403 section_read_required. В обоих случаях Attempt не создаётся.
2. Пользователь получает только публичные поля снимка на выбранном языке: ID, тип и текст вопросов, ID и тексты вариантов. Ключи правильности отсутствуют.
3. При отправке backend проверяет владельца, CSRF, структуру ответа, язык и принадлежность ID снимку.
4. QIL-038: первый submit проходит отдельный initial serializer/validator и требует непустого ответа на каждый вопрос snapshot; неполнота даёт 400 incomplete_answers. Сначала валидируется вся структура: Single-choice с несколькими ID, неизвестные ID/дубли и неверные типы дают прежний validation_error даже вместе с пропусками. Чистый grade_snapshot не меняется. Для исторических submitted сохраняются прежний serializer, нормализация пропусков и идемпотентные повторы.
5. Backend в транзакции фиксирует нормализованные ответы, `submitted_language`, время, числа верных/всех вопросов и статус `submitted`.
6. Пользователь получает результат только из `correct_count`, `total_count`, `percentage` и отдельные метаданные истории. Вопросы, варианты, выбранные ответы, ключи и внутренний snapshot после submit не возвращаются. Нельзя принять клиентский процент или оценивать по изменившемуся текущему контенту.

Повтор submit с тем же attempt_id и нормализованным payload возвращает 200 с прежним результатом/датой; изменённый допустимый payload submitted даёт 409 attempt_already_submitted. Сначала блокируется текущий User по протоколу поколения, затем owned Attempt. Сравниваются язык и нормализованные наборы: порядок полей/вопросов/вариантов незначим, дубли не принимаются. Пустые ответы старых submitted нормализуются как раньше; для первого in_progress действуют новые правила полноты. После reset удалённый ID даёт 404. Точный порядок — [PROGRESS_SPEC](PROGRESS_SPEC.md#61-incomplete_answers-и-совместимость-истории).

Незавершённая попытка не участвует в истории результатов или освоении. Отдельный сценарий возобновления теста после закрытия браузера не включён в MVP.

### 8.2. Формула

Single-choice: один балл при совпадении выбранного и единственного правильного варианта. Multiple-choice: один балл при точном равенстве наборов выбранных и правильных вариантов, иначе ноль. Частичных баллов нет; порядок не важен.

`percentage = 100 * correct_count / total_count`. Для API это число с ROUND_HALF_UP до двух знаков: например, 1/32 даёт 3,13%. Все вопросы равновесны. Пропуски исторических submitted остаются в знаменателе; в QIL-038 новый первый неполный submit отклоняется, а total_count=0 не публикуется и не запускается.

Целевое освоение QIL-042: N>0, r=N по текущим Published-разделам и существует собственный `submitted` Attempt с `100 * correct_count >= 80 * total_count` при `total_count > 0`. Условие проверяется по целым числам, не по округлённому отображаемому проценту.

### 8.3. Прогресс без дублирования

В QIL-043 TopicSectionProgress хранит одну неизменяемую первую отметку на user/section. N — Published-разделы, r — отмеченные текущим пользователем; Read=(N>0 AND r=N). Legacy TopicProgress хранится для сохранности старой даты и не используется как обход агрегата. Best result, mastery и проценты не сохраняются редактируемыми копиями.

В прежних Progress/CompletionProgress article_read_at=null при неполном Read; при полном — историческая TopicProgress.article_read_at, если есть, иначе максимум первых read_at учитываемых разделов. GET не создаёт legacy-строку. Старый progress список также включает темы с частичными section marks, включая Draft без контентных текстов; completion включает все Published-темы, в том числе не начатые.

`article_progress=30*r/N` при N>0, иначе 0. При M>0 `completion=article_progress+70*S/M`; при M=0 только article_progress. N=0 не даёт Read/mastery и не разрешает публикацию: 400 incomplete_content. Среднее Published считается по точным дробям, потом ROUND_HALF_UP до двух знаков; пустой каталог 0. Practice учитывается в S/M, не в mastery; число вопросов не увеличивает M. [Формулы и оракулы](PROGRESS_SPEC.md#2-формулы-и-изменяемый-набор-activity).

Добавление Published section ID может уменьшить Read/completion/mastery без удаления прежних отметок или пересчёта snapshot-результата. Edit/reorder того же ID сохраняют чтение. Section unpublish меняет N, но не стирает его отметку; republish учитывает её снова. Root Topic unpublish скрывает контент/новый start/read и исключает тему из среднего; при неизменном наборе разделов Read/mastery сохраняются. Худший новый тест не отменяет лучший исторический результат.

Read/reset сериализуются общим User → UserProgressState → Topic протоколом. Reset удаляет собственные TopicSectionProgress/TopicProgress/Attempt/PracticeSubmission, повышает generation и сохраняет квитанцию; section content IDs остаются, поздний POST старого поколения не восстанавливает отметку. В момент перехода старые записи переносятся только на подтверждённый существующий section из learning 0003, не на все текущие: [миграция и её проверка происхождения](TOPIC_SECTIONS_SPEC.md#5-неразрушительная-миграция).

## 9. Минимальный API-контракт

Контракт Learner API использует префикс `/api/v1`. Базовые endpoints реализованы в предыдущих задачах; новые reading/section-detail/section-read и Read-гейт реализованы в QIL-043. Content Admin работает с контентом через `/admin/`, а не через изменяющие learner endpoints.

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
| Progress | `topic_id`, `article_read_at` или `null`, `best_result` формы Result или `null`, `mastered`; форма прежняя, Read вычисляется по sections |
| TopicReading, SectionArticle, SectionRead — план | Точные закрытые наборы полей и JSON — TOPIC_SECTIONS_SPEC §3.1; reading={total_sections,read_sections,is_read,completion_contribution}; никаких новых полей в старых DTO |

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
| `POST /topics/{topic_id}/read/` | Пользователь | `{}` | QIL-043: N=1 →200 Progress через section Read; N>1 всегда 403 section_read_required; Draft →404 |
| `POST /topics/{topic_id}/attempts/` | Пользователь | `language` | `201`, PendingAttempt; Draft →404, неполный Read →403 section_read_required, без Attempt |
| `GET /attempts/{attempt_id}/` | Владелец | Query `language` применяется до submit | `200`, PendingAttempt до submit или SubmittedAttempt после него |
| `POST /attempts/{attempt_id}/submit/` | Владелец | `language`, массив `answers` | `200`, SubmittedAttempt; идентичный повтор даёт тот же результат |
| `GET /attempts/` | Пользователь | Без тела | `200`, массив только своих SubmittedAttempt, новые первыми |
| `GET /progress/` | Пользователь | Без тела | `200`, массив Progress; сохранённые собственные записи для Draft не скрываются |
| `GET /completion-progress/` | Пользователь | Без query/body | `200`, новый CompletionProgress со всеми Published-темами и поколением |
| `POST /progress/reset/` | Пользователь | confirmation, request_id | `200`, новое progress_generation; собственные TopicSectionProgress/legacy Read/Attempt/PracticeSubmission удалены атомарно после QIL-043 |
| `GET /topics/{topic_id}/sections/` | Пользователь | Query language | `200`, прежний SectionsArticle; parent Draft →404, Draft-разделы исключены |
| `GET /topics/{topic_id}/reading/` (план) | Пользователь | Query language | `200`, TopicReading: оглавление без тел, собственный Read, generation |
| `GET /topics/{topic_id}/sections/{section_id}/` (план) | Пользователь | Query language | `200`, SectionArticle: один раздел, его read_at, соседние Published ID |
| `POST /topics/{topic_id}/sections/{section_id}/read/` (план) | Пользователь | `{}` | `200`, SectionRead, одна запись/первая дата; неверный parent/Draft →404 |

answers содержит только question_id/choice_ids из snapshot. QIL-038: первый in_progress требует все вопросы и непустые наборы; пропуски дают incomplete_answers. Для submitted нормализация и 200/409 сохранены, включая старые пропуски. Дубли/несколько вариантов Single-choice невалидны. Старый Article GET собирает текст sections с прежними четырьмя полями; тело POST read остаётся {}.

После QIL-034 все семь mutating learner POST требуют X-Progress-Generation и общего User-lock, включая Test/Practice start/submit/delete и read/reset. Header не нужен Auth/GET/Admin и не заменяет session/CSRF. До проверки generation выполняется owned lookup: старые удалённые ID дают 404, а stale create/read — 409 progress_reset. Точные поля, последние reset receipts и порядок — [PROGRESS_SPEC](PROGRESS_SPEC.md#4-поколение-прогресса-и-порядок-блокировок). Это явное изменение POST-протокола; старые GET DTO сохранены. QIL-043 добавляет восьмой mutating путь section read в ту же защиту; новый read/start gate проверяется после валидного поколения/структуры. Контентные GET ничего не записывают, персональные reading GET включают generation и защищаются клиентским progress epoch.

Для Draft запрещено создание новых попыток и чтение статьи/словаря. Чтение публичных вопросов уже начатой попытки и её submit остаются разрешёнными владельцу по snapshot. Ответы истории и прогресса не раскрывают актуальное Draft-содержимое.

Новый UI: `/topics/{topic_id}` — оглавление; `/topics/{topic_id}/sections/{section_id}` — отдельный reader с language в URL. Старые #section-ID переводятся только в проверенный внутренний путь. Навигация/focus/pending/visibility и точные ответы — [TOPIC_SECTIONS_SPEC](TOPIC_SECTIONS_SPEC.md#3-точные-learner-маршруты).

### 9.4. Ошибки и HTTP-статусы

Ошибка имеет объект `error` с обязательными строками `code`, `message` и необязательным объектом `fields` с сообщениями по входным полям. Ошибки не содержат ключей правильности, snapshot, паролей, токенов или stack trace. Стандартные редиректы Django Admin не являются контрактом REST API.

| HTTP | `error.code` | Условие |
| --- | --- | --- |
| `400 Bad Request` | `validation_error` | Невалидный JSON/язык/структура ответов, неизвестные ID для начатой попытки, дубли, readonly или неизвестные поля |
| `400 Bad Request` | `invalid_credentials` | Неверный login или неактивный аккаунт; сообщение не раскрывает существование email |
| `400 Bad Request` | `incomplete_answers` | Неполный первый submit in_progress по snapshot; без записи результата |
| `400 Bad Request` | `incomplete_content` | Контентный Admin: неполный RU/EN или Published Topic без разделов; полный rollback |
| `403 Forbidden` | `authentication_required` или `csrf_failed` | Нет допустимой session для защищённого запроса либо не пройдена CSRF-проверка |
| `403 Forbidden` | `section_read_required` | QIL-043: новый Test/Practice start до всех Published section Read; legacy read при N>1 всегда без записи |
| `403 Forbidden` | `practice_locked` | Practice start: полный section Read есть, но своего submitted-теста нет |
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

QIL-042 уточняет только новый start: полный агрегированный Read → затем любой submitted-тест; неполное чтение даёт 403 section_read_required, при полном чтении без теста остаётся practice_locked. Это реализованное в QIL-043 переопределение старого условия наличия TopicProgress в PRACTICE_SPEC; preview blocked_by остаётся article_not_read/test_not_submitted с новой семантикой Read. Owned GET/submit уже начатой работы по snapshot не получает этот гейт.

Практика не участвует в is_mastered и старом Progress; QIL-033 включает её в отдельный completion_progress, не меняя правило 80% или Result. Reset становится явным owner-only исключением из сохранности работ. Account deletion остаётся отдельной возможностью; FK User CASCADE сохраняется, автоматического retention нет. POST Practice также участвуют в новом generation/mutex-протоколе.

QIL-033 не добавляет сервисы или dependencies. UserProgressState реализована additive-миграцией assessments 0004 в QIL-034. Общий User-lock охватывает все learner-записи и reset; completion GET получает согласованный снимок одной PostgreSQL-командой. Отсутствующая строка состояния означает generation=1 без записи из GET. QIL-041 добавляет две контентные модели sections и additive/data migration learning 0003. Sections/legacy Article GET блокирует Topic на время согласованного чтения; writers используют ту же блокировку с expected_revision.

## 13. Первичные источники

- [Django: custom User до первых миграций](https://docs.djangoproject.com/en/5.2/topics/auth/customizing/#using-a-custom-user-model-when-starting-a-project).
- [Django: хранение и проверка паролей](https://docs.djangoproject.com/en/5.2/topics/auth/passwords/).
- [DRF: SessionAuthentication и CSRF](https://www.django-rest-framework.org/api-guide/authentication/#sessionauthentication).
- [DRF: ограничения object permissions для списков и создания объектов](https://www.django-rest-framework.org/api-guide/permissions/#limitations-of-object-level-permissions).
- [Playwright Python: интеграция с Pytest](https://playwright.dev/python/docs/test-runners).
- [GitHub Actions — PostgreSQL service container](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers).
