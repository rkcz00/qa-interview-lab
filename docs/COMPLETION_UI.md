# Completion progress и reset UI — QIL-035

## Согласованный объём

Текущее явное задание QIL-035 реализует frontend по [PROGRESS_SPEC](PROGRESS_SPEC.md) поверх backend QIL-034. Уточнения пользователя: reset возвращает 200 с generation; Published Practice входит в completion (30/35/35), но не mastery; Answer/Finish исключён. Прежний план test flow, который использовал тот же ID, сохранён как отложенный TFL-scope в [backlog](BACKLOG.md); новый номер ему не назначается автоматически.

Backend/API, миграции, CI, зависимости, `.env` и семь пользовательских untracked-скриптов не меняются. Локальный npm ci использует существующий lock; для освобождения Rolldown был остановлен только проверенный проектный Vite-процесс. Настройки Windows не менялись.

## Отображение

ProgressStore объединяет completion-снимок с RU-каталогом для названий и навигации. Membership и числовой порядок строк /progress берутся из completion; левое меню сохраняет порядок каталога, чтобы совпадать с домашней страницей. При разнице публикации между двумя GET используется безопасное название «Тема №ID», без раскрытия Draft-текста. Overall и topic percentage копируются с сервера без вычислений, а mastery берётся из серверного bool. Счётчик освоенных тем считает эти bool отдельно от процента.

На `/progress`: Read/not read; test/practice unattempted/failed/passed с русскими подписями; отсутствие опубликованной Practice; correct_count/total_count и процент лучшего теста. Дополнительные counts/attempt history в API отсутствуют и не выдумываются. Snapshot, ответы, server keys, внутренние revision и generation не показываются. Общий прогресс одинаков для RU/EN. AppShell/sidebar используют тот же store; успешные изменения Read/Test/Practice запускают фоновый GET с сохранением DOM/фокуса.

## Reset и ошибки

Кнопка отделена от основного контента. Native dialog имеет заголовок/описание, предупреждает об удалении Read/Attempt/PracticeSubmission, истории и незавершённых работ, сохранении account/content и необратимости. Начальный фокус — «Отмена», Tab остаётся внутри, Escape отменяет до запроса, обязательная галочка включает подтверждение. Галочка синхронизируется до показа окна; повторное открытие не наследует прежнее согласие. Pending блокирует повтор и закрытие; после закрытия фокус возвращается к кнопке.

Один подтверждённый action создаёт UUID v4 в памяти и фиксирует исходный generation. POST выполняет существующий клиент с CSRF/credentials. После 200 загружаются completion/catalog; старое read-only отображение сохраняется до успешного GET не старше подтверждённого generation. Отображается полученное состояние, а не выдуманный ноль: новые законные действия другой вкладки могут уже дать новый прогресс.

При 400/403/500 показывается безопасный отказ и допускается только явный повтор. При 409 progress_reset/reset_request_conflict сначала запрашивается актуальное состояние, без автоматического POST. Отмена/переоткрытие конфликта сохраняет необходимость GET. При network/timeout/protocol uncertainty нужен явный GET, затем явный повтор того же UUID, тела и исходного generation. GET сам по себе не доказывает квитанцию данного UUID; экран не заявляет успех до подтверждённого POST + GET. Если POST подтверждён, а GET упал, повторяется только GET.

Клиент блокирует stale writes и уведомляет вкладки сигналом без личных данных. Общий обработчик очищает старые private stores/end-marker переходом на /progress. Только активный контроллер своего reset может отменить этот переход ради замороженного отображения. Смена session передаётся отдельной причиной и всегда открывает /login, даже если reset уже блокирует записи. Потеря session при любом GET/POST немедленно удаляет приватный view; поздние ответы и unmount не восстанавливают его. Источником ownership остаётся backend.

## Проверки

Unit проверяют перенос серверных процентов без пересчёта (включая искусственно независимый overall), 30/70, 30/35/35, M=0 JSON, статусы/mastery, публичные поля, empty/errors, отмену, double submit, pending POST/GET, 200+GET, ошибки/конфликт, сохранность квитанции, поздние ответы и session loss. M=0 — защитный unit-контракт: текущие правила публикации не позволяют создать реальную Published-тему без вопросов; E2E не обходят это правило.

Playwright использует реальный React/Django/временную PostgreSQL. Критический путь на desktop 1280×900 и mobile 390×844 включён в Chromium/Firefox/WebKit: статусы/результаты, dialog/keyboard/cancel, single-flight reset, подтверждённый GET, ownership/старые ID, Draft/empty, CSRF/validation/409 и потеря session. Negative transport-сценарии перехватывают только транспорт: фактический POST доходит до backend, затем его ответ теряется или падает GET. Проверяется сохранность новой записи после идемпотентного повтора и очистка frozen view при logout из соседней вкладки. Media/credentials/сырые ошибки не сохраняются в CI artifacts.

Локальная автоматическая приёмка завершена. Ручная пользовательская проверка нового UI проводится отдельно; тесты используют собственные временные БД.

## Фактические результаты — 24 ноября 2026 года

- PASS — npm ci из существующего lock; frontend unit: 251/251, type-check и production build.
- PASS — полный backend/HTTPX: 404 теста и 22 подтеста на временной PostgreSQL 17.11; Django checks, makemigrations --check --dry-run, migrate --check, pip check.
- PASS — финальный полный Chromium suite: 127/127; критический Firefox: 42/42; WebKit: 42/42, desktop 1280×900 и mobile 390×844. Пропусков нет.
- PASS — закрытие браузерных context/browser, backend/frontend child processes и удаление только собственных временных БД; итоговый read-only count test_qil006_* = 0. Dev-БД не сбрасывалась.
- PASS — Markdown и внутренние ссылки 11 документов, git diff --check, scan изменённых файлов на реальные локальные секреты и ключи. .env игнорируется и отсутствует в индексе.
- PASS — read-only ревью workflow: четыре job IDs и три browser executions сохранены; YAML совпадает с принятым baseline побайтово. Отдельный YAML parser локально NOT_RUN: он не установлен, новая зависимость не добавлялась. GitHub проверяет тот же workflow после публикации.
- NOT_RUN — отдельная ручная пользовательская приёмка этого UI. Answer/Finish, sections и deployment остаются отдельным scope.

CI точного нового SHA проверяется после единственного разрешённого push; run URL, job/check-run evidence и окончательный статус приводятся в финальном отчёте публикации. Числа выше относятся к локальным проверкам этой версии.

### Разобранные и неповторившиеся падения

Ранние E2E обнаружили гонку сброса галочки при повторном открытии dialog и особенность WebKit: click не всегда фокусирует кнопку-инициатор. Галочка теперь синхронизируется до показа dialog; кнопка получает фокус перед открытием. Финальные проверки сохранили исходные требования и прошли во всех трёх движках. Fault injection timeout ограничен reset POST, чтобы не затрагивать обычные CSRF/GET.

Первый локальный backend-run завершился exit=1 без доступного диагностического testcase. Причина не установлена. Отдельный полный повтор дал 404 PASS и 22 PASS подтеста; это неповторившийся сбой, а не доказательство исправления backend. Результат браузерного прогона, потерянный при прерывании сессии, не использован: финальная матрица запущена заново.

## Файлы изменения

Всего 30: пять созданных и 25 изменённых. Созданы:

- [docs/COMPLETION_UI.md](COMPLETION_UI.md)
- [frontend/src/progress/ResetDialog.tsx](../frontend/src/progress/ResetDialog.tsx)
- [frontend/tests/progress-fixture.ts](../frontend/tests/progress-fixture.ts)
- [frontend/tests/progress-reset.test.ts](../frontend/tests/progress-reset.test.ts)
- [tests/e2e/test_completion_ui.py](../tests/e2e/test_completion_ui.py)

Изменены:

- [README.md](../README.md)
- [docs/ARCHITECTURE.md](ARCHITECTURE.md)
- [docs/BACKLOG.md](BACKLOG.md)
- [docs/COMPLETION_BACKEND.md](COMPLETION_BACKEND.md)
- [docs/PRACTICE_SPEC.md](PRACTICE_SPEC.md)
- [docs/PRD.md](PRD.md)
- [docs/PROGRESS_SPEC.md](PROGRESS_SPEC.md)
- [docs/QA_STRATEGY.md](QA_STRATEGY.md)
- [docs/TOPIC_SECTIONS_SPEC.md](TOPIC_SECTIONS_SPEC.md)
- [frontend/README.md](../frontend/README.md)
- [frontend/src/api/client.ts](../frontend/src/api/client.ts)
- [frontend/src/api/index.ts](../frontend/src/api/index.ts)
- [frontend/src/practice/PracticeApplication.tsx](../frontend/src/practice/PracticeApplication.tsx)
- [frontend/src/progress/ProgressApplication.tsx](../frontend/src/progress/ProgressApplication.tsx)
- [frontend/src/progress/model.ts](../frontend/src/progress/model.ts)
- [frontend/src/progress/texts.ts](../frontend/src/progress/texts.ts)
- [frontend/src/styles.css](../frontend/src/styles.css)
- [frontend/src/ui/AppShell.tsx](../frontend/src/ui/AppShell.tsx)
- [frontend/src/ui/OverviewContext.tsx](../frontend/src/ui/OverviewContext.tsx)
- [frontend/src/ui/TopicSidebar.tsx](../frontend/src/ui/TopicSidebar.tsx)
- [frontend/tests/completion.test.ts](../frontend/tests/completion.test.ts)
- [frontend/tests/progress.test.ts](../frontend/tests/progress.test.ts)
- [tests/e2e/test_assessment_ui.py](../tests/e2e/test_assessment_ui.py)
- [tests/e2e/test_learning_workspace.py](../tests/e2e/test_learning_workspace.py)
- [tests/e2e/test_progress_ui.py](../tests/e2e/test_progress_ui.py)

Backend/API, миграции, lock/dependencies, workflow, .env и семь исходных пользовательских untracked-скриптов проверены по исходным hashes и сохранены. Новых runtime-зависимостей нет.

Квитанция reset — UUID действия и исходный generation в памяти. Она позволяет явно повторить потерянный запрос без второго удаления нового прогресса. Native dialog использует встроенное управление modal focus браузера; дополнительные библиотеки не потребовались.


## Что проверить вручную

На отдельном тестовом аккаунте открыть /progress, сравнить процент и отдельное освоение, перейти к теме и вернуться Back/Forward. Проверить mobile menu, Tab/Shift+Tab, отмену и повторное открытие dialog с пустой галочкой. После подтверждённого сброса дождаться GET и проверить отсутствие прежних работ. Не сообщать пароли/CSRF. Общий учебный контент и аккаунт должны сохраниться.

Следующий отдельный scope — Answer/Finish/TFL либо sections QIL-036 по решению пользователя; в этом milestone они не реализуются.
