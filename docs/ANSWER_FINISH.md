# Answer/Finish — QIL-038

## Решение и границы

Пользователь подтвердил свободный ID QIL-038 и уточнил прежний [PROGRESS_SPEC](PROGRESS_SPEC.md#6-тест-локальное-подтверждение-и-финальная-отправка): на последнем вопросе Finish появляется только после всех подтверждений, до этого скрыт. Базовая версия `c77ff7f` опубликована; [run 45400397751](https://github.com/rkcz00/qa-interview-lab/actions/runs/45400397751) завершён успешно во всех шести executions. Следующее уточнение пользователя в рамках того же QIL-038 добавляет автоматический переход после Answer и меняет только frontend/связанные тесты/документацию. [Backlog](BACKLOG.md#qil-038--answerfinish-и-полный-первый-submit), FR-05/06 и TFL-01–TFL-05 — критерии. Backend/API, TFL-06/login, sections, Practice, scoring/mastery/completion/reset, миграции, зависимости, CI и deployment в уточнении не меняются.

Маршруты прежние: `/topics/{id}/test` → `/attempts/{id}`; POST submit остаётся `/api/v1/attempts/{id}/submit/`. PracticeTask не входит в этот Attempt.

## Клиент

- «Предыдущий — Ответить — Следующий» сохраняет возможность пропустить экран и вернуться. Answer требует непустой выбор: один radio или хотя бы один checkbox. Без выбора показана ошибка, перехода нет. С выбором Answer локально подтверждает текущий вопрос и сразу открывает следующий, фокусируя его заголовок; HTTP и оценки нет.
- ReadonlySet подтверждённых question IDs хранится рядом с выбором в AttemptStore, только в памяти экрана. Доступный status сообщает answered, отдельный текст — число подтверждений. Изменение/clear снимает только одно подтверждение; повтор того же выбора его сохраняет. После возврата Answer вновь подтверждает изменённый ответ и переводит вперёд; последний только подтверждает, без перехода/submit.
- Store принимает ожидаемый question ID и отклоняет устаревшее действие. UI отбрасывает второй native click двойного нажатия, включая клик по появившемуся Finish, и при необходимости восстанавливает focus нового заголовка. Это защищает заранее заполненный следующий вопрос без таймера и не мешает последовательным клавиатурным подтверждениям.
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

## Приёмка базовой версии

Локальная приёмка 24 ноября 2026 года — PASS:

- Полный backend/HTTPX: 435 тестов и 22 подтеста; Django checks, makemigrations --check --dry-run, migrate --check и pip check.
- Полный frontend unit: 256/256; type-check и production build.
- Chromium full: 133/133. Firefox/WebKit: по 51 уникальному critical-сценарию — основной прогон 48 и дополнительный прогон трёх transport-тестов, помеченных cross_browser после начала основной collection. Все шесть новых desktop/mobile сценариев также отдельно прошли в каждом движке.
- Ошибок/skips нет. Browser contexts, backend/frontend дочерние процессы и собственные БД очищены; read-only PostgreSQL count test_qil006_* = 0. Пользовательская dev-БД не сбрасывалась.
- YAML 1.2/aliases, неизменность workflow с четырьмя job IDs и тремя browser executions, Markdown/ссылки, git diff --check и scan реальных локальных секретов/ключей прошли. Финальная редакция документации и staged blobs проверяются перед commit.

CI базового SHA `c77ff7f` подтверждён [run 45400397751](https://github.com/rkcz00/qa-interview-lab/actions/runs/45400397751): backend_api, frontend_check_build, frontend_unit и три playwright_e2e completed/success. Начальный WebKit focus-failure устранён явным focus на выбранном radio; assertions не ослаблены.

## Уточнение: автоматический переход после Answer

Runtime изменён только в `frontend/src/assessment/model.ts`, `AssessmentApplication.tsx`, `texts.ts`. Связанные тесты: `frontend/tests/assessment.test.ts`, `tests/e2e/test_assessment_ui.py`, `test_answer_finish.py`, новый `test_answer_advance.py` и `learning_data.py`. Последний добавляет третью полную двуязычную question только явным fixture-действием в собственной временной PostgreSQL через существующую операцию edit_topics; dev-контент и backend-код не меняются. Пользователь отдельно разрешил уточнение общих helpers в `tests/e2e/test_auth_ui.py` и `test_learning_ui.py` после диагностики HTTP 304.

Два новых unit и два desktop/mobile E2E проверяют заранее заполненные три вопроса, native double click, focus, локальный последний Answer, Back → изменение → новый Answer, RU/EN и browser Back/Forward. Прежние шесть Answer/Finish E2E сохранены и адаптированы к автопереходу. Все существующие сценарии сохраняют собственные проверки результата/transport; helper больше не делает лишний Next после Answer.

Frontend unit 258/258, type-check/build и focused E2E 8/8 в каждом движке — PASS. Первый полный прогон: Chromium 135 PASS; Firefox 132 PASS / 3 FAIL; WebKit 133 PASS / 2 FAIL, без skips. Все Answer/Finish прошли; ошибки были в старых helpers прямой SPA-навигации. После согласованной правки helpers диагностические три сценария прошли в обоих движках, затем одинаковый полный suite прошёл в Chromium/Firefox/WebKit: по 135 PASS, ноль failures/skips. CI-конфигурация сохранена: полный Chromium и critical Firefox/WebKit, отдельные безопасные JUnit. Первый focused прогон выявил потерю focus на повторном mousedown: добавлено восстановление focus при отклонённом клике, assertion сохранён, повторный focused прогон всех движков успешен.

Изолированная диагностика без подмены ответов установила причину пяти E2E-сбоев: повторный `/login` возвращал 304 в Firefox/WebKit, повторная статья — 304 в Firefox. Helpers ошибочно требовали 200 от каждого `page.goto`. [RFC 9110 §15.4.5](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.4.5) разрешает 304 для условного GET. С согласия пользователя helpers теперь сначала отдельно требуют HTTP 200 через APIRequestContext без браузерного кэша, затем допускают 200/304 браузерной навигации и сохраняют обязательные проверки DOM. Ответы API, runtime, cache policy приложения и assertions доступности/ownership не меняются; перехвата или подмены критического HTTP нет.

Документация уточнения: `README.md`, `frontend/README.md`, `docs/PRD.md`, `ARCHITECTURE.md`, `QA_STRATEGY.md`, `BACKLOG.md`, `PROGRESS_SPEC.md`, этот отчёт. Итого 18 файлов: три runtime, семь тестовых (включая один новый), восемь документов.

Первый backend regression: 456 успешных проверок и один setup PermissionError на `ready_file.is_file()` в HTTPX harness; это проверка временного файла готовности, причина отказа доступа не установлена. Повтор только упавшего теста прошёл. Затем полный последовательный повтор завершён успешно: 435 тестов и 22 подтеста (457 passed), ноль failures/skips, Django checks, makemigrations --check --dry-run, migrate --check, pip check и cleanup — PASS. Harness не изменялся; первоначальный сбой не скрывается.

Финальная локальная приёмка уточнения — PASS: frontend unit/type-check/build, полный backend/HTTPX, миграции/Django/pip, полный suite 135 × 3. Тестовые исходники совпадают с хешами до финального прогона. Контексты/дочерние процессы завершены штатными teardown; read-only PostgreSQL count test_qil006_* = 0. Dev-БД и работающие пользовательские сервисы не сбрасывались.

Перед единственным commit/push проверяются границы diff, Markdown/ссылки, YAML, staged blobs и отсутствие секретов. Новый CI подтверждается только для опубликованного SHA; локальный PASS его не заменяет. Повторный push/re-run не разрешён. Локальная ручная приёмка нового автоперехода — NOT_RUN, следующий отдельный пользовательский шаг.

`.env` и семь пользовательских untracked helpers не меняются и не добавляются. Все DB/browser-прогоны используют собственные временные БД/процессы; dev-БД не сбрасывается. Локальная ручная приёмка обновлённого Answer/Finish остаётся отдельным пользовательским шагом.

## QIL-040 — Устойчивый focus после Answer

Исходный [CI run 45608561380](https://github.com/rkcz00/qa-interview-lab/actions/runs/45608561380), SHA `7a2d8f612d5842626b5ccdaccedc5ae07e50de33`, подтвердил AssertionError в `test_answer_advance.py:40` во всех трёх движках: новый h2 не удержал focus после двойного Answer. QIL-039 корректно сообщил failed=1/errors=0 и не маскировал падение. Исправление приложения выделено в QIL-040; formatter, workflow и artifacts не меняются.

Локальная исходная версия на Windows прошла конечный focus-assertion, но запись только типов DOM-событий показала переход h2 → Answer → h2: второй mousedown забирал native focus, а обработчик второго click пытался восстановить его позднее. Защита только в click оставляла лишнее изменение фокуса. Новая регрессия запрещает такой промежуточный возврат и падает на исходной версии; прежний конечный assertion сохранён. Это прямое локальное доказательство дефекта последовательности, а не заявление о воспроизведении Linux timing.

В AssessmentApplication добавлен preventDefault только для повторного mousedown после успешного автоперехода. Первый pointer click и клавиатурная активация не перехватываются. Существующий effect фокусирует h2 с tabIndex=-1, второй click по-прежнему игнорируется, fallback восстановления focus сохранён. Таймеров, HTTP, глобальных обработчиков или изменений AppShell нет. Последний Answer не делает submit; прежний отдельный Finish, выбор/подтверждения, RU/EN, Back/Forward и ошибки остаются прежними.

Unit расширен на оба исходных языка. E2E сохраняет все прежние assertions и проверяет двойной Answer на заранее заполненном следующем вопросе, отсутствие возврата focus на кнопку, Enter/Space, radio/checkbox, Back/изменение, RU↔EN/Back/Forward, последний Answer без POST и один явный Finish. Все восемь комбинаций начального языка, клавиши и desktop 1280×900/mobile 390×844 помечены cross_browser; критические HTTP-ответы не подменяются. Диагностический listener сохраняет только метки heading/answer в памяти страницы, без логов, текстов, ответов или credentials.

Локально подтверждены 259 frontend unit, type-check/build, 24 focused E2E (8 на движок) и полный Playwright: по 141 PASS в Chromium/Firefox/WebKit. Используются production frontend и реальный Django/HTTP с собственной временной PostgreSQL. Прежние assertions не удалены и не ослаблены.

Первый полный backend-прогон завершился exit=1; pytest cache указал `tests/api/test_practice.py::test_absent_configuration_missing_ids_and_draft_content_return_404`. Подробности первоначального сбоя runner не сохранил, поэтому его причина не объявляется установленной. Отдельный повтор этого теста на новой временной БД завершился exit=0. После browser suite полный последовательный backend-прогон подтвердил 460 PASS и 46 успешных подтестов, ноль failures/errors/skips. Исходники backend/harness не менялись; первый FAIL не подменяется одиночным повтором.

Django checks, makemigrations --check --dry-run, migrate --check и pip check — PASS на отдельной временной PostgreSQL. Все browser contexts и собственные frontend/backend процессы прошли teardown; итоговые read-only counts test_qil006_* и unused_* равны нулю. Dev-БД не сбрасывалась. YAML/matrix/35 Bash-проверок, неизменность sanitizer/JUnit, Markdown/ссылки, diff и secret scan прошли; финальные staged blobs отдельно проверяются перед commit. CI нового SHA подтверждается после единственного разрешённого push; локальный PASS не заменяет CI. Новая ручная пользовательская приёмка — NOT_RUN. Backend/API, миграции, зависимости, .env и семь пользовательских helpers сохранены.

Файлы QIL-040: `frontend/src/assessment/AssessmentApplication.tsx`, `frontend/tests/assessment.test.ts`, `tests/e2e/test_answer_advance.py`, этот отчёт и `docs/BACKLOG.md`. Новых проектных файлов и зависимостей нет; локальная служебная диагностика остаётся вне Git.

Новый термин для изучения: default action mousedown — штатное действие браузера, которое может переместить focus ещё до click; preventDefault отменяет именно его для повторного нажатия. Изменение не отменяет сам Answer и не подменяет доступность кнопки.

## Что проверить пользователю

На desktop/mobile открыть тест, пропустить вопрос, вернуться и подтвердить radio/checkbox. Проверить, что пустой Answer показывает ошибку, выбранный Answer открывает ровно следующий вопрос с focus, двойной клик не пропускает экран. RU/EN и Back/Forward сохраняют выбор/подтверждения, изменение снимает только одно. Последний Answer не отправляет HTTP; после всех подтверждений отдельный Finish даёт один результат без ключей, snapshot и Practice. Ручная приёмка автоперехода — отдельный следующий шаг; sections автоматически не начинаются.
