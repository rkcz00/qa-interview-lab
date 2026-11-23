# Прогресс, reset и подтверждение ответов — QIL-033

Статус: правила утверждены пользователем 23 ноября 2026 года; этот документ фиксирует целевой контракт. Реализация QIL-034/QIL-035 — **NOT_IMPLEMENTED**. Успешные старые тесты и документационный CI не доказывают выполнение новых требований.

Источники: [PRD](PRD.md), [архитектура](ARCHITECTURE.md), [QA-стратегия](QA_STRATEGY.md), [backlog](BACKLOG.md), [Practice](PRACTICE_SPEC.md), [разделы Topic](TOPIC_SECTIONS_SPEC.md).

## 1. Термины и статусы

В Topic сейчас один тест: весь упорядоченный набор Question. Question — вопрос этого теста, Choice — вариант ответа; PracticeTask является отдельной activity и не входит в Assessment Attempt. Несколько самостоятельных тестов, тест на каждый раздел и несколько PracticeTask не добавляются.

| Статус activity | Тест | Published PracticeTask |
| --- | --- | --- |
| `unattempted` | Нет собственных submitted Attempt | Нет собственных submitted PracticeSubmission этой Task |
| `failed` | Завершённые Attempt есть, лучший точный результат ниже 80% | Завершённые работы есть, ни одна сохранённая работа не имеет verdict=correct |
| `passed` | Есть собственный submitted Attempt с `100 * correct_count >= 80 * total_count`, total_count > 0 | Есть собственная сохранённая submitted-работа с verdict=correct |

UI-подписи: «Не пройдено», «Неуспешно», «Успешно». Открытая in_progress-работа сама не меняет статус, не отменяет прежний passed и не создаёт счётчик незавершённых попыток. Неуспешная submitted-попытка завершена, но не успешна. Она по-прежнему удовлетворяет условию допуска к Practice вместе с Read; требование 80% для открытия Practice не вводится.

Для статьи используются article_read_at=null («Не прочитано») и первая сохранённая дата («Прочитано»), общие для RU/EN. Отсутствующая, Draft или не подключённая через TopicPractice практика представлена `practice=null`, без раскрытия её ID/содержимого и без статуса failed. Loading/ошибка сети являются состояниями интерфейса, а не unattempted или нулём.

Лучший тест выбирается из собственных сохранённых submitted Attempt по точной дроби correct_count/total_count; при равенстве берётся Attempt с меньшим ID, как в текущем progress service. Округлённое percentage не участвует в выборе или пороге. Для Practice достаточно любого сохранённого correct этой Task. Результаты старых snapshot после редактирования по-прежнему подходят. Более поздний failed не отменяет passed. Удаление единственной correct-работы Practice может понизить её статус и completion_progress; отдельная копия достижения не хранится.

## 2. Формулы и изменяемый набор activity

Для каждой Published Topic:

- R=1 при article_read_at, иначе R=0.
- M — количество опубликованных activity-компонентов. Сейчас тест даёт 1, если Topic опубликована и имеет допустимый непустой набор вопросов; тест наследует публикацию Topic, отдельного test.status нет. Подключённая Published PracticeTask даёт ещё 1. Количество Question, Choice, Attempt и PracticeSubmission не увеличивает M.
- S — количество этих activity со статусом passed, 0 <= S <= M.
- При M>0: `completion_progress = 30 * R + 70 * S / M`.
- При M=0: `completion_progress = 30 * R`. Нет деления на ноль и автоматического начисления оставшихся 70%. При текущих критериях публикации Topic без вопросов недопустима: M=0 — защитная ветка расчёта, а не разрешение публиковать такую тему.
- Без Published PracticeTask веса равны 30/70, с ней — 30/35/35. failed и unattempted дают одинаковый нулевой вклад, но разные подписи.

`overall_completion_progress = SUM(completion_progress по Published Topic) / число Published Topic`. При нуле Published Topic результат 0. У всех тем одинаковый вес; длина статьи и число вопросов не влияют на среднее. Включены все Published-темы, в том числе демо; фильтр программы не вводится. Среднее считается из неокруглённых значений, а не из отображаемых процентов. Для API и UI итог каждого процента округляется до двух знаков по ROUND_HALF_UP и передаётся JSON number, не строкой с `%`.

Mastery остаётся отдельно: `article_read_at != null AND EXISTS собственный submitted Attempt с 100 * correct_count >= 80 * total_count при total_count > 0`. Practice и completion_progress в условие не входят. Mastery не выводится из completion_progress. До явного reset плохая новая попытка, редактирование или unpublish не отменяют выполненное условие.

| Read | Тест | Practice | M | completion_progress | mastered |
| --- | --- | --- | --- | --- | --- |
| нет | passed | отсутствует | 1 | 70 | false |
| да | failed | отсутствует | 1 | 30 | false |
| да | passed | отсутствует | 1 | 100 | true |
| да | passed | unattempted | 2 | 65 | true |
| да | failed | passed | 2 | 65 | false |
| да | passed | passed | 2 | 100 | true |

Например, Published-темы с 65 и 100 дают общий процент 82.5. Draft Topic исключена из среднего, но её данные не удаляются. Публикация новой темы или PracticeTask и снятие публикации activity могут изменить знаменатель/веса и процент без изменения сохранённых результатов. Успех скрытой Practice не учитывается в текущем M/S, но собственная работа остаётся доступной по snapshot до её удаления/reset.

Проценты и статусы вычисляет backend из исходных записей; редактируемые копии баллов, mastered и completion_progress в TopicProgress не добавляются.

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

topics содержит все Published Topic, включая не начатые, в порядке числового topic_id. best_result имеет прежнюю форму Result из трёх агрегатов; при unattempted он null. Поля test/practice не являются расширением Result/PracticeResult. В data ровно progress_generation, overall_completion_progress, topics; в элементе topics ровно показанные шесть полей. Один ответ использует согласованный снимок набора публикации и собственных результатов; среднее соответствует тем же topics. Ни ключи, ни snapshots, ни ответы, ни внутренние ревизии Topic в него не входят.

При пустом каталоге: `data={progress_generation: "1", overall_completion_progress: 0, topics: []}`. Отсутствующая техническая строка состояния трактуется как generation=1, без записи из GET. generation — положительное десятичное целое строкой, без пробелов/знака/ведущих нулей, до 9223372036854775807. Это не секрет и не авторизация.

Старый `GET /api/v1/progress/` сохраняет массив Progress с topic_id/article_read_at/best_result/mastered и собственными сохранёнными данными, включая Draft. Новые поля туда не добавляются: существующие runtime decoders строгие. Новый UI использует completion-progress для процентов и статусов; история в UI не возвращается. Старый процент mastered Published / все Published остаётся историческим поведением QIL-027 и не обозначается новым общим процентом.

## 4. Поколение прогресса и порядок блокировок

После реализации QIL-034 все learner POST, записывающие прогресс, требуют `X-Progress-Generation` наряду с обычными session/CSRF. Это обязательное изменение mutating-контрактов, без legacy-обхода:

| POST | Payload остаётся |
| --- | --- |
| `/api/v1/topics/{topic_id}/read/` | `{}` |
| `/api/v1/topics/{topic_id}/attempts/` | language |
| `/api/v1/attempts/{attempt_id}/submit/` | language, answers |
| `/api/v1/topics/{topic_id}/practice/submissions/` | language |
| `/api/v1/practice-submissions/{submission_id}/submit/` | language, answer_text |
| `/api/v1/practice-submissions/{submission_id}/delete/` | `{}` |
| `/api/v1/progress/reset/` | confirmation, request_id |

Auth POST, GET и контентные Admin-операции не требуют этого заголовка. Header берётся из completion-progress текущей сессии и хранится клиентом в памяти. Он не заменяет CSRF, session или ownership.

Целевая техническая модель UserProgressState: OneToOne User с CASCADE; generation (положительный BigInteger, default 1), last_reset_request_id (UUID, nullable), last_reset_from_generation (nullable). Последние два поля либо оба null, либо описывают предыдущий generation=current-1. Это минимальная квитанция последнего reset, без тем, ответов и snapshots; она не удаляется вместе с учебной историей и не выдаётся в Admin/learner DTO.

Любая перечисленная запись и reset выполняются в atomic-транзакции с общим mutex: сначала select_for_update текущей строки User, затем получение/создание UserProgressState, далее Topic и owned Attempt/PracticeSubmission в согласованном порядке. Нельзя брать User-lock после Topic/работы. Общий User-lock защищает и первоначальное создание состояния, и конкурирующий start/read/submit/delete/reset. Контентные операции используют прежнюю Topic.revision и не захватывают learner User-lock.

После штатного CSRF, метода/session проверяются доступность ресурса и ownership, затем форма generation/payload и бизнес-правила. Для чужого, отсутствующего или уже удалённого ID сначала 404 — до сравнения generation и разбора тела. Неверная форма header даёт 400 validation_error; несовпадение с текущим generation — 409 progress_reset без записи. Исключение — точно распознанный повтор последнего reset из раздела 5.

Если запись первой получила mutex, она завершается до reset и её данные удаляются reset. Если первым завершился reset, старый start/read получает 409, а обращение к удалённой работе — 404. Никакого восстановления удалённых объектов через save/upsert. Одна atomic-транзакция без общей сериализации и проверки generation этому контракту не соответствует.

GET-ответ прошлого поколения клиент игнорирует. После 409 progress_reset он очищает пользовательские draft/confirmed/cache, останавливает автоматическое чтение, проверяет состояние GET и сообщает о сбросе. Автоматического обновления generation с повтором прежнего POST нет. Вкладки оповещаются сигналом reset без пользовательских данных; даже вкладка, пропустившая сигнал, защищена сервером. Новое автопрочтение разрешается только после нового явного открытия/возобновления материала, а не от старого видимого end-marker.

## 5. Reset API и история

`POST /api/v1/progress/reset/`, Content-Type application/json, без query, с корректным CSRF и X-Progress-Generation:

```json
{"confirmation": "reset_all_progress", "request_id": "00000000-0000-4000-8000-000000000033"}
```

request_id — новый канонический UUID v4 для одного подтверждённого действия; не credential. При транспортном повторе сохраняются тот же UUID, тело и исходный header. Другие поля, user_id, отсутствующее/неверное confirmation или невалидный UUID дают 400 validation_error.

В одной транзакции под общим mutex удаляются только TopicProgress, Attempt и PracticeSubmission request.user, включая in_progress/submitted и данные Draft Topic. Удаляются их ответы, snapshots и история. Контент, аккаунт, session, группы и чужие записи не меняются. generation увеличивается на 1, квитанция последнего reset обновляется в той же транзакции. Ошибка/overflow откатывает всё; успех до commit не показывается.

Успех — 200:

```json
{"data": {"progress_generation": "2"}}
```

Повтор последнего request_id с исходным generation возвращает тот же 200 и generation, не удаляя повторно даже записи, созданные после reset. Тот же последний UUID с другим синтаксически допустимым generation — 409 reset_request_conflict; неверная форма header остаётся 400. После следующего отдельного reset прежняя квитанция заменена: более старый запрос с прежним header даёт 409 progress_reset, без удаления. Это ограниченная идемпотентность последней операции, а не бессрочный журнал reset.

После успеха клиент очищает local drafts/подтверждения, уведомляет вкладки, переходит на `/progress` и получает актуальный GET. При отсутствии новых действий все статусы unattempted, Read=null, mastered=false, проценты 0. Старые GET/submit/delete ID дают 404; прежние обещания идемпотентности удалённых работ прекращаются. Новое чтение может создать новую первую дату. Неуспешный reset не показывает выдуманный ноль.

UI содержит отдельное предупреждение «Будут удалены отметки чтения, все попытки и работы, включая историю. Восстановление не предусмотрено» и явное подтверждение; кнопка заблокирована на время запроса. Network/timeout не повторяет POST автоматически: сначала GET, при необходимости явный повтор с тем же request_id и исходным generation. Нельзя превращать транспортный повтор в новый reset с новым UUID/свежим header.

| HTTP | error.code | Условие |
| --- | --- | --- |
| 400 | validation_error | Неверные header, JSON, поля, confirmation, UUID или query |
| 403 | authentication_required / csrf_failed | Нет session / неверный CSRF; изменений нет |
| 404 | not_found | Чужая, отсутствующая или удалённая работа; до проверки generation |
| 409 | progress_reset | Устаревшее поколение; очистить stale state, без автоповтора |
| 409 | reset_request_conflict | Повтор UUID последнего reset с другим generation |
| 405 | method_not_allowed | Не предусмотренный метод; GET reset не удаляет данные |
| 415 | unsupported_media_type | POST не application/json |
| 500 | internal_error | Неожиданная ошибка/overflow; безопасное сообщение и полный rollback |

Reset — явное утверждённое исключение из сохранности истории после редактирования/unpublish. Отдельное удаление PracticeSubmission остаётся прежним owner-only действием и не удаляет Read/Attempt.

## 6. Тест: локальное подтверждение и финальная отправка

На каждом вопросе панель: «Предыдущий — Ответить — Следующий». Answer не делает HTTP, не оценивает правильность и не выдаёт вердикт; он подтверждает текущий выбор по question_id/choice IDs в памяти экрана. Навигация отдельная, без автоматического подтверждения/перехода. Подтверждение объявляется доступным status-сообщением. Single-choice требует ровно один вариант, multiple-choice — хотя бы один; backend не требует два выбранных варианта даже при двух правильных.

На последнем вопросе дополнительно появляется «Завершить тест»; она disabled, пока каждый вопрос snapshot не имеет подтверждённого непустого выбора. «Ответить» на последнем вопросе не отправляет Attempt. Изменение/очистка выбора отменяет только подтверждение этого вопроса. Повторное Answer без изменений не делает записей. Back/Forward и RU/EN сохраняют вопрос, выбор и подтверждения по ID; reload теряет неотправленное состояние, как сейчас, с понятным предупреждением. Никаких correct keys, локального scoring, localStorage/autosave или отдельного QuestionAttempt нет.

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

submitted проверяется по прежней структурной схеме и нормализации до нового правила полноты: идентичный нормализованный payload → 200, изменённый допустимый → 409 attempt_already_submitted. Это сохраняет повторы старых submitted с пропусками. Пропуски в историческом scoring по-прежнему ноль, но новая первичная неполная отправка не создаёт submitted. Полнота проверяется сервером; флаг confirmed от клиента не принимается. Изменение требования и соответствующих прежних тестов выполняется в QIL-035, без пересчёта исторических результатов.

### 6.2. Login

На `/login` отсутствует ссылка/кнопка «На главную». Остаются название, форма и переход к регистрации. Успешный login/действующая session ведут на `/`; `next`/`returnTo` не добавляются. Общая навигация learner-экранов сохраняется; удаление ссылки на `/register` отдельно не требуется.

## 7. Приёмка и границы

Матрица PGR-01–PGR-10 и TFL-01–TFL-06 — в [QA-стратегии](QA_STRATEGY.md). Обязательны независимые оракулы формулы/M=0/пустого каталога, лучшие результаты и точный порог, отсутствие ответов в DTO, ownership/CSRF, rollback/две вкладки/late POST, повторы reset без удаления новой работы, 404 старых ID, локальные подтверждения/все ответы/Finish, историческая идемпотентность и regression. Реализация проверяется через PostgreSQL/HTTPX/TCP/Playwright; документационный этап не запускает destructive reset.

QIL-034 реализует progress/generation/reset с API-клиентом и UI целиком; reset нельзя включать до защиты всех семи POST. QIL-035 реализует strict submit/test flow/login. Их API/UI-функции сейчас отсутствуют. Публичный deploy, новые activity-типы, расширение Result и код пользователя вне объёма.
