# Backend объективной практики — QIL-029

Контракт — [PRACTICE_SPEC.md](PRACTICE_SPEC.md). Область QIL-029 уточнена пользователем: только backend; клиент и Practice UI будут отдельной задачей. Полная правка Published разрешает новый start с новым snapshot; запрет новых start действует после unpublish. Старые работы остаются на прежнем snapshot.

## Изменения

- Django-модуль apps.practice: TopicPractice, PracticeTask, PracticeTaskTranslation, PracticeSubmission; additive-миграция создаёт только новые таблицы, ограничения и индекс.
- Два нормализатора v1, проверка исходных 5000 Unicode scalar values, типы/пустота и точное сравнение без исполнения Python/SQL.
- Все пять GET/POST-маршрутов, только собственные submissions, sessions/CSRF, явные serializers, immutable snapshot и прежние дата/verdict при эквивалентном submit.
- Запись контента использует Topic lock и обязательную expected_revision; Published Practice сохраняет полноту даже у Draft Topic. В Admin добавлены только три контентные модели. PracticeSubmission не регистрируется.
- Форма Admin не удаляет значимые пробелы эталона. HTML CRLF приводится к каноническому эталону только объявленным режимом. Публикация требует редакторского подтверждения эталона и SQL scalar-result; семантику произвольного SQL сервер не исполняет и не доказывает.
- Старые DTO, прогресс, scoring и русский frontend не меняются. Старый E2E fixture проверяет расширенный allowlist Content Admin (11 моделей), остальные сценарии сохраняются.

## Реальные проверки и ограничения

Из Codex Docker API и PostgreSQL вернули отказ permission policy, в том числе после сообщённого пользователем перезапуска Docker. Повторные попытки прекращены; обход, установка и изменение PATH не выполняются. В Codex пройдены 48 unit-тестов Practice, Django checks, pip check, 171 frontend unit и type-check/build, offline-согласованность миграции, Markdown/ссылки, syntax/whitespace и secret scan. Эти результаты отдельно не заменяют PostgreSQL/HTTPX/Playwright.

После исправления фикстуры пользователь повторно запустил tools/check_practice_backend.py в обычном PowerShell. Получен полный лог RESULT=PASS: временная PostgreSQL, migrate, Django checks, makemigrations --check, migrate --check, pip check, 332 backend/HTTPX-теста и 22 подтеста, 171 frontend unit, type-check/build и 87 Playwright-тестов. TEMP_CLEANUP=PASS и FILES=PASS подтверждают очистку и сохранность файлов. Код в workspace побайтно совпал с ранее проверенной версией; после прогона обновляется только документация.

Первый ручной прогон выявил коллизию email в ownership-фикстуре для роли learner. Исправлен только адрес второго пользователя и добавлена проверка разных ID; проверки доступа не ослаблялись. Повторный успешный полный прогон выше заменяет прежний FAIL для исправленной версии. Результат CI точного commit SHA фиксируется в итоговом отчёте после единственного согласованного push; ручной PASS не выдаётся за GitHub Actions PASS. Dev-БД и Docker volumes этот runner не меняет.

## Один файл проверки

Используйте [tools/check_practice_backend.py](../tools/check_practice_backend.py). Из корня проекта:

```powershell
.\.venv\Scripts\python.exe .\tools\check_practice_backend.py
```

Также можно запустить файл системным Python по абсолютному пути: он сам переключится на .venv проекта и найдёт корень независимо от текущей папки.

На Windows исходный процесс теперь ждёт проектную .venv, поэтому приглашение PowerShell возвращается после завершения проверки. Долгие стадии печатают RUNNING с прошедшим временем каждые 30 секунд, без сырых логов. Backend имеет общий timeout 15 минут, Playwright — 25 минут; RESULT=FAIL означает завершённый неуспешный прогон, а не зависание.

Предпосылки: запущенная локальная PostgreSQL из существующего Compose, действующий .env, проектная .venv с locked QA-зависимостями, Node/npm, frontend/node_modules и уже согласованные браузерные бинарники. Скрипт ничего не устанавливает и не вызывает Docker API. Если предпосылки не выполнены, он сообщает BLOCKED/FAIL без вывода приватных значений.

Скрипт использует существующий пароль только в памяти, генерирует временный Django key и создаёт новую PostgreSQL-БД. Миграции, Django/migration checks и полный backend pytest выполняются с отдельной БД; pytest/HTTPX используют свой существующий disposable harness. Затем проверяются frontend unit/type-check/build и весь текущий Playwright, у которого также собственная БД/процессы.

При завершении удаляется только созданная скриптом временная БД; fixtures очищают принадлежащие им БД/процессы. Dev-БД, Docker volumes, .env, Git и старые check-*.py не меняются. Исходники и защищённые файлы сравниваются до/после по хешам, значения не печатаются. Нет HTML/trace/video/скриншотов и файлов с ответами/секретами. При сбое печатаются только названия test-функций без параметров, exit code и безопасный статус.

Критерий успешного ручного прогона: каждый обязательный шаг PASS, TEMP_CLEANUP=PASS, FILES=PASS и итог RESULT=PASS. Сам факт наличия runner и тестовых файлов не является этим доказательством.

## Объём новых тестов

- Unit: режимы/line endings/ASCII trim/TAB/NBSP/case/Unicode, пустой эталон, raw limit, неправильные JSON-типы, строгие DTO и отсутствие внутренних полей.
- PostgreSQL: FK/UNIQUE/CHECK, каноничность, SQL-вход, RU/EN/publish/rollback/revision, неизменность snapshot/финальных полей, CASCADE аккаунта, сохранность старых данных при миграции.
- HTTPX/TCP: preview/start/get/submit/delete, порядок отказов, все ошибки, CSRF/auth/ownership, эквивалентные повторы/409, edit/unpublish, старая/новая версия, raw Unicode, сохранность progress/mastery, гонки submit/delete/start/edit и два редактора.

Practice UI, пользовательские API-методы frontend и Practice E2E остаются следующей задачей. Текущий Playwright проверяет регрессию существующего MVP, а не отсутствующий UI практики.
