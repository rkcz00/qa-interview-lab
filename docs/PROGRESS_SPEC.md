# Прогресс, reset и подтверждение ответов — QIL-033/QIL-042

Статус: backend completion/reset QIL-034, UI QIL-035 и Answer/Finish QIL-038/QIL-040 реализованы; [backend](COMPLETION_BACKEND.md), [UI](COMPLETION_UI.md), [test flow](ANSWER_FINISH.md). Reset остаётся 200 + GET; Practice входит в completion, но не mastery.

QIL-042, 27 ноября 2026: утверждён отдельный reader и section-level progress по [TOPIC_SECTIONS_SPEC](TOPIC_SECTIONS_SPEC.md). QIL-043 реализует новую модель, дробный вклад статьи, динамические Read/mastery и Read-гейт нового Test/Practice start; [переход и provenance](SECTION_PROGRESS_BACKEND.md). Текущий длинный reader минимально адаптирован по отдельному разрешению; отдельные страницы остаются QIL-044. Прежние JSON Progress/CompletionProgress/Result, activity-правила и Answer/Finish не расширяются.

Источники: [PRD](PRD.md), [архитектура](ARCHITECTURE.md), [QA-стратегия](QA_STRATEGY.md), [backlog](BACKLOG.md), [Practice](PRACTICE_SPEC.md), [разделы Topic](TOPIC_SECTIONS_SPEC.md).

## 1. Термины и статусы

В Topic один тест: весь упорядоченный набор Question. Question — вопрос, Choice — вариант; PracticeTask — отдельная activity, не часть Assessment Attempt. Несколько тестов/практик и тест на каждый раздел не добавляются.

| Статус activity | Тест | Published PracticeTask |
| --- | --- | --- |
| `unattempted` | Нет собственных submitted Attempt | Нет собственных submitted PracticeSubmission этой Task |
| `failed` | Submitted есть, лучший точный результат ниже 80% | Submitted есть, ни одна сохранённая работа не correct |
| `passed` | Есть submitted Attempt с 100*correct_count>=80*total_count, total_count>0 | Есть сохранённая submitted-работа с verdict=correct |

UI: «Не пройдено», «Неуспешно», «Успешно». In_progress не меняет статус и не создаёт счётчик незавершённых работ. Любой submitted-балл вместе с полным section Read открывает новый Practice start; 80% требуется для mastery, не для Practice.

TopicSectionProgress(user, section, read_at) имеет UNIQUE(user, section), FK section PROTECT и общую RU/EN первую дату. Текущий Topic Read вычисляется по всем Published-разделам: N>0 и r=N. Наличие legacy TopicProgress не заменяет агрегацию. В прежних DTO article_read_at=null при неполном Read; при полном — сохранённая историческая дата TopicProgress, иначе максимум первых read_at текущих Published-разделов. Это совместимая проекция, не аудит момента публикации; GET не создаёт legacy-строку и не меняет дату. Подробные section read_at/counters выдаёт отдельный reading API.

Отсутствующая/Draft/не подключённая Practice представлена practice=null, без раскрытия её ID/содержимого. Loading/ошибка сети — состояния UI, а не unattempted или ноль.

Лучший тест выбирается из собственных submitted Attempt по точной дроби correct_count/total_count; при равенстве меньший ID. Отображаемый процент не влияет на выбор/порог. Для Practice достаточно любого сохранённого correct этой Task. Поздний failed не отменяет passed; удаление последнего correct Practice может уменьшить completion, не mastery. Старые snapshot-результаты сохраняются после редактирования.

## 2. Формулы и изменяемый набор activity

Для каждой Published Topic:

- N — число текущих Published TopicSection; r — число из них с собственной отметкой, 0<=r<=N. Draft-разделы скрыты и не входят в N.
- `article_progress = 30 * r / N` при N>0; при N=0 — 0. Это вклад статьи 0..30 в тему; каждый раздел даёт 30/N.
- `Read = (N > 0 AND r = N)`. Язык, порядок, длина и повтор просмотра не меняют вес.
- M — число опубликованных activity: один тест при допустимом непустом наборе Question и максимум одна Published PracticeTask. Question/Choice/Attempt/Submission не увеличивают M.
- S — число этих activity со статусом passed, 0<=S<=M.
- При M>0: `completion_progress = article_progress + 70 * S / M`.
- При M=0: `completion_progress = article_progress`, без деления на ноль и начисления оставшихся 70%. Это защита, а не разрешение публикации Topic без допустимого теста.
- N=0: r=0, article_progress=0, Read=false, mastered=false. Это защита Draft/старых данных. Published Topic без Published-разделов запрещён: Admin 400 incomplete_content с rollback; обнаруженная повреждённая Published при learner-выдаче → безопасный 500 internal_error.
- Полная статья даёт 30%; без Practice тест — 70%; с Published Practice тест/Practice — по 35%. failed и unattempted дают 0 activity, но различаются в UI.

Общий процент — среднее неокруглённых completion_progress всех Published Topic, включая демо и не начатые; пустой каталог — 0. У тем одинаковый вес. Каждый выводимый процент — JSON number с ROUND_HALF_UP до двух знаков; среднее не вычисляется из уже округлённых значений.

Mastery вычисляется отдельно: `N>0 AND r=N AND EXISTS собственный submitted Attempt: 100*correct_count>=80*total_count, total_count>0`. Practice/completion_progress не входят в условие. Новый Published section ID увеличивает N и может снять Read/mastery до его чтения, сохраняя прежние отметки/результаты. Правка/reorder того же ID не требуют повторного чтения. Unpublish section исключает его из N; republish учитывает прежнюю дату. Root Topic unpublish исключает тему из среднего и запрещает новый контентный доступ/start/read, но не удаляет данные; при прежнем наборе Published-разделов Read/mastery не меняются. Это утверждённое QIL-042 изменение прежнего правила неизменности mastery после добавления раздела.

Таблица крайних случаев: «нет» означает r=0, «да» — r=N>0. Частичное чтение использует дробную формулу.

| Read | Тест | Practice | M | completion_progress | mastered |
| --- | --- | --- | --- | --- | --- |
| нет | passed | отсутствует | 1 | 70 | false |
| да | failed | отсутствует | 1 | 30 | false |
| да | passed | отсутствует | 1 | 100 | true |
| да | passed | unattempted | 2 | 65 | true |
| да | failed | passed | 2 | 65 | false |
| да | passed | passed | 2 | 100 | true |

Частичные независимые оракулы: N=2/r=1 + passed test без Practice →15+70=85, mastered=false; N=3/r=1 + failed test →10; N=2/r=2 + passed test и unattempted Practice →65, mastered=true. Исторический passed тест продолжает учитываться после добавления непрочитанного раздела, хотя новый start до полного Read запрещён.

N=7/r=1 и failed activity: вклад статьи отображается 4.29; среднее с другой темой 0 равно 2.14, не 2.15. Полные темы с 65 и 100 дают среднее 82.5. Draft исключается из среднего, но его данные сохраняются. Публикация Topic/section/Practice может менять веса/знаменатель без пересчёта snapshots. Сервер не сохраняет редактируемых копий процентов/статусов.

## 3. API состояния прогресса

Все новые ответы имеют точный envelope `{data: ...}` либо `{error: {code, message, fields?}}`. Дополнительные поля запросов запрещены. Доступ только через Django session, владелец всегда request.user; чужой user_id не принимается. Ответы не кешируются (`Cache-Control: no-store`). GET не меняет состояние.

`GET /api/v1/completion-progress/` без query/body возвращает 200:

```json
{
  "data": {
    "progress_generation": "1",
    "overall_completion_progress": 82.5,
    "topics": [
      {
        "topic_id": "12",
        "article_read_at": "2026-11-23T10:00:00Z",
        "test": {"status": "passed", "best_result": {"correct_count": 4, "total_count": 5, "percentage": 80}},
        "practice": {"task_id": "31", "status": "unattempted"},
        "completion_progress": 65,
        "mastered": true
      },
      {
        "topic_id": "13",
        "article_read_at": "2026-11-23T10:01:00Z",
        "test": {"status": "passed", "best_result": {"correct_count": 5, "total_count": 5, "percentage": 100}},
        "practice": null,
        "completion_progress": 100,
        "mastered": true
      }
    ]
  }
}
```

topics содержит все Published Topic, включая не начатые, в порядке числового topic_id. best_result имеет прежнюю форму Result из трёх агрегатов; при unattempted он null. Поля test/practice не являются расширением Result/PracticeResult. В data ровно progress_generation, overall_completion_progress, topics; в элементе topics ровно показанные шесть полей. При QIL-043 article_read_at может быть null при ненулевом дробном вкладе статьи: Read требует всех разделов. JSON-поля не меняются; section counters/даты доступны из отдельного reading API. Один ответ использует согласованный снимок набора публикации, собственных отметок разделов и результатов; среднее соответствует тем же topics. Ни ключи, ни snapshots, ни ответы, ни внутренние ревизии Topic в него не входят.

Уточнение пользователя для backend QIL-034: отдельных counts в JSON нет. Количество компонентов определяется из одного объекта test и practice/null (0/1), без расширения схемы.

При пустом каталоге: `data={progress_generation: "1", overall_completion_progress: 0, topics: []}`. Отсутствующая техническая строка состояния трактуется как generation=1, без записи из GET. generation — положительное десятичное целое строкой, без пробелов/знака/ведущих нулей, до 9223372036854775807. Это не секрет и не авторизация.

Старый `GET /api/v1/progress/` сохраняет массив Progress с topic_id/article_read_at/best_result/mastered и собственными данными, включая Draft без текстов. Темы с частичными TopicSectionProgress тоже включаются: article_read_at=null/mastered=false до полного текущего Read, лучший тест остаётся. Новые поля туда не добавляются: существующие runtime decoders строгие. Новый UI использует completion-progress для процентов и статусов; история в UI не возвращается. Старый процент mastered Published / все Published остаётся историческим поведением QIL-027 и не обозначается новым общим процентом.

## 4. Поколение прогресса и порядок блокировок

После реализации QIL-034 все learner POST, записывающие прогресс, требуют `X-Progress-Generation` наряду с обычными session/CSRF. Это обязательное изменение mutating-контрактов, без legacy-обхода:

| POST | Payload остаётся |
| --- | --- |
| `/api/v1/topics/{topic_id}/read/` | `{}`; N=1 →200, N>1 →403 section_read_required |
| `/api/v1/topics/{topic_id}/sections/{section_id}/read/` (QIL-043, план) | `{}` |
| `/api/v1/topics/{topic_id}/attempts/` | language |
| `/api/v1/attempts/{attempt_id}/submit/` | language, answers |
| `/api/v1/topics/{topic_id}/practice/submissions/` | language |
| `/api/v1/practice-submissions/{submission_id}/submit/` | language, answer_text |
| `/api/v1/practice-submissions/{submission_id}/delete/` | `{}` |
| `/api/v1/progress/reset/` | confirmation, request_id |

Auth POST, GET и контентные Admin-операции не требуют этого заголовка. Header берётся из completion-progress или нового персонального reading/section GET текущей сессии и хранится клиентом в памяти. Он не заменяет CSRF, session или ownership.

Целевая техническая модель UserProgressState: OneToOne User с CASCADE; generation (положительный BigInteger, default 1), last_reset_request_id (UUID, nullable), last_reset_from_generation (nullable). Последние два поля либо оба null, либо описывают предыдущий generation=current-1. Это минимальная квитанция последнего reset, без тем, ответов и snapshots; она не удаляется вместе с учебной историей и не выдаётся в Admin/learner DTO.

Любая перечисленная запись и reset выполняются в atomic-транзакции с общим mutex: сначала select_for_update текущей строки User, затем получение/создание UserProgressState, далее Topic и owned Attempt/PracticeSubmission в согласованном порядке. Нельзя брать User-lock после Topic/работы. Общий User-lock защищает и первоначальное создание состояния, и конкурирующий start/read/submit/delete/reset. Контентные операции используют прежнюю Topic.revision и не захватывают learner User-lock; section Read не увеличивает revision. QIL-043 включает его в тот же mutex/reset-протокол, без массовой записи пользовательского прогресса из редактора.

После штатного CSRF, метода/session проверяются доступность ресурса и ownership, затем форма generation/payload и бизнес-правила. Для чужого, отсутствующего или уже удалённого ID сначала 404 — до сравнения generation и разбора тела. Неверная форма header даёт 400 validation_error; несовпадение с текущим generation — 409 progress_reset без записи. После валидных generation/payload новый Test/Practice start требует полного section Read; иначе 403 section_read_required без создания работы. При полном Read и отсутствии submitted-теста Practice сохраняет 403 practice_locked. Если отсутствуют оба prerequisites, приоритет у section_read_required. Legacy read при N>1 даёт тот же 403, даже если всё прочитано; массового обхода нет. Owned GET/submit уже начатых работ разрешены по snapshot без нового Read-гейта. Исключение для поколения — точно распознанный повтор последнего reset из раздела 5.

Если запись первой получила mutex, она завершается до reset и её данные удаляются reset. Если первым завершился reset, старый start/read получает 409, а обращение к удалённой работе — 404. Никакого восстановления удалённых объектов через save/upsert. Одна atomic-транзакция без общей сериализации и проверки generation этому контракту не соответствует.

GET-ответ прошлого поколения клиент игнорирует. После 409 progress_reset он очищает пользовательские draft/confirmed/cache, останавливает автоматическое чтение, проверяет состояние GET и сообщает о сбросе. Автоматического обновления generation с повтором прежнего POST нет. Вкладки оповещаются сигналом reset без пользовательских данных; даже вкладка, пропустившая сигнал, защищена сервером. Новое автопрочтение разрешается только после нового явного открытия/возобновления материала, а не от старого видимого end-marker.

## 5. Reset API и история

`POST /api/v1/progress/reset/`, Content-Type application/json, без query, с корректным CSRF и X-Progress-Generation:

```json
{"confirmation": "reset_all_progress", "request_id": "00000000-0000-4000-8000-000000000033"}
```

request_id — новый канонический UUID v4 для одного подтверждённого действия; не credential. При транспортном повторе сохраняются тот же UUID, тело и исходный header. Другие поля, user_id, отсутствующее/неверное confirmation или невалидный UUID дают 400 validation_error.

В одной транзакции под общим mutex удаляются только TopicSectionProgress (после QIL-043), legacy TopicProgress, Attempt и PracticeSubmission request.user, включая in_progress/submitted и данные Draft Topic/sections. Удаляются их ответы, snapshots и история. Контент, аккаунт, session, группы и чужие записи не меняются. generation увеличивается на 1, квитанция последнего reset обновляется в той же транзакции. Ошибка/overflow откатывает всё; успех до commit не показывается.

Успех — 200:

```json
{"data": {"progress_generation": "2"}}
```

Повтор последнего request_id с исходным generation возвращает тот же 200 и generation, не удаляя повторно даже записи, созданные после reset. Тот же последний UUID с другим синтаксически допустимым generation — 409 reset_request_conflict; неверная форма header остаётся 400. После следующего отдельного reset прежняя квитанция заменена: более старый запрос с прежним header даёт 409 progress_reset, без удаления. Это ограниченная идемпотентность последней операции, а не бессрочный журнал reset.

После успеха клиент очищает local drafts/подтверждения, уведомляет вкладки, переходит на `/progress` и получает актуальный GET. При отсутствии новых действий все статусы unattempted, Read=null, mastered=false, проценты 0. Старые work GET/submit/delete ID дают 404; section IDs относятся к контенту и остаются: section GET после reset даёт read_at=null, поздний read POST со старым generation →409 progress_reset; прежние обещания идемпотентности удалённых работ прекращаются. Новое чтение может создать новую первую дату. Неуспешный reset не показывает выдуманный ноль.

UI содержит отдельное предупреждение «Будут удалены отметки чтения, все попытки и работы, включая историю. Восстановление не предусмотрено» и явное подтверждение; кнопка заблокирована на время запроса. Network/timeout не повторяет POST автоматически: сначала GET, при необходимости явный повтор с тем же request_id и исходным generation. Нельзя превращать транспортный повтор в новый reset с новым UUID/свежим header.

| HTTP | error.code | Условие |
| --- | --- | --- |
| 400 | validation_error | Неверные header, JSON, поля, confirmation, UUID или query |
| 403 | authentication_required / csrf_failed | Нет session / неверный CSRF; изменений нет |
| 403 | section_read_required | Новый Test/Practice start до полного section Read; legacy read при N>1 (не ошибка reset) |
| 404 | not_found | Чужая, отсутствующая или удалённая работа; до проверки generation |
| 409 | progress_reset | Устаревшее поколение; очистить stale state, без автоповтора |
| 409 | reset_request_conflict | Повтор UUID последнего reset с другим generation |
| 405 | method_not_allowed | Не предусмотренный метод; GET reset не удаляет данные |
| 415 | unsupported_media_type | POST не application/json |
| 500 | internal_error | Неожиданная ошибка/overflow; безопасное сообщение и полный rollback |

Reset — явное утверждённое исключение из сохранности истории после редактирования/unpublish. Отдельное удаление PracticeSubmission остаётся прежним owner-only действием и не удаляет Read/Attempt.

## 6. Тест: локальное подтверждение и финальная отправка

На каждом вопросе панель: «Предыдущий — Ответить — Следующий». Answer не делает HTTP, не оценивает правильность и не выдаёт вердикт; он подтверждает текущий выбор по question_id/choice IDs в памяти экрана и сразу открывает следующий вопрос по порядку. Фокус переходит на заголовок нового вопроса. Без выбора показана понятная ошибка, подтверждения и перехода нет. Ручные «Предыдущий»/«Следующий» позволяют пропустить экран и вернуться, не подтверждая ответ. Подтверждение объявляется доступным status-сообщением. Single-choice требует ровно один вариант, multiple-choice — хотя бы один; backend не требует два выбранных варианта даже при двух правильных.

На последнем вопросе «Завершить тест» появляется только после подтверждения непустого выбора каждого вопроса snapshot; до этого кнопка не показывается. Это уточнение пользователя для QIL-038 заменяет прежний вариант disabled Finish. «Ответить» на последнем вопросе только подтверждает его, не меняет экран и не отправляет Attempt. Изменение/очистка выбора отменяет только подтверждение этого вопроса; неизменившийся повтор выбора не снимает подтверждение. После возврата повторное Answer подтверждает изменённый ответ и снова открывает следующий вопрос. Двойной клик не перескакивает через два вопроса, даже если следующий уже заполнен; второй клик также не превращается в Finish. Back/Forward и RU/EN сохраняют вопрос, выбор и подтверждения по ID; reload теряет неотправленное состояние, как сейчас, с понятным предупреждением. Никаких correct keys, локального scoring, localStorage/autosave или отдельного QuestionAttempt нет.

Один явный Finish фиксирует language/answers и выполняет существующий POST `/api/v1/attempts/{attempt_id}/submit/` с CSRF и generation. Кнопки/выбор/язык блокируются до подтверждённого исхода. Network/timeout использует прежний frozen payload, GET и только явный безопасный повтор; 409 attempt_already_submitted ведёт к GET результата. После reset stale draft не отправляется. Результат остаётся ровно correct_count/total_count/percentage; PracticeTask в payload/Attempt не включается.

### 6.1. incomplete_answers и совместимость истории

Для первой отправки in_progress backend сначала проверяет JSON/допустимые поля, language, типы, известность ID, дубли и допустимое число вариантов Single-choice. Затем проверяет полноту по snapshot:

- отсутствует answers при корректном остальном запросе, answers=[], отсутствует хотя бы один вопрос snapshot, отсутствует choice_ids у известного вопроса или choice_ids=[] → 400 incomplete_answers;
- неверный/отсутствующий language, answers не массив, не объект answer, отсутствующий/неизвестный question_id, неверный тип choice_ids, лишние поля, неизвестные/чужие choice IDs, дубли либо несколько вариантов Single-choice → прежний 400 validation_error;
- при смешении структурных ошибок с неполнотой приоритет у validation_error; результат не сохраняется;
- число правильных вариантов не раскрывается; полнота не означает правильность.

```json
{"error": {"code": "incomplete_answers", "message": "Answer every question before submitting the test."}}
```

submitted проверяется по прежней структурной схеме и нормализации до нового правила полноты: идентичный нормализованный payload → 200, изменённый допустимый → 409 attempt_already_submitted. Это сохраняет повторы старых submitted с пропусками. Пропуски в историческом scoring по-прежнему ноль, но новая первичная неполная отправка не создаёт submitted. Полнота проверяется сервером; флаг confirmed от клиента не принимается. QIL-038 добавляет отдельный initial-submit validator, не меняя исторический scoring и результаты. У submitted отсутствующие answers или choice_ids остаются прежним validation_error; допустимые пропуски представлены отсутствующим вопросом или пустым набором.

### 6.2. Login

Отдельное целевое правило TFL-06: на `/login` отсутствует ссылка/кнопка «На главную». Оно пока отложено и не реализуется в QIL-038. Остаются название, форма и переход к регистрации. Успешный login/действующая session ведут на `/`; `next`/`returnTo` не добавляются. Общая навигация learner-экранов сохраняется; удаление ссылки на `/register` отдельно не требуется.

## 7. Приёмка и границы

Матрица PGR-01–PGR-10 и TFL-01–TFL-06 — в [QA-стратегии](QA_STRATEGY.md). Обязательны независимые оракулы формулы/M=0/пустого каталога, лучшие результаты и точный порог, отсутствие ответов в DTO, ownership/CSRF, rollback/две вкладки/late POST, повторы reset без удаления новой работы, 404 старых ID, локальные подтверждения/все ответы/Finish, историческая идемпотентность и regression. Реализация проверяется через PostgreSQL/HTTPX/TCP/Playwright; документационный этап не запускает destructive reset.

SRP-01–SRP-12 дополняют PGR/TFL для целевого QIL-042: частичные Read, миграция только исходного раздела, 403 start/legacy, PROTECT, section reset и reader во всех движках. [Полный контракт и DAG](TOPIC_SECTIONS_SPEC.md#6-приёмка-и-зависимости). Backend QIL-043 зависит от QIL-042/QIL-041/QIL-034/QIL-029; UI QIL-044 — от QIL-043/QIL-035/QIL-041; приёмка QIL-045 — от QIL-043/QIL-044/QIL-031/QIL-038. Задачи TODO не считаются реализованными.

Изначальный backlog QIL-034 включал progress/generation/reset с API-клиентом и UI целиком. Серверный этап реализован в QIL-034; семь прежних POST защищены одновременно; новый section read добавляется в общий протокол QIL-043. QIL-035 — completion/reset UI без изменения backend. QIL-038 реализует Answer/Finish и строгий первый submit из разделов 6/6.1; TFL-06/login остаётся отложенным; базовые sections реализованы в QIL-041, отдельный reader/section progress ожидают QIL-043/QIL-044. Публичный deploy, новые activity-типы, расширение Result и код пользователя вне объёма.
