# Backend section progress — QIL-043

## Объём и совместимость

Реализованы TopicSectionProgress, динамические Read/mastery, три learner endpoint, section-гейт новых Test/Practice start и reset по [TOPIC_SECTIONS_SPEC](TOPIC_SECTIONS_SPEC.md) и [PROGRESS_SPEC](PROGRESS_SPEC.md). TopicProgress остаётся исторической первой датой, но его наличие не означает полного текущего чтения. Формы старых Article, SectionsArticle, Progress, CompletionProgress и результатов не расширяются.

Пользователь отдельно разрешил минимальную адаптацию существующего длинного reader: один marker на раздел, GET reading и POST конкретного section, безопасное объяснение нового 403. Отдельные страницы /topics/{id}/sections/{sid} и оглавление вместо длинной статьи остаются задачей QIL-044. Answer/Finish, scoring, Practice snapshot, activity-веса и reset receipt не изменены.

## Данные и операции

TopicSectionProgress содержит user, section, read_at: UNIQUE(user, section), User CASCADE, section PROTECT. Дата задаётся сервером при первом чтении и сохраняется при повторе, смене RU/EN, редактировании и reorder. Content Admin не получает прав на прогресс; защищённое удаление не перечисляет learner-объекты или владельцев.

Набор текущих Published-разделов определяет N, число собственных отметок — r. Read = N>0 и r=N; вклад статьи = 30*r/N, при N=0 — 0; activity = 70*S/M при M>0, иначе 0. Расчёты используют точные дроби до финального ROUND_HALF_UP. Новый Published section ID снимает aggregate Read/mastery до его чтения; старые отметки и результаты остаются. Unpublish/republish раздела меняют N без удаления отметок; Draft родителя скрывает learner-контент.

| Операция | Успех | Особенности |
| --- | --- | --- |
| GET /api/v1/topics/{id}/reading/?language=ru | 200 TopicReading | Только metadata/заголовки/собственные read_at; без body |
| GET /api/v1/topics/{id}/sections/{sid}/?language=en | 200 SectionArticle | Одно тело, previous/next из Published-порядка, общий Read |
| POST /api/v1/topics/{id}/sections/{sid}/read/ с {} | 200 SectionRead | Session, CSRF, X-Progress-Generation, idempotency |
| POST /api/v1/topics/{id}/read/ с {} | 200 прежний Progress при N=1 | При N>1 всегда 403 section_read_required, включая полный Read |
| POST start Test/Practice | 201 после полного Read | До него 403 section_read_required; Practice без submitted-теста после полного Read — practice_locked |

DTO и точный порядок валидации определены [спецификацией](TOPIC_SECTIONS_SPEC.md#31-topicreading-sectionarticle-и-sectionread). GET reading/detail и completion читают согласованный PostgreSQL snapshot одним SQL statement и не записывают прогресс. POST выполняются под существующей транзакцией User → Topic с generation-check. Несовпадение topic/section и Draft →404; stale generation →409 progress_reset; повреждённая Published без разделов →безопасный 500 internal_error. Поздние записи после reset не восстанавливают удалённые данные. Собственные начатые Attempt/PracticeSubmission завершаются по snapshot после edit/unpublish и изменения Read.

## Происхождение старого Read

Миграция assessments.0005_topic_section_progress не изменяет learning.0003 и прежние таблицы. Она атомарно создаёт новую таблицу и переносит дату **только на доказанный исходный раздел** learning.0003_topic_sections, если он ещё существует. У поздних разделов отметки не появляются. Отсутствующий исходный раздел или тема, созданная после learning.0003 без такого раздела, не получают выдуманного Read; исходная TopicProgress сохраняется.

Learning.0003 не записывала origin marker. Поэтому migration требует проверенный оператором экспорт истории перехода для всех тем с legacy TopicProgress. Источник — подтверждённые данные/backup непосредственно после learning.0003 или иное достоверное свидетельство того же перехода. Текущие minimum ID, position, совпадение текстов и created_at не доказывают происхождение. **SHA256 связывает запуск с вычитанным файлом, но сам по себе не доказывает его правильность.** Автоматической генерации сопоставления из сегодняшнего каталога нет.

Формат ниже иллюстративный, ID/дата синтетические; такой пример не разрешено использовать как доказательство для настоящей БД:

```json
{
  "version": 1,
  "source_migration": "learning.0003_topic_sections",
  "applied_at": "2026-01-01T12:00:00+00:00",
  "origins": [
    {"topic_id": "17", "section_id": "93"},
    {"topic_id": "18", "section_id": null}
  ]
}
```

applied_at должен точно соответствовать записи learning/0003_topic_sections в django_migrations целевой БД. topic_id покрывают ровно темы с legacy-отметками. section_id — подтверждённый исторический ID, даже если он уже удалён; null допустим только для подтверждённой темы, созданной после этой миграции без исходного раздела. Существующий ID проверяется на принадлежность Topic. Даты создания служат только отрицательной проверкой невозможного позднего origin, а не алгоритмом выбора.

Проверяются строгая схема JSON/дубликаты, SHA256, привязка к миграции, полное покрытие тем и cross-topic подмена. Неоднозначность блокирует миграцию с безопасным reason code и полным rollback; ни одного угадывания/частичного переноса. Если подтверждённой истории нет, остановиться и отдельно согласовать восстановление provenance. Файл не содержит ответов/аккаунтов/секретов и не коммитится.

## Явный локальный переход

В QIL-043 проверяются только новые временные PostgreSQL, dev-БД не мигрируется автоматически. Для существующей БД нужен отдельный план остановки learner/content writes, backup и проверенный provenance. Старый backend reset не знает новую таблицу: смешанный запуск версий во время перехода запрещён.

Read-only preflight не требует уже созданной таблицы прогресса:

```powershell
.\.venv\Scripts\python.exe -B backend/manage.py check_section_provenance --manifest C:\path\reviewed-section-provenance.json --sha256 <reviewed-sha256>
```

Без legacy TopicProgress свежая БД проходит без manifest. При наличии legacy отмеченных тем preflight без доказательства намеренно BLOCKED. Он не изменяет БД и сообщает только PASS/число тем либо безопасный reason code.

Фактический read-only preflight локальной dev-БД в QIL-043: BLOCKED, reason `verified_provenance_required`. Перенос не запускался, схема и пользовательские записи не менялись. Это ожидаемый защитный отказ без подтверждённой истории; результаты тестовой миграции не считаются доказательством происхождения dev-данных.

После проверки источника и остановки writes передать тот же файл и checksum **только в окружение текущего процесса**, без изменения .env:

```powershell
$env:QIL_SECTION_PROVENANCE_FILE = 'C:\path\reviewed-section-provenance.json'
$env:QIL_SECTION_PROVENANCE_SHA256 = '<reviewed-sha256>'
try {
    .\.venv\Scripts\python.exe -B backend/manage.py check_section_provenance
    if ($LASTEXITCODE -ne 0) { throw 'Provenance preflight blocked' }
    .\.venv\Scripts\python.exe -B backend/manage.py migrate --noinput
    if ($LASTEXITCODE -ne 0) { throw 'Migration failed' }
    .\.venv\Scripts\python.exe -B backend/manage.py migrate --check
} finally {
    Remove-Item Env:QIL_SECTION_PROVENANCE_FILE -ErrorAction SilentlyContinue
    Remove-Item Env:QIL_SECTION_PROVENANCE_SHA256 -ErrorAction SilentlyContinue
}
```

Команды не создают manifest и не подтверждают его вместо оператора. После перехода сверить counts/UNIQUE/дату исходного раздела, отсутствие поздних отметок и неизменность legacy дат/generation/attempts/Practice/snapshots. Автоматический lossless downgrade после новых частичных отметок не предусмотрен: удаление новой таблицы уничтожило бы эти отметки и требует отдельного решения.

## Проверки

Локально подтверждены 545 backend/HTTPX-тестов и 46 подтестов, Django checks, makemigrations --check, migrate --check, pip check, 289 frontend unit и type-check/build. Все DB-проверки используют отдельные временные PostgreSQL; cleanup входит в harness. Полные browser-прогоны и CI точного SHA фиксируются отдельно после завершения, без переноса PASS от прежней версии.

Окончательный полный повтор на текущем diff: Chromium 149 PASS, Firefox 149 PASS, WebKit 149 PASS; в каждом прогоне собственные frontend/backend/PostgreSQL и cleanup PASS. Workflow/reporting не менялись; их контрольные суммы сохранены. CI нового SHA ещё не запускался на момент локального PASS; после разрешённого push его шесть executions проверяются отдельно в отчёте публикации.

Первый полный прогон каждого из трёх движков завершился одним одинаковым failure в tests/e2e/test_practice_ui.py::test_entry_hidden_for_disabled_or_draft_task_and_locked_preview_has_no_start: ожидался прежний текст про статью. Ожидание заменено на утверждённое чтение всех Published-разделов, дополнительно проверяется точный 403 section_read_required. После этой правки запущены повторные полные наборы; первый failure не считается PASS. До этого направленная проверка выявила старые topic-level ожидания/перехват URL и helper заголовка первой темы для второй; после адаптации 10 релевантных сценариев прошли.

Новые unit/PostgreSQL/HTTPX проверяют формулы/N=0/M=0, первую дату/UNIQUE/PROTECT, динамические Read/mastery, RU/EN, точные DTO, ownership/cross-topic, CSRF, одновременный read/reset, late writes и rollback. MigrationExecutor на отдельной временной БД проверяет отсутствие proof, неверный поздний origin, существующий/удалённый исходный раздел, точное сохранение дат и старых Attempt/snapshot/generation. Preflight покрыт проверками schema/checksum/binding/coverage.

Регрессия current reader сохраняет тесты hidden/0×0/stale marker, pending POST при смене языка/отказе перевода, явный GET после ошибки POST, focus/keyboard, reload/Back/Forward. Положительные start-сценарии явно читают разделы; отрицательные гейты проверяются прямым HTTP. Полные фактические результаты локальных прогонов и CI точного SHA фиксируются в отчёте задачи; промежуточные падения не объявляются PASS. Будущие страницы и их сквозная приёмка остаются QIL-044/QIL-045.

## Файлы реализации

| Область | Изменённые/новые файлы |
| --- | --- |
| Модель и вычисления | backend/apps/assessments/models.py, reading.py, progress.py, completion.py, progress_state.py |
| Миграция и preflight | assessments/migrations/0005_topic_section_progress.py, section_provenance_v1.py, management/commands/check_section_provenance.py и package __init__.py |
| HTTP и Admin | assessments/views.py, serializers.py; practice/views.py; config/urls.py; learning/content_admin.py |
| Backend QA | assessments/tests/test_section_progress.py, test_section_provenance.py, test_attempt_model.py, test_progress.py, test_completion_database.py; learning/tests/test_sections_migration.py; tests/api/test_section_progress.py, test_attempts.py, test_practice.py, test_progress.py, test_sections.py |
| Совместимость клиента | frontend/src/api/{client,types,decoders}.ts; learning/{model,texts}.ts, LearningApplication.tsx; assessment/{model,texts}.ts; practice/{model,texts}.ts |
| Frontend/E2E QA | frontend/tests/{learning,section-progress}.test.ts; tests/e2e/{learning_data,practice_data,content_admin_data}.py и существующие Assessment/Learning/Progress/Practice/Sections/Reset/Focus/Visual тесты |
| Документация | README.md, frontend/README.md, docs/{PRD,ARCHITECTURE,QA_STRATEGY,BACKLOG,PROGRESS_SPEC,TOPIC_SECTIONS_SPEC,SECTION_PROGRESS_BACKEND}.md |

Workflow/reporting, зависимости/lock-файлы, старые миграции, .env и семь пользовательских корневых check-скриптов не изменяются. Новые учебные темы и dev seed в задачу не входят.
