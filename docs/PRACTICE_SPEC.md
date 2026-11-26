# Объективная практика — QIL-028

Уточнение QIL-033 от 23 ноября 2026 года: утверждены [completion_progress/reset/test flow](PROGRESS_SPEC.md) и [sections](TOPIC_SECTIONS_SPEC.md). Backend QIL-034 реализует generation/reset и участие Practice в отдельном completion_progress; текущий QIL-035 добавляет [Progress/reset UI](COMPLETION_UI.md) без изменения checker/API. Answer/Finish реализован отдельно; QIL-041 добавляет sections и расширяет контентную роль до 13 моделей без изменения Practice API/checker. Immutable snapshot, отдельная PracticeSubmission и независимость от mastery сохраняются. [Границы серверного этапа](COMPLETION_BACKEND.md).

Статус: требования и API согласованы пользователем 19 ноября 2026 года в QIL-028. Backend принят в QIL-029; Practice UI реализован в QIL-030, полный ручной PostgreSQL/Playwright-прогон — PASS. [Backend](PRACTICE_BACKEND.md), [UI и runner](PRACTICE_UI.md). На исходном commit `60a01aa` моделей и endpoints Practice нет. Успешный CI документации не является приёмкой функциональности.

Источники: [PRD](PRD.md), [архитектура](ARCHITECTURE.md), [QA-стратегия](QA_STRATEGY.md), [backlog](BACKLOG.md), [правила Codex](../AGENTS.md). Этот документ — точная спецификация отдельного инкремента после базового MVP; FR-01–FR-13 и NFR-01–NFR-03 сохраняются.

## 1. Назначение и границы

Учебный маршрут: статья → тест → практика. Первый kind — `single_correct_answer`: пользователь вводит точный текстовый результат, backend сравнивает его с одним каноническим `expected_answer`. Код и SQL из условия или ответа не исполняются. Не используются sandbox, внешние API, ИИ, rubric, списки допустимых ответов, regex и семантическое сравнение.

Для Python это, например, определение вывода `print('text')`; канонический результат синтетического примера — `text`. Для SQL первая версия поддерживает только scalar-result: ровно одну строку и один столбец. Написание произвольного решения, эквивалентные SQL-запросы, табличные результаты и ручная оценка остаются будущими возможностями.

| ID | Требование |
| --- | --- |
| PRA-01 | Только явный TopicPractice включает практику; одна PracticeTask на тему |
| PRA-02 | Детерминированный общий технический контекст и один серверный эталон; исполнения кода нет |
| PRA-03 | Полные RU/EN-инструкции и атомарная публикация; ID и эталон общие |
| PRA-04 | Версионированная минимальная нормализация, условно допустимый пустой ответ, лимит 5000 |
| PRA-05 | Django session, CSRF, owner-only данные; начало после Read и любого submitted-теста |
| PRA-06 | Immutable snapshot создаётся при явном start |
| PRA-07 | Атомарный submit: идентичный нормализованный payload → 200, изменённый завершённый → 409 |
| PRA-08 | Публичный результат — только verdict; эталон, внутренний snapshot и сохранённый ответ не выдаются |
| PRA-09 | Practice не меняет mastery и Read; Published Task участвует в отдельном completion_progress по QIL-033 |
| PRA-10 | Content Admin управляет 11 моделями после QIL-029, 13 после sections QIL-041; PracticeSubmission/UserProgressState недоступны |
| PRA-11 | Ответ хранится до удаления работы владельцем, полного reset или удаления аккаунта; фонового retention нет |
| PRA-12 | Доступные UI-состояния, независимый RU/EN, безопасные повторы и проверки полного сценария |

## 2. Модели и ограничения

Все PK — BigAutoField, как у текущих моделей; в API ID представлены непрозрачными строками. FK обязательны, если явно не указано иное. Даты timezone-aware, API использует ISO 8601 UTC. Родительские связи и владелец после создания неизменяемы.

### 2.1. TopicPractice

Поля: `id`, `topic` (OneToOneField, UNIQUE, PROTECT), `practice_kind` (не NULL, только `single_correct_answer`), `created_at`, `updated_at`.

Отсутствие строки означает отсутствие practice_kind у Topic. Наименование темы и её язык не включают практику автоматически. Существующие темы при миграции не получают TopicPractice.

### 2.2. PracticeTask

Поля: `id`, `topic_practice` (OneToOneField, UNIQUE, PROTECT), `status` (`draft` по умолчанию или `published`), `source_type` (`python`, `sql`, `other`), `source_text`, `input_data`, `environment`, `output_spec`, `expected_answer`, `normalization_mode`, `created_at`, `updated_at`.

Текстовые поля не NULL. `input_data=""` означает явно отсутствие внешнего ввода; для SQL поле обязано описывать схему и полный набор исходных строк. Для Published обязательны непустые source_text, environment и output_spec. Environment фиксирует существенные версию/диалект/настройки. Source_type определяет представление контекста, но не выбирает исполнитель: алгоритм проверки всегда сравнивает строки.

`expected_answer` — серверный TextField, допускающий пустую строку, но не NULL; максимум 5000 Unicode scalar values. `normalization_mode` — `lf_trim_outer_v1` по умолчанию либо `lf_exact_v1`. При публикации эталон уже должен быть каноническим: `N(expected_answer) == expected_answer`. Правильность эталона и детерминизм проверяет редактор; публикация не запускает пример. Пустой эталон редактор подтверждает как намеренный, а не как забытое поле.

Две связи OneToOne обеспечивают одну задачу на Topic. Обязательный FK к TopicPractice и CHECK его kind исключают задачу у темы без practice_kind. Отдельного nullable-флага, противоречащего этой связи, нет.

### 2.3. PracticeTaskTranslation

Поля: `id`, `task` (FK, CASCADE), `language` (`ru` или `en`), `title`, `prompt`.

UNIQUE(task, language), CHECK языка; title/prompt не NULL. Draft может быть неполным. Published требует непустые title/prompt для обеих локалей. Только поясняющие тексты переводятся: source_text, input_data, environment, output_spec, эталон и политика нормализации общие. Изменение строкового литерала в коде при переводе не считается допустимым переводом того же задания.

### 2.4. PracticeSubmission

Поля: `id`, `user` (FK User, CASCADE), `task` (FK PracticeTask, PROTECT), `status` (`in_progress` или `submitted`), `task_snapshot` (JSONField), `submitted_answer` (TextField, nullable до submit), `submitted_language` (nullable до submit), `verdict` (nullable до submit), `created_at`, `submitted_at` (nullable до submit).

`submitted_answer` хранит нормализованную строку, включая допустимую пустую строку. Исходный ненормализованный текст отдельно не сохраняется.

DB CHECK состояния:
- in_progress: submitted_answer, submitted_language, verdict, submitted_at равны NULL;
- submitted: эти поля не NULL; язык ru/en; verdict только correct/incorrect. Пустая строка submitted_answer не равна NULL и допустима.

DB CHECK ограничивает kind, source_type, статусы, режимы нормализации и языки; char_length(expected_answer) и char_length(submitted_answer) не превышают 5000. FK, NOT NULL и UNIQUE реализуются в PostgreSQL. Межтабличная полнота RU/EN, каноничность и условия публикации проверяются доменной транзакцией. Индекс(user, status, id) обслуживает owner lookup. UNIQUE(user, task) нет: новые явно начатые работы разрешены.

Task snapshot, user, task и created_at после создания не меняются. После submitted ответ, язык, verdict и submitted_at неизменяемы. Отдельные PracticeAttempt, таблица результата и поля тестовых correct_count/total_count не добавляются.

## 3. Нормализация и пустой ответ

N применяется только на сервере и одинаково при подготовке эталона и проверке ответа:
1. CRLF заменяется на LF.
2. Оставшиеся CR заменяются на LF.
3. Для lf_exact_v1 больше ничего не меняется.
4. Для lf_trim_outer_v1 с двух концов всей строки удаляются только U+0020 (обычный пробел) и U+000A (LF).

Табуляции, NBSP, внутренние пробелы, отступы отдельных строк, регистр, пунктуация, кавычки, Unicode normalization и представление чисел не меняются. Два символа `\n` не превращаются в перевод строки. Нет SQL parsing, сортировки, удаления заголовков, case-folding и «умного» сравнения.

Лимит — 5000 Unicode scalar values исходной строки ДО N; фронтенд считает code points, а не UTF-16 code units. U+0000 и некорректные одиночные surrogate code points отклоняются с 400. Для остальных символов нет скрытых преобразований. Канонический эталон также укладывается в 5000.

Порядок проверки:
- missing/null/number/bool/list/object вместо строки, превышение лимита и некорректный Unicode → 400 validation_error;
- после N, для in_progress: если ответ пуст, а snapshot expected_answer непуст, → 400 validation_error, без записи результата;
- если эталон пуст, пустой нормализованный ответ допустим и даёт correct; непустая строка даёт incorrect;
- после структурной валидации для уже submitted сначала применяется правило повторного submit из раздела 5. Изменённая строка, включая пустую, даёт 409; новое состояние не записывается.

Публичного allow_empty_answer, длины/хеша эталона и производных подсказок нет. Поэтому клиент не ставит required на поле ответа и не блокирует отправку только из-за пустоты: допустимость решает сервер.

| Эталон | Режим | Исходный ответ | Ожидание для in_progress |
| --- | --- | --- | --- |
| text | lf_trim_outer_v1 | text | 200 correct |
| text | lf_trim_outer_v1 | обычный пробел + text + CRLF | 200 correct |
| text | lf_trim_outer_v1 | Text или 'text' | 200 incorrect |
| text | lf_trim_outer_v1 | text + TAB или NBSP | 200 incorrect |
| text | lf_trim_outer_v1 | только обычные пробелы/LF | 400 validation_error |
| пустая строка | lf_trim_outer_v1 | пусто или обычные пробелы/LF | 200 correct |
| пустая строка | lf_trim_outer_v1 | TAB | 200 incorrect |
| пустая строка | lf_exact_v1 | один обычный пробел | 200 incorrect |
| text | lf_exact_v1 | text + LF | 200 incorrect |

v1 означает неизменяемую семантику. Будущая политика получает новый идентификатор; обработчики v1 сохраняются для существующих snapshot.

## 4. SQL scalar-result и публикация

SQL-условие фиксирует диалект/версию, необходимые timezone/collation, schema/types и все входные данные. Query находится в source_text. Результат обязан иметь ровно одну строку и один столбец; их порядок объявлен как единственный. Zero rows и таблицы не входят в scalar-result. COUNT с результатом 0 является допустимым скаляром.

Output_spec объявляет точное текстовое представление единственного значения: без таблицы/заголовка/имени столбца, SQL NULL — `NULL`, boolean — `true`/`false`, у чисел точка как decimal separator и явно заданная точность, у текста — само значение. Кавычки вводятся только если являются частью значения. Переносы, пустая строка и значимые пробелы оговариваются явно. Нормализатор не приводит `4.0` к `4`.

Недетерминированные условия (текущее время, random, внешние данные, неоговорённый выбор строки) не публикуются. Это структурная проверка и редакторское подтверждение, без запуска query или попыток доказать SQL-семантику на сервере.

Все три контентные модели меняются через транзакцию дерева Topic: select_for_update Topic + expected_revision. Успешная запись увеличивает Topic.revision; устаревшая — 409 edit_conflict. Published PracticeTask сохраняется только с полным допустимым контентом; отказ — 400 incomplete_content с полным rollback. Полнота обычной Topic по FR-11 сохраняется; TopicPractice без готовой задачи не запрещает публиковать статью и тест.

## 5. Доступ, snapshot и конкурентность

Preview доступен аутентифицированному пользователю только для Published Topic и Published PracticeTask через TopicPractice. Без включения, задачи или публикации — 404. Карточка может показываться до выполнения prerequisites, но не выдаёт полное условие.

Start дополнительно требует TopicProgress.article_read_at и хотя бы один собственный Attempt со status=submitted по той же Topic. Балл любой; in_progress-тест не подходит. Исторические завершённые тесты подходят после редактирования контента. Язык не входит в ключ допуска. При нехватке prerequisites — 403 practice_locked.

Start вызывается явно, создаёт одну новую in_progress-запись и snapshot в одной транзакции, согласованной с редактурой и unpublish через блокировку Topic. GET, показ карточки и переключение RU/EN не создают работу.

Snapshot сохраняет topic_id, task_id, source_revision, kind, source_type, source_text, input_data, environment, output_spec, title/prompt RU/EN, expected_answer, normalization_mode и answer_max_length=5000. В нём нет ключей или ответов тестового Attempt. Редактура задания/эталона/режима и смена публикации не меняют snapshot.

Submit блокирует строку собственной PracticeSubmission. После проверки структуры и N:
- in_progress → submitted: сравнить с snapshot expected_answer, сохранить N(answer_text), language, verdict и первое submitted_at;
- submitted с теми же N(answer_text) и language → 200, полностью прежний SubmittedPracticeSubmission;
- submitted с изменением N(answer_text) или language → 409 practice_already_submitted, без перезаписи;
- неверный тип/слишком длинный текст остаётся 400 даже при повторе, поскольку это не допустимый payload.

Порядок JSON-ключей незначим. Нормализация — только раздел 3; изменение регистра или значимого пробела считается изменённым ответом. При двух одинаковых конкурентных submit обе стороны получают одну сохранённую запись; при разных payload один записывается, второй получает 409.

После unpublish Topic/Task preview и новые start дают 404. Владелец продолжает GET и submit начатой работы по snapshot; актуальный Draft-контент не читается. После submitted GET возвращает прежний verdict. Ни unpublish, ни исправление эталона не пересчитывают результаты.

## 6. API: общие правила

Новые пути находятся под `/api/v1` и не изменяют существующие Article, Attempt, Result и Progress. Практический результат называется PracticeResult. Тестовый Result по-прежнему содержит только correct_count, total_count, percentage; запреты тестовых ответов и ключей не ослабляются.

Все объекты ниже имеют точный разрешённый набор полей; дополнительные поля запросов отклоняются. ID — строки положительных PK; невалидный/отсутствующий/чужой ID ресурса → 404. Время — ISO 8601 UTC.

Аутентификация — Django session; клиент использует credentials: include. Каждый POST требует CSRF cookie и X-CSRFToken, включая delete. Штатный GET /api/v1/auth/csrf/ используется существующим клиентом по назначению; токен не добавляется к DTO Practice. CSRF middleware не отключается.

После QIL-034 каждый Practice POST дополнительно требует X-Progress-Generation из GET /api/v1/completion-progress/. Общий mutex текущего User берётся до Topic/submission-lock; отсутствующий/невалидный header даёт 400 validation_error, устаревший — 409 progress_reset, без автоматического обновления и повторения POST. Lookup чужой/удалённой работы остаётся 404 до проверки generation и тела. Точный протокол/квитанция reset — [PROGRESS_SPEC](PROGRESS_SPEC.md#4-поколение-прогресса-и-порядок-блокировок). GET/DTO Practice не расширяются.

Для POST обязателен Content-Type application/json и JSON object. Query-параметры POST запрещены. GET допускает только один `language=ru|en`, по умолчанию ru; пустое, повторное, неизвестное значение/параметр → 400.

Порядок отказов: штатная CSRF-проверка unsafe-запроса выполняется до view; с корректным CSRF проверяются HTTP-метод, session, доступный ресурс/ownership, затем payload/query и бизнес-правила. Для чужого/отсутствующего submission возвращается 404 до разбора payload и до идемпотентного ответа. Все списки/lookup ограничены request.user; staff/Content Admin/superuser не обходят ownership.

GET ничего не записывает. Ответы Practice не кешируются. API никогда не выдаёт expected_answer, canonical/expected hash/length, внутренний task_snapshot, source_revision, submitted_answer, owner ID, session ID или производный diff/подсказку из эталона. Нет публичного списка submissions.

### 6.1. Пути

| Метод и точный путь | Request | Успешный response |
| --- | --- | --- |
| GET /api/v1/topics/{topic_id}/practice/ | Query language | 200, data формы PracticePreview |
| POST /api/v1/topics/{topic_id}/practice/submissions/ | language | 201, data формы PendingPracticeSubmission |
| GET /api/v1/practice-submissions/{submission_id}/ | Query language | 200, data формы PendingPracticeSubmission или SubmittedPracticeSubmission |
| POST /api/v1/practice-submissions/{submission_id}/submit/ | language, answer_text | 200, data формы SubmittedPracticeSubmission |
| POST /api/v1/practice-submissions/{submission_id}/delete/ | Пустой объект {} | 204, без тела |

Все POST начинают/меняют только собственные работы. Delete задан как POST с {} для совместимости с существующим typed GET/POST wrapper и обработкой 204; метод DELETE для этого URL не предусмотрен.

### 6.2. Публичные формы

PracticePreview: topic_id, task_id, practice_kind, language, title, can_start (boolean), blocked_by (массив кодов), normalization_mode, answer_max_length. blocked_by содержит только недостающие `article_not_read`, затем `test_not_submitted`; пустой массив означает can_start=true. Это статусы только текущего пользователя. Полное условие в preview отсутствует.

PendingPracticeSubmission: submission_id, topic_id, task_id, status=in_progress, language и task. Вложенный task содержит ровно practice_kind, source_type, title, prompt, source_text, input_data, environment, output_spec, normalization_mode, answer_max_length. Все значения берутся из snapshot; title/prompt — на выбранном языке.

SubmittedPracticeSubmission: submission_id, topic_id, task_id, task_title, status=submitted, submitted_language, submitted_at, result. task_title берётся из snapshot на submitted_language. PracticeResult содержит ровно `verdict` со значением `correct` или `incorrect`. Условие и сохранённый ответ после submit через этот GET не возвращаются. Валидный GET language не меняет submitted_language или verdict.

Ниже только синтетические примеры, не записи локальной БД.

Preview с непрочитанной статьёй и уже завершённым тестом:

```json
{
  "data": {
    "topic_id": "41",
    "task_id": "73",
    "practice_kind": "single_correct_answer",
    "language": "ru",
    "title": "Вывод программы",
    "can_start": false,
    "blocked_by": ["article_not_read"],
    "normalization_mode": "lf_trim_outer_v1",
    "answer_max_length": 5000
  }
}
```

Точное тело start:

```json
{"language": "ru"}
```

Ответ 201 на разрешённый start:

```json
{
  "data": {
    "submission_id": "501",
    "topic_id": "41",
    "task_id": "73",
    "status": "in_progress",
    "language": "ru",
    "task": {
      "practice_kind": "single_correct_answer",
      "source_type": "python",
      "title": "Вывод программы",
      "prompt": "Укажите текст, который выводит программа.",
      "source_text": "print('text')",
      "input_data": "",
      "environment": "Python 3.14.2",
      "output_spec": "stdout text",
      "normalization_mode": "lf_trim_outer_v1",
      "answer_max_length": 5000
    }
  }
}
```

Точное тело submit для этого синтетического примера:

```json
{"language": "ru", "answer_text": "text"}
```

Допустимое тело для задания с пустым эталоном:

```json
{"language": "ru", "answer_text": ""}
```

Ответ 200 после submit:

```json
{
  "data": {
    "submission_id": "501",
    "topic_id": "41",
    "task_id": "73",
    "task_title": "Вывод программы",
    "status": "submitted",
    "submitted_language": "ru",
    "submitted_at": "2026-11-19T10:00:00Z",
    "result": {"verdict": "correct"}
  }
}
```

Точное тело delete:

```json
{}
```

### 6.3. Ошибки

Форма: error с обязательными непустыми строками code/message и необязательным fields — объектом списков строк по полям. message безопасен; точная фраза не является стабильным идентификатором, клиент использует code. Значения входного ответа, эталона, SQL/traceback и настройки не отражаются в ошибках.

| HTTP | error.code | Условие |
| --- | --- | --- |
| 400 | validation_error | Невалидный JSON, язык, query, поля, тип/лимит/Unicode ответа; недопустимый пустой ответ начатой работы |
| 403 | authentication_required | Нет Django session; для POST этот случай проверяется с корректным CSRF |
| 403 | csrf_failed | Cookie/header отсутствуют или неверны; запись не меняется |
| 403 | practice_locked | Start до Read или без собственной submitted-попытки теста |
| 404 | not_found | Неизвестный/чужой submission; нет включения/Task/публикации для preview/start; удалённая работа |
| 409 | practice_already_submitted | Структурно допустимый изменённый payload завершённой работы |
| 409 | progress_reset | Поколение Practice POST устарело после полного reset; удалённый ID вместо этого даёт 404 |
| 405 | method_not_allowed | Метод не предусмотрен для URL; Allow соответствует таблице путей |
| 415 | unsupported_media_type | Для POST не application/json |
| 500 | internal_error | Непредвиденная ошибка с безопасным сообщением; не превращается в 400 |

```json
{
  "error": {
    "code": "validation_error",
    "message": "Invalid practice request.",
    "fields": {"answer_text": ["Expected a string."]}
  }
}
```

```json
{"error": {"code": "practice_locked", "message": "Read the article and submit a test first."}}
```

```json
{"error": {"code": "practice_already_submitted", "message": "This practice submission has already been submitted."}}
```

Отказ не создаёт частичного результата. 400/403 позволяют исправить подтверждённо непринятый запрос; 409 не разрешает редактировать сохранённую работу.

## 7. Хранение, удаление и неизменность mastery

Хранятся snapshot, нормализованный submitted_answer и verdict до явного удаления работы владельцем, подтверждённого полного reset либо удаления аккаунта. Автоматических TTL, retention jobs, очистки черновиков и скрытого удаления при unpublish/edit нет. Ненормализованный текст отдельно не сохраняется. Ответы/ключи не логируются и не попадают в reports/artifacts. Условия синтетические; ввод напоминает не вставлять персональные данные/секреты. Автоматическая редактура текста не добавляется в нормализацию.

POST delete атомарно удаляет всю собственную PracticeSubmission, включая snapshot/ответ/verdict. Требуются явное подтверждение пользователя в UI и корректный CSRF. Чужая работа не удаляется. Для аутентифицированного запроса повтор delete, GET и submit удалённого ID дают 404; при отсутствии session остаётся 403 authentication_required. После удаления обещание идемпотентного submit прекращается, поскольку записи больше нет. User FK CASCADE удаляет работы при отдельно согласованном удалении аккаунта; новый account-delete endpoint в этот инкремент не входит.

При гонке submit/delete блокируется одна строка: submit может завершиться до удаления, либо после удаления получить 404; восстановление удалённой записи и изменение чужих строк запрещены.

При отдельном delete PracticeSubmission Read и Attempt не удаляются. Mastery остаётся `article_read_at != null AND EXISTS submitted Attempt: 100 * correct_count >= 80 * total_count при total_count > 0`; Practice в этот запрос не входит. По QIL-033 новый процент — среднее completion_progress Published Topic: Read=30%, тест/Published Practice делят 70%; без Practice тест получает 70%. Статус passed означает любой сохранённый correct, failed — только incorrect, unattempted — нет submitted. Удаление последнего correct может снизить новый процент, но не mastery. Отсутствие TopicPractice не исключает тему из общего среднего.

Полный reset — отдельная операция, удаляющая все собственные Read, Attempt и PracticeSubmission, включая историю/in_progress/Draft, с повышением generation. Вся работа (ответ/snapshot/verdict) удаляется, старые ID дают 404, повторный start возможен только после повторного выполнения Read+submitted-test. Поздний start/submit/delete не восстанавливает данные; другие пользователи и контент не затронуты. Это утверждённое исключение, а не скрытая очистка при редактировании. Точный API — [PROGRESS_SPEC](PROGRESS_SPEC.md#5-reset-api-и-история).

## 8. UI и безопасные сетевые сценарии

Маршруты UI: `/topics/{topic_id}/practice` для карточки и явного начала; `/practice-submissions/{submission_id}` для работы/результата. Текущие маршруты и AppShell сохраняются. Practice-кнопка на теме/результате теста использует отдельный preview GET; 404 скрывает вход в практику. Catalog/Article/Test/Progress DTO не получают дополнительные поля. До prerequisites карточка объясняет блокировку; доступ проверяется повторно на backend.

Полный текст условия, общий код/данные и правило нормализации отображаются как текст, без исполнения HTML/JS/SQL. Русский UI, независимый RU/EN задания, keyboard/focus/mobile 1280×900 и 390×844. Смена языка сохраняет неотправленный ввод и не выполняет POST. До submit текст только в памяти; нет localStorage/sessionStorage или auto-save. Уход с несохранённым ответом сопровождается предупреждением. Reload восстанавливает условие и статус, но не неотправленный текст.

Кнопка submit не блокируется из-за пустоты; HTML required не используется. Лимит считается по Unicode scalar values. Пока POST выполняется, повторное нажатие блокируется. После submit показаны только контекст и Верно/Неверно; вопрос/ввод убраны, эталон и diff отсутствуют. Новый start разрешён явно; история и счётчики практических попыток в UI не добавляются. Удаление решения имеет отдельное подтверждение и возвращает к практике темы, а если она недоступна — к каталогу, без next/returnTo.

Typed API-клиент добавляет отдельные practice DTO/decoders и методы поверх существующего wrapper: credentials: include, CSRF в памяти, ApiError, timeout. Expected_answer не попадает в frontend-типы, конфигурацию, bundle или ответы API.

Start не повторяется автоматически. При потере его ответа UI сообщает, что явный новый start может создать ещё одну начатую работу, как у текущего Test. На неопределённом submit payload фиксируется; GET известного ID проверяет результат. Только после in_progress разрешён явный повтор того же payload. После 409 выполняется GET сохранённого результата. Timeout delete разрешается GET: 404 подтверждает отсутствие записи, существующая работа допускает явный повтор удаления. Автоматических повторов POST нет.

## 9. Content Admin

После QIL-029 группа получает view/add/change/delete на 11 моделях; QIL-041 добавляет ещё две, итого 13:
- существующие Topic, TopicTranslation, Term, TermTranslation, Question, QuestionTranslation, Choice, ChoiceTranslation;
- новые TopicPractice, PracticeTask, PracticeTaskTranslation.
- TopicSection, TopicSectionTranslation после реализации sections по [TOPIC_SECTIONS_SPEC](TOPIC_SECTIONS_SPEC.md).

До QIL-029 фактический allowlist содержит прежние восемь моделей. Публикация PracticeTask требует change и доменной проверки; массовая операция и inline не обходят транзакцию/ревизию. Пустой эталон проверяется редактором как намеренный.

На PracticeSubmission, User, Group, permissions, sessions, Attempt, TopicProgress и UserProgressState прав нет; список/карточка/actions/inline/export и прямые URL закрыты. PracticeSubmission и техническое состояние reset не регистрируются для Content Admin. Staff не означает доступ к чужим learner-данным; superuser не заменяет роль в тестах.

FK PROTECT не даёт удалить TopicPractice с задачей или PracticeTask с работами. Снятие публикации выполняется через Draft и не удаляет пользовательские данные. Отдельная роль Reviewer и просмотр чужих ответов не вводятся.

## 10. QA-план и критерии приёмки

Ниже план QIL-029, а не выполненные проверки QIL-028. DB-сценарии используют отдельную PostgreSQL; API — настоящий HTTPX/TCP; UI — реальный frontend/backend/БД через Playwright. SQLite, mocks транспорта и superuser вместо роли не являются доказательством.

| ID | Требования | Проверка / оракул | Уровень |
| --- | --- | --- | --- |
| PQA-01 | PRA-01 | Миграция не включает существующие темы; без TopicPractice создать Task нельзя даже через FK; дубли TopicPractice/Task запрещены | PostgreSQL |
| PQA-02 | PRA-01, PRA-03 | CHECK kind/status/source_type/mode/language; NOT NULL; unique перевода; неизменяемые родители | PostgreSQL |
| PQA-03 | PRA-02, PRA-03 | Общие source/input/эталон RU/EN; перевод не меняет литералы; один scalar SQL, полные schema/data/environment/output | Domain, ручная |
| PQA-04 | PRA-03 | Полный Published принимается; неполный/неканонический откатывается; Draft допускает неполноту; пустой эталон допустим | Domain, Admin HTTP |
| PQA-05 | PRA-03 | Конкурентная правка одной Topic.revision: одна запись, второй 409; child edit увеличивает revision | PostgreSQL |
| PQA-06 | PRA-04 | Оба режима: CRLF/CR/LF, крайние/внутренние пробелы, indentation, TAB/NBSP, case/quotes/punctuation, literal backslash-n; нормализация идемпотентна | Unit |
| PQA-07 | PRA-04 | Пустой эталон + пусто/пробелы по обоим режимам; непустой эталон + пусто → 400; nonempty против пустого → incorrect; пустой изменённый repeat → 409 | Unit, DB, HTTPX |
| PQA-08 | PRA-04 | Missing/null/int/float/bool/list/object → 400; 0/4999/5000/5001 code points; astral Unicode, NUL/surrogates; raw limit до N | Unit, HTTPX |
| PQA-09 | PRA-05 | Все комбинации Read/test: только оба условия открывают start; любой submitted-балл подходит; in_progress/чужой тест не подходит | PostgreSQL, HTTPX |
| PQA-10 | PRA-05 | Гость/нет CSRF/неверный CSRF → 403 без записи; Content-Type/query/методы/ошибки имеют точный envelope | HTTPX |
| PQA-11 | PRA-05, PRA-08 | B и staff не получают/меняют/удаляют A; lookup до payload; 404 чужого и missing одинаков; readonly поля отклонены | HTTPX |
| PQA-12 | PRA-06 | Start атомарен с edit/unpublish; после изменения source/ключа/режима/перевода и Draft GET/submit используют прежний snapshot | PostgreSQL, HTTPX |
| PQA-13 | PRA-06 | Нет изменения snapshot/user/task; старый v1 не заменяется новой политикой; rollback при сбое создания | PostgreSQL |
| PQA-14 | PRA-07 | Правильный/неправильный допустимый ответ → 200 и correct/incorrect; identical N+language сохраняет ID/дату/одну запись; изменённый payload → 409 | Unit, HTTPX |
| PQA-15 | PRA-07 | Параллельные одинаковые и разные submit дают один финальный результат; ошибка валидации не завершает работу | PostgreSQL, HTTPX |
| PQA-16 | PRA-08 | Положительные списки всех JSON; нет эталона/его производных/ответа/snapshot в GET/POST/error/bundle; результат ровно verdict | API, frontend unit |
| PQA-17 | PRA-02, PRA-08 | Строки с Python/SQL/HTML/JS не исполняются; нет eval/exec/shell/SQL-исполнителя или сетевых вызовов проверки; безопасное отображение | Unit, HTTPX, E2E |
| PQA-18 | PRA-09 | Mastery/Read неизменны при Practice; целевой completion учитывает лучший сохранённый correct Published Task, delete/unpublish меняют веса/статус по PROGRESS_SPEC. Без kind тема остаётся в среднем | Unit, PostgreSQL |
| PQA-19 | PRA-10 | Content Admin управляет ровно 11 моделями до QIL-041, 13 после sections; запрещённые пользовательские/технические модели и прямые URL закрыты | Admin HTTP, E2E |
| PQA-20 | PRA-11 | Отдельный owner delete → 204; повтор/GET/submit → 404; B не удаляет; Read/Test прежние. Полный reset атомарно удаляет всю собственную историю/работы; late writes отвергнуты; account CASCADE сохранён | PostgreSQL, HTTPX |
| PQA-21 | PRA-12 | Полный путь статья → тест → практика, preview locked/404, RU/EN, правильный и неправильный ответ, пустой ответ, повтор/409, reload | Playwright |
| PQA-22 | PRA-12 | Desktop/mobile, Tab/Enter/focus, языковая смена без потери ввода/POST, loading/disabled/errors, raw length, пустой submit доступен | Frontend unit, Playwright |
| PQA-23 | PRA-07, PRA-12 | Потерянный start без автоповтора, submit timeout + GET + frozen repeat, 409 + GET, delete timeout + 404; нет дублей от UI | Unit, Playwright |
| PQA-24 | PRA-08, PRA-11 | Только синтетические ответы; нет request body/keys/cookies в logs/JUnit/media; очистка временной БД и собственных процессов | API/E2E, CI |

Полная приёмка Practice требует всех PRA-01–PRA-12 и соответствующих PQA-01–PQA-24. По указанию пользователя QIL-029 ограничен backend: применяются Unit/PostgreSQL/HTTPX/Admin части матрицы, Django checks, makemigrations --check, migrate --check, pip check, полный backend pytest и существующие frontend unit/type-check/build/Playwright regression. Practice UI и его E2E-части матрицы входят в QIL-030 и до реализации остаются NOT_RUN. Существующие Auth/Learning/Assessment/Progress тесты сохраняются. Все четыре GitHub Actions jobs остаются обязательными; реальный run проверяется для точного SHA. Падение/NOT_RUN/BLOCKED не называется PASS.

## 11. Следующий шаг и исключения

QIL-028 зафиксировала документацию, QIL-029 готовит backend с отдельной приёмкой по [PRACTICE_BACKEND](PRACTICE_BACKEND.md). Следующая задача после подтверждённого PASS backend — QIL-030 Practice UI по [backlog](BACKLOG.md). Контракт этого документа не меняется из-за разделения этапов; новая задача не запускается автоматически.

На будущее остаются rubric/self-check, Reviewer, исполнение кода, внешние проверки/ИИ, несколько допустимых эталонов, SQL-таблицы, несколько задач на тему, autosave, история решений в UI и автоматический retention. Новый account-delete UI также не добавляется.
