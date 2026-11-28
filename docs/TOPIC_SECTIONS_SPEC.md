# Разделы Topic и прогресс чтения — QIL-042

Статус: контракт QIL-042 утверждён 27 ноября 2026 года. QIL-043 реализует TopicSectionProgress, новые endpoints, ограничения start, reset и проверку provenance; [границы backend и миграции](SECTION_PROGRESS_BACKEND.md). Совместимый длинный reader заменён в QIL-044 оглавлением и отдельным reader каждого раздела; [реализация и проверки UI](SECTION_READER_UI.md). Сквозная приёмка QIL-045 остаётся NOT_IMPLEMENTED. Реализованная версия QIL-041 и её проверки сохранены отдельно в разделе 7; они не доказывают новое поведение.

Основания: [PRD](PRD.md), [архитектура](ARCHITECTURE.md), [прогресс и test flow](PROGRESS_SPEC.md), [QA](QA_STRATEGY.md), [backlog](BACKLOG.md). Этот контракт заменяет прежние правила единого reader, topic-level Read и неизменности mastery при добавлении раздела. Уточнение допуска к новому Practice start имеет приоритет над прежними `TopicProgress.article_read_at`/`practice_locked` для непрочитанной статьи в [PRACTICE_SPEC](PRACTICE_SPEC.md#5-доступ-snapshot-и-конкурентность): остальные Practice JSON, snapshot, submit/delete и ownership не меняются.

## 1. Состав темы

Одна Topic содержит упорядоченные разделы, общий словарь, один тест Question/Choice и максимум одну PracticeTask через TopicPractice. Тесты по разделам, вложенность, редактор HTML/Markdown, загрузка файлов и новые activity-типы не добавляются. Язык материала и словаря общий; язык теста независим; UI русский.

| Модель | Поля | Ограничения |
| --- | --- | --- |
| TopicSection | id, topic, position, status, created_at, updated_at | BigAutoField; FK Topic CASCADE; position >=1; status draft/published; UNIQUE(topic, position), DEFERRED |
| TopicSectionTranslation | id, section, language, title, article_body | FK section CASCADE; ru/en; UNIQUE(section, language); пустые строки допустимы только у Draft |
| TopicSectionProgress / assessments, QIL-043 | id, user, section, read_at | FK User CASCADE; FK TopicSection PROTECT; UNIQUE(user, section); read_at NOT NULL, UTC, серверная первая дата |

Родитель section.topic/translation.section неизменяем. Порядок position, затем id, одинаков для RU/EN; позиции могут иметь промежутки, перестановка не меняет ID. У TopicSectionProgress нет language, topic_id, процента или mastery: Topic определяется через section, владелец — из request.user. Повторная отметка не меняет read_at; reset/удаление аккаунта удаляют только соответствующие пользовательские строки.

TopicProgress сохраняется как legacy-строка с исторической первой topic-level датой, но не является источником текущего Read. Нельзя использовать её наличие вместо агрегации TopicSectionProgress. Новые признаки полного чтения, проценты и mastery вычисляются общим серверным сервисом, не сохраняются редактируемыми копиями.

TopicTranslation хранит RU/EN title темы; прежний article_body остаётся read-only legacy-копией. Источник тела — TopicSectionTranslation; параллельного редактирования двух источников нет.

## 2. Публикация и конкуренция

Published Topic требует полного title RU/EN, минимум одного Published TopicSection, полного словаря и допустимого непустого теста. Каждый Published-раздел требует непустых title/article_body RU/EN, даже у Draft-родителя. Draft-раздел может быть неполным и не входит в learner API, N, оглавление или сборку Article. Публикация Topic без Published-разделов и попытка скрыть последний раздел без одновременного перевода Topic в Draft → `400 incomplete_content` с полным rollback.

Сохраняется транзакционная операция дерева: блокировка Topic + expected_revision; устаревшая ревизия → `409 edit_conflict`, первая запись сохраняется. Успешное publishable-изменение, включая section/translation/order/status, увеличивает Topic.revision. Published редактируется только с проверкой итоговой полноты RU/EN. Массовое действие проверяет темы в стабильном порядке и откатывается целиком при любом отказе. Learner API не принимает и не выдаёт revision/expected_revision.

Добавление нового Published section ID увеличивает N и делает Topic непрочитанной, пока пользователь не прочтёт этот раздел; старые отметки и тестовые результаты остаются. Правка текста/перевода и reorder того же ID не требуют нового чтения. Unpublish раздела исключает его из N, но сохраняет отметку; повторный publish того же ID снова учитывает прежнюю дату. Это может как уменьшить, так и увеличить вычисляемые completion/mastery. Unpublish всей Topic скрывает контент и новые start/read, исключает тему из общего среднего; сам по себе не меняет набор статусов её разделов и не удаляет данные. При неизменном наборе Published-разделов агрегированный Read/mastery остаётся прежним.

Использованный раздел защищён FK PROTECT: физическое удаление section или каскадное удаление её Topic запрещено, пока есть TopicSectionProgress. Используется Draft/unpublish. Стандартный Admin-отказ не должен перечислять пользователей/ID их отметок; нового learner DELETE section нет. Content Admin по-прежнему имеет 13 контентных моделей, без permissions/list/detail/actions на TopicSectionProgress, TopicProgress, Attempt, PracticeSubmission, UserProgressState, User и Group. PROTECT не обходится массовым delete.

## 3. Точные learner-маршруты

Префикс всех путей — `/api/v1`. Новые маршруты QIL-043:

| Метод/путь | Успех | Назначение |
| --- | --- | --- |
| GET /topics/{topic_id}/reading/ | 200, TopicReading | Оглавление и состояние чтения текущего пользователя, без тел разделов |
| GET /topics/{topic_id}/sections/{section_id}/ | 200, SectionArticle | Только выбранный Published-раздел и соседние ID |
| POST /topics/{topic_id}/sections/{section_id}/read/ | 200, SectionRead | Идемпотентная отметка одного раздела; тело ровно {} |

GET принимает только один `language=ru|en`, default ru. Пустой/неизвестный/повторный query или другой параметр → `400 validation_error`; POST не принимает query и требует application/json. Session обязательна; её отсутствие → `403 authentication_required`. POST требует CSRF cookie + X-CSRFToken + X-Progress-Generation по [PROGRESS_SPEC](PROGRESS_SPEC.md#4-поколение-прогресса-и-порядок-блокировок).

Невалидный/отсутствующий ID, Draft Topic, Draft section и section другой Topic → одинаковый `404 not_found`, до проверки generation/payload. Нет fallback языка. Все DTO персональные, no-store, GET не создаёт отметки или UserProgressState. Чужого user_id/ID записи прогресса в маршруте нет; body с user_id/read_at или другими полями → 400. IDs/generation — строки положительных целых; position/counters — JSON integers; даты — ISO 8601 UTC либо null.

Общий ReadingState имеет ровно total_sections, read_sections, is_read, completion_contribution. total_sections=N; read_sections=r; is_read=(N>0 AND r=N). completion_contribution — вклад статьи в тему 0..30, округлённый ROUND_HALF_UP до двух знаков; это не процент всей темы. На корректной Published Topic N>=1. На Draft/старых данных расчёт N=0 даёт r=0, is_read=false, contribution=0; это не разрешение публикации. Неожиданная повреждённая Published Topic без разделов/перевода → безопасный `500 internal_error`, без частичного контента.

### 3.1. TopicReading, SectionArticle и SectionRead

TopicReading содержит ровно topic_id, title, language, progress_generation, reading, sections. sections — массив всех Published-разделов в порядке position/id, без pagination; элемент имеет ровно section_id, position, title, read_at. read_at=null означает непрочитанный раздел. Пустая строка состояния поколения означает generation="1", без записи из GET.

```json
{
  "data": {
    "topic_id": "12",
    "title": "Учебная тема",
    "language": "ru",
    "progress_generation": "1",
    "reading": {"total_sections": 2, "read_sections": 1, "is_read": false, "completion_contribution": 15},
    "sections": [
      {"section_id": "101", "position": 10, "title": "Раздел A", "read_at": "2026-11-27T10:00:00Z"},
      {"section_id": "102", "position": 20, "title": "Раздел B", "read_at": null}
    ]
  }
}
```

SectionArticle содержит ровно topic_id, topic_title, language, progress_generation, section, previous_section_id, next_section_id, reading. section имеет ровно section_id, position, title, article_body, read_at. Соседи определяются по Published-разделам этой Topic; на границе соответствующее поле null, не ID +/-1.

```json
{
  "data": {
    "topic_id": "12",
    "topic_title": "Учебная тема",
    "language": "en",
    "progress_generation": "1",
    "section": {"section_id": "102", "position": 20, "title": "Section B", "article_body": "Text B.", "read_at": null},
    "previous_section_id": "101",
    "next_section_id": null,
    "reading": {"total_sections": 2, "read_sections": 1, "is_read": false, "completion_contribution": 15}
  }
}
```

SectionRead содержит ровно topic_id, section_id, read_at, progress_generation, reading. Пример после чтения второго раздела:

```json
{
  "data": {
    "topic_id": "12",
    "section_id": "102",
    "read_at": "2026-11-27T10:05:00Z",
    "progress_generation": "1",
    "reading": {"total_sections": 2, "read_sections": 2, "is_read": true, "completion_contribution": 30}
  }
}
```

GET получает согласованный снимок publication/своих отметок/поколения одной PostgreSQL-командой, по существующему принципу completion GET; отдельное несогласованное чтение generation и marks недопустимо. Reset или редактура не дают смесь разных состояний в одном ответе. POST атомарен под User → UserProgressState → Topic locks: доступность, generation, пустой payload, get_or_create собственной TopicSectionProgress, затем согласованная агрегация. Два POST/вкладки не создают дубликат и не меняют первую дату; повтор с действующим поколением даёт 200. При изменении набора Published разделов reading может измениться; неизменяемость всего JSON после edit не обещается. Чтение раздела не увеличивает Topic.revision.

В ответах отсутствуют user_id, progress row ID, status Draft-разделов, revision, server keys, правильные ответы, snapshots и сохранённые ответы работ. Словарь остаётся общим для темы и не создаёт отметки чтения.

### 3.2. Legacy Article GET и список разделов

`GET /api/v1/topics/{topic_id}/` сохраняет ровно topic_id, title, language, article_body. При одном Published-разделе тело равно его тексту дословно, без trim/заголовка. При нескольких блок `title + "\n\n" + article_body` для каждого раздела соединяется ровно `"\n\n"` в порядке position/id. Запрошенный язык обязателен, HTML/Markdown не интерпретируется.

`GET /api/v1/topics/{topic_id}/sections/` сохраняет SectionsArticle с ровно topic_id, title, language, sections; элемент — section_id, position, title, article_body. Старые DTO не получают progress/reading/revision. Новый UI не использует их для длинной страницы или массового Read.

### 3.3. Legacy POST read, Progress и completion

`POST /api/v1/topics/{topic_id}/read/` сохраняет тело {}, session/CSRF/generation и прежнюю форму Progress только при ровно одном Published-разделе: делегирует той же section-read операции и возвращает 200. При N>1 всегда `403 section_read_required`, даже если все разделы уже прочитаны; ни массовой отметки, ни условного обхода нет. Draft Topic →404; повреждённая Published с N=0 →500.

Старые Progress и CompletionProgress сохраняют прежние наборы полей по [PROGRESS_SPEC](PROGRESS_SPEC.md#3-api-состояния-прогресса); section counters/даты доступны из TopicReading/SectionArticle. В старом Progress/Completion article_read_at=null, пока не выполнен текущий агрегированный Read. При полном чтении используется исторический TopicProgress.article_read_at, если есть; иначе максимум первых read_at текущих Published-разделов. Это совместимая проекция даты, не отдельный аудит момента публикации. Историческая legacy-дата не перезаписывается при добавлении раздела и хранится даже когда в DTO временно null. Наличие строки само по себе не открывает тест/практику. GET никогда не создаёт legacy-строку.

`GET /progress/` включает собственные темы с TopicSectionProgress, legacy TopicProgress или submitted Attempt, включая Draft без её текстов. При частичном чтении article_read_at=null, mastered=false, лучший исторический тест сохраняется. Completion включает только Published Topic; статья даёт дробный вклад, даже при null article_read_at.

### 3.4. Допуск к тесту/Practice и ошибки

Новый `POST /topics/{topic_id}/attempts/` требует прочтения всех текущих Published-разделов; иначе `403 section_read_required` и Attempt не создаётся. Успех остаётся 201 с прежним PendingAttempt; язык/поля не меняются. У `POST /topics/{topic_id}/practice/submissions/` сначала проверяются Published Topic/Task/TopicPractice, затем generation/структура, затем полный Read; нехватка чтения → тот же 403 section_read_required. При полном Read, но отсутствии любой собственной submitted-попытки теста → прежний `403 practice_locked`. Балл может быть любым; 80% не становится условием открытия Practice.

Practice preview сохраняет свои поля и blocked_by: article_not_read теперь означает неполный агрегированный section Read, test_not_submitted — отсутствие submitted-теста; порядок прежний. Новые коды в blocked_by не добавляются. Если не выполнены оба условия start, приоритет у section_read_required после валидного generation/payload. Историческая запись TopicProgress или чужие отметки не обходят допуск.

Гейтинг применяется только к новому start. Owned GET/submit уже начатой Attempt/PracticeSubmission разрешены по snapshot после edit/unpublish/добавления раздела, без повторной проверки Read; submit idempotency/409 и три агрегата Result/один verdict Practice не меняются. После reset удалённые ID дают 404.

| HTTP | error.code | Условие |
| --- | --- | --- |
| 400 | validation_error | Неверные JSON/поля/query/language/форма generation; без записи |
| 400 | incomplete_content | Admin publish/edit без полного RU/EN или Published-разделов; atomic rollback |
| 403 | authentication_required / csrf_failed | Нет session / неверный CSRF |
| 403 | section_read_required | Новый Test/Practice start до полного Read; любой legacy read при N>1 |
| 403 | practice_locked | Practice start при полном Read, но без своего submitted-теста |
| 404 | not_found | Отсутствующий/Draft/чужой ресурс, section другой Topic; раньше body/generation |
| 409 | progress_reset | Устаревшее поколение learner-записи |
| 409 | edit_conflict | Только контентный Admin с устаревшей revision |
| 405 / 415 / 500 | method_not_allowed / unsupported_media_type / internal_error | Прежний envelope, безопасное сообщение |

```json
{"error": {"code": "section_read_required", "message": "Use the section reader to read all published sections."}}
```

error содержит code/message и допускает fields при валидации; внутренние данные/traceback запрещены. CSRF middleware выполняется до view. Затем метод/session, доступность/ownership, форма и значение generation, структура payload, prerequisites. Чужая/удалённая работа не раскрывается при невалидном payload или stale generation. Повтор/ошибки reset, incomplete_answers и attempt_already_submitted остаются по PROGRESS_SPEC.

## 4. Reader и Read

UI `/topics/{topic_id}?language=ru|en` становится оглавлением с отметками разделов и ссылками на общий словарь/тест/практику. Тела всех разделов не собираются в одну страницу. Reader `/topics/{topic_id}/sections/{section_id}?language=ru|en` показывает только текущий раздел. Переходы previous/next и оглавление сохраняют язык; чтение допускается в любом порядке. Back/Forward/reload восстанавливают URL, не создают отметок сами по себе.

Старый внутренний `#section-ID` на странице темы после проверки ID/принадлежности Published-разделу заменяется через history.replace на новый reader. Неверный якорь не превращается во внешний redirect: остаётся оглавление с безопасным сообщением. Разрешённый якорь heading на странице раздела — `#section-ID`; генерация якорей из произвольного текста/HTML не добавляется. next/returnTo отсутствуют.

End-marker только после текущего полностью загруженного раздела. Для autoRead требуются активный visible document, подключённый актуальный marker с ненулевой геометрией, CSS-видимость и полное пересечение viewport. Hidden, 0x0, stale marker, loading/ошибка/частичная загрузка не дают POST; возврат вкладки заново измеряет текущий DOM. Короткий полностью видимый раздел может прочитаться без scroll. Это фиксация достижения конца, не доказательство чтения каждого абзаца. Оглавление и словарь POST не создают.

Один in-flight POST на section в пределах текущего клиента; registry по session user/generation/section ID живёт выше reader. RU/EN, ошибка перевода, переключение раздела A→B→A и повторные intersection/visibility события не сбрасывают pending уже отправленной записи. Ответ A применяется к A, не перезаписывает B. Подтверждённую дату не затирает stale GET. После ошибки/timeout сначала явная GET-проверка, затем допустим явный повтор; автоповтора POST нет. Разные вкладки/reload могут повторить HTTP, серверная UNIQUE/idempotency сохраняет одну строку/первую дату.

После reset/session loss private state очищается; старый GET/POST не восстанавливает отметку. Клиент не подставляет свежий generation для повтора старого POST. Старый видимый marker не считается новым действием: autoRead разрешён только после явного открытия/возобновления материала.

Heading фокусируется один раз при смене topic/section path; смена языка сохраняет focus LanguageSelector. Оглавление имеет aria-current=page, accessible labels, mobile toggle и previous/next по клавиатуре. Сохраняются AppShell, focus-visible и 1280×900/390×844 без overflow. Проценты/Read/start eligibility не вычисляются браузером вместо backend; для POST отказ остаётся окончательной проверкой.

## 5. Неразрушительная миграция

Историческая QIL-041/learning 0003 уже создала по одному section из каждой существовавшей статьи, скопировав title/body RU/EN без изменения символов; Topic IDs/Read/snapshots тогда не менялись. Старая миграция не переписывается.

Additive/data migration assessments.0005_topic_section_progress добавляет TopicSectionProgress с зависимостью от существующих sections и generation:

1. Старый TopicProgress.read переносится **только на существующий раздел, созданный из прежней статьи миграцией learning 0003**, с прежним article_read_at. Другие, добавленные позднее разделы остаются непрочитанными. Например, при одной legacy-отметке и двух текущих Published-разделах: r=1, вклад статьи=15, Topic Read=false.
2. Мигрированный раздел должен быть достоверно сопоставлен topic_id→section_id предварительной проверкой происхождения. Position=10, минимальный ID, одинаковый текст или единственный оставшийся раздел сами по себе не доказательство. Learning 0003 не хранит явный origin marker: QIL-043 обязана подготовить проверяемое сопоставление по истории миграции/данным перехода; при неоднозначности перенос останавливается с полным rollback и конкретным отчётом, без угадывания.
3. У подтверждённо отсутствующего/удалённого исходного раздела и у темы, созданной после learning 0003 без такого раздела, новая отметка не выдумывается. Legacy TopicProgress/дата остаются сохранены. Если исходный раздел существует, но теперь Draft или его родитель Draft, историческая отметка переносится на него и не участвует в N до его публикации.
4. Нет копирования на все текущие разделы, присвоения Read по успешному тесту, создания контента или запуска loader/seed. Topic IDs, legacy первые даты, UserProgressState/generation/reset receipt, Attempt/PracticeSubmission IDs/результаты/ответы/snapshots не меняются.
5. Переход выполняется при остановленных learner-записях и редактировании контента: старый backend reset ещё не удаляет новую таблицу. После backfill включается backend, умеющий общий section-level Read/reset; старые end-markers не получают новый generation и не восстанавливают запись.
6. Сверяются counts/UNIQUE/FK, точное равенство перенесённых дат, отсутствие отметок у поздних разделов и сохранность прежних записей/снимков. Ошибка откатывает всю новую data migration. Возврат к старой версии после новых частичных отметок не считается без потерь и требует отдельного плана.

QIL-043 проверяет миграцию только на временных PostgreSQL. Dev-БД не мигрируется автоматически: read-only preflight `check_section_provenance`, проверенный оператором экспорт перехода и его SHA256 описаны в [инструкции](SECTION_PROGRESS_BACKEND.md#происхождение-старого-read). Checksum фиксирует входной файл, но не заменяет доказательство происхождения; неподтверждённое сопоставление блокирует перенос. Learning 0003 не изменена.

## 6. Приёмка и зависимости

Матрица SRP-01–SRP-12 в [QA-стратегии](QA_STRATEGY.md#416-section-level-reading-progress--qil-042) — проверки backend QIL-043 и UI QIL-044; сквозная приёмка QIL-045 остаётся отдельной задачей. Старые SEC-05–SEC-07 описывают историческую QIL-041; они не разрешают topic-level обход после перехода.

DAG нового инкремента: QIL-041/QIL-034 → QIL-042; QIL-042 + QIL-041/QIL-034/QIL-029 → QIL-043 (backend, migration, HTTPX, typed protocol при необходимости); QIL-043 + QIL-035/QIL-041 → QIL-044 (отдельный reader/клиент/UI); QIL-043/QIL-044/QIL-031/QIL-038 → QIL-045 (сквозная приёмка). QIL-037 сохраняет прежний объём приёмки QIL-041, а не заменяет будущие SRP-тесты. Задачи не запускаются автоматически.

Обязательны PostgreSQL/HTTPX/TCP, frontend unit/strict decoders, реальные E2E без mocks критического пути, Chromium full + Firefox/WebKit critical на desktop/mobile и cleanup. Проверяются миграция только исходного раздела, частичная формула/N=0/M=0, dynamic Read/mastery, revision/rollback, PROTECT/Admin privacy, полный reset/late writes, single-flight и запрет новых start. Result/Practice snapshot, scoring, Answer/Finish и правила activity не меняются. Новые темы, зависимости, deployment и production hardening вне объёма.

## 7. Реализация и проверки QIL-041

Исторический отчёт реализованного единого reader. Последующие требования QIL-042 реализуются в QIL-043/QIL-044; старые PASS не являются их приёмкой.

Модели и миграция находятся в learning; sections GET и legacy Article используют один согласованный снимок под блокировкой Topic. Создание, изменение и удаление разделов/переводов требуют expected_revision; пакетные операции используют edit_topics с одной ревизией на итоговое дерево. TopicTranslation.article_body сохраняется read-only и не участвует в выдаче. Публикация раздела проверяет RU/EN даже у Draft-темы; последний Published-раздел нельзя скрыть у Published Topic.

Content Admin управляет 13 контентными моделями. У новых разделов есть отдельное подтверждаемое publish/unpublish; пустые Draft разрешены. User, Group и learner/technical data остаются недоступными. Новые зависимости и продуктовые API вне sections не добавлены.

Reader отображает все Published-разделы как plain text; оглавление и переходы используют только проверенные внутренние #section-ID. Язык и якорь сохраняются в URL; переход по якорю не перезагружает контент/Read. Фокус переходит на h2 выбранного раздела, смена языка оставляет его на LanguageSelector. End-marker один, после последнего раздела. Жизненный цикл markRead и visibility-код QIL-027 сохранены.

Локальные проверки 26 ноября 2026: PASS. Полный backend — 488 тестов и 46 подтестов; после последней адресной правки Admin выполнены все 17 sections HTTPX-тестов. Frontend — 278 unit, type-check и production build. Django checks, makemigrations --check, migrate --check и pip check прошли на временной PostgreSQL. Первые ошибки migration-тестов устранены восстановлением полного графа перед историческим downgrade; приоритет Draft 404 перед query validation сохранён.

В каждом движке первый полный suite из 149 сценариев дал 148 PASS и timeout одного старого ожидания legacy Article GET. Reader обращается к sections GET; исправлено только ожидание маршрута с дополнительным точным сравнением legacy 404. После этого в Chromium, Firefox и WebKit прошли по 10 релевантных сценариев: исправленный 404, настоящий Admin → learner, все новые разделы, RU/EN, anchors/reload/history/keyboard, desktop/mobile, pending Read и unpublish/snapshot. Первоначальные прогоны не объявляются полностью зелёными; новый CI проверяется после публикации. Все 149 browser instances, backend/frontend процессы и временные БД каждого полного прогона, затем по 10 instances целевого прогона очищены.

Локальная dev-миграция применена явно штатным migrate после read-only preflight: было две Published Topic и четыре TopicTranslation, добавлено ровно два раздела и четыре перевода. Хеши строк 21 прежней таблицы совпали до/после, включая старые статьи, пользователей, sessions, Read, Attempt/PracticeSubmission и snapshots. Topic IDs/status/revision/даты сохранены; новые Topic не создавались. Только согласованные Content Admin permissions расширены с 44 до 52; остальные роли не изменены. Повторный migrate --check не обнаружил ожидающих миграций. .env и семь старых пользовательских helpers сохранены.

Созданы articles.py, learning migration 0003, Admin confirmation template, PostgreSQL/domain и migration tests, HTTPX sections tests, frontend sections unit и real Playwright sections tests. Изменены learning models/Admin/serializers/views/permissions, URL, typed API/decoder/reader/routing/styles, существующий явный demo loader, совместимые fixtures/tests и связанные документы. JSON демо-контента, зависимости, CI/sanitizer, completion/mastery/reset, Practice и Answer/Finish не менялись. Массовое delete_selected скрыто у TopicSection: удаление требует отдельную форму с ревизией; дубликаты позиции/языка дают ошибку поля до записи, а DB constraints остаются обязательными.

Markdown/внутренние ссылки, Python AST, diff/secret scan и защищённые файлы проверены. YAML workflow побайтово совпадает с исходным проверенным файлом; новые YAML/dependencies не добавлялись. Статус CI нового SHA до публикации — NOT_RUN; окончательный run и все шесть executions фиксируются в отчёте публикации. Ручная пользовательская приёмка новой версии остаётся отдельным шагом.
