# Answer/Finish — QIL-038

## Решение и границы

Пользователь подтвердил свободный ID QIL-038 и уточнил прежний [PROGRESS_SPEC](PROGRESS_SPEC.md#6-тест-локальное-подтверждение-и-финальная-отправка): на последнем вопросе Finish появляется только после всех подтверждений, до этого скрыт. [Backlog](BACKLOG.md#qil-038--answerfinish-и-полный-первый-submit), FR-05/06 и TFL-01–TFL-05 — критерии этой задачи. Отдельный TFL-06/login, sections, Practice, scoring/mastery/completion/reset, миграции, зависимости, CI и deployment не меняются.

Маршруты прежние: `/topics/{id}/test` → `/attempts/{id}`; POST submit остаётся `/api/v1/attempts/{id}/submit/`. PracticeTask не входит в этот Attempt.

## Клиент

- «Предыдущий — Ответить — Следующий» сохраняет возможность пропустить экран и вернуться. Answer требует непустой выбор: один radio или хотя бы один checkbox. Он не делает HTTP, не оценивает выбор и не переключает вопрос.
- ReadonlySet подтверждённых question IDs хранится рядом с выбором в AttemptStore, только в памяти экрана. Доступный status сообщает answered, отдельный текст — число подтверждений. Изменение/clear снимает только одно подтверждение; повтор того же выбора/Answer его сохраняет.
- RU/EN, загрузка/ошибка перевода и Browser Back/Forward того же адреса сохраняют номер, выбор и подтверждения. Reload/уход теряют локальное состояние с явной подсказкой; autosave, storage, QuestionAttempt и новые API не добавляются.
- Finish виден только на последнем вопросе после всех подтверждений. Store также запрещает отправку без них, а answerPayload отвергает пустые наборы. Уход в sending синхронный, поэтому двойной клик не даёт второй POST. Payload содержит только language и массив question_id/choice_ids.
- Сохраняется прежняя frozen-модель для network/timeout: GET проверяет результат, автоматического POST нет, явный retry отправляет тот же payload. Изменённый повтор →409 и GET сохранённого результата. Result по-прежнему содержит только три серверных агрегата.
- Во время проверки выявлена потеря radio focus при pointer-смене языка в WebKit. LanguageSelector явно фокусирует выбранный input перед существующим переходом; focus-assertion сохранён. Остальные learner-экраны покрывает browser regression.

## Сервер

InitialSubmitAttemptSerializer допускает отсутствующий answers только для первого in_progress, чтобы классифицировать его как неполноту. grade_initial_snapshot дополняет отсутствующий choice_ids пустым набором только у структурно допустимого объекта question_id. Затем неизменённый grade_snapshot валидирует **все** типы, ID, дубли, extras и cardinality Single-choice. Любая структурная ошибка имеет приоритет над неполнотой.

После структурной валидации пустой выбор любого вопроса нормализованного snapshot означает 400:

```json
{"error":{"code":"incomplete_answers","message":"Answer every question before submitting the test."}}
```

Статус, ответы, результат и submitted_at не сохраняются. Подставленный confirmed запрещён. Полный допустимый payload использует прежний exact-set/ROUND_HALF_UP. Один выбранный checkbox допустим и может дать неправильный ответ; требование двух выбранных вариантов не вводится и число correct keys не раскрывается.

У уже submitted остаются прежние SubmitAttemptSerializer и grade_snapshot. Нормализованный повтор исторического payload с пропусками возвращает тот же 200/дату, изменённый допустимый —409 attempt_already_submitted. Отсутствующий answers/choice_ids у submitted остаётся validation_error. Исторические результаты не пересчитываются. User/Attempt locks, generation, CSRF, lookup/ownership, транзакция и snapshot не меняются.

## Тесты и данные

Новые unit проверяют полноту/приоритет и неизменность scoring; frontend unit — локальное Answer, guards Finish, подтверждения/clear/no-op/RU/EN/reload/session loss и frozen payload. HTTPX использует действующие session/CSRF/generation и настоящий TCP: отсутствие answers/question/choice_ids, пустые наборы, смешанные ошибки, rollback и корректная повторная отправка. Исторический submitted с пропусками создаётся только тестовым ORM-fixture в отдельной БД и проверяется через реальные API.

Прежние regression-fixtures с новым пустым submit заменены полным допустимым неверным выбором, сохраняя проверки нулевого результата, Practice prerequisites, progress, Admin, snapshot и concurrency. Чистые исторические scoring-тесты не меняются. Существующие transport/CSRF/ownership/409/E2E сохраняются и проходят через новые локальные подтверждения.

Шесть новых E2E (desktop 1280×900 / mobile 390×844) включены в cross_browser: skip/return, radio/checkbox/keyboard, отсутствие POST на Answer, подтверждения при RU/EN/Back/Forward, скрытый Finish, clear, reload, двойной клик и реальный incomplete_answers с явным успешным Finish. Три существующих Assessment transport-сценария (потерянный сохранённый ответ, network + frozen retry, timeout без автоматического POST) также включены в cross_browser. Критический путь не замокан; negative-route изменяет только запрос или транспорт, который проверяет настоящий backend. Сырые ответы/credentials/media не публикуются.

## Фактическая приёмка

Локальная приёмка 24 ноября 2026 года — PASS:

- Полный backend/HTTPX: 435 тестов и 22 подтеста; Django checks, makemigrations --check --dry-run, migrate --check и pip check.
- Полный frontend unit: 256/256; type-check и production build.
- Chromium full: 133/133. Firefox/WebKit: по 51 уникальному critical-сценарию — основной прогон 48 и дополнительный прогон трёх transport-тестов, помеченных cross_browser после начала основной collection. Все шесть новых desktop/mobile сценариев также отдельно прошли в каждом движке.
- Ошибок/skips нет. Browser contexts, backend/frontend дочерние процессы и собственные БД очищены; read-only PostgreSQL count test_qil006_* = 0. Пользовательская dev-БД не сбрасывалась.
- YAML 1.2/aliases, неизменность workflow с четырьмя job IDs и тремя browser executions, Markdown/ссылки, git diff --check и scan реальных локальных секретов/ключей прошли. Финальная редакция документации и staged blobs проверяются перед commit.

CI точного SHA проверяется после единственного разрешённого push; URL и результаты шести executions приводятся в финальном отчёте, без повторного push/re-run. Локальный PASS не заменяет итог GitHub Actions. Начальный WebKit focus-failure устранён явным focus на выбранном radio; assertions не ослаблены, после правки прошли focused и regression прогоны.

`.env` и семь пользовательских untracked helpers не меняются и не добавляются. Все DB/browser-прогоны используют собственные временные БД/процессы; dev-БД не сбрасывается. Локальная ручная приёмка обновлённого Answer/Finish остаётся отдельным пользовательским шагом.

## Что проверить пользователю

На desktop/mobile открыть тест, пропустить вопрос, вернуться и подтвердить radio/checkbox. Убедиться, что Answer не завершает тест, смена RU/EN сохраняет подтверждения/focus, а изменение ответа скрывает Finish до нового Answer. После подтверждения всех вопросов на последнем нажать Finish: один результат без ключей, snapshot и Practice. Следующий отдельный milestone — согласование sections и её ID; автоматически он не начинается.
