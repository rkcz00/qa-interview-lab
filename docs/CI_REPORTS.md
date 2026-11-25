# CI-отчёты и безопасные artifacts — QIL-023

## Исходный аудит

Через официальный GitHub REST API проверен [успешный run 43428542799](https://github.com/rkcz00/qa-interview-lab/actions/runs/43428542799), SHA `19bb5eea74ac6870f5a3f32811cdd24280f8de05`. В памяти открыт единственный ZIP `backend-test-report`: один `backend.xml`, 221 testcase, без failure/error, properties, system-out/system-err. Известных секретов и подозрительных присваиваний не обнаружено; файлы на диск не извлекались.

Найдены пробелы: frontend unit не формировал XML; Playwright XML загружался только при сбое; raw JUnit при будущем падении мог включить exception, assertion diff или параметры с чувствительными значениями. `--show-capture=no` управляет выводом Pytest и сам по себе не очищает весь XML.

## Что публикуется

Четыре обязательных job ID и минимальные `permissions: contents: read` сохраняются. QIL-031 добавляет browser matrix внутри `playwright_e2e`: шесть executions, включая Chromium full и Firefox/WebKit critical. Приложение/API, миграции и зависимости не меняются; browser fixtures и выбор тестов описаны в [CROSS_BROWSER_ACCEPTANCE](CROSS_BROWSER_ACCEPTANCE.md).

| Job | Источник | Artifact |
| --- | --- | --- |
| `backend_api` | Все backend/API-тесты Pytest, реальная PostgreSQL и HTTPX/TCP | `backend_api-junit`, только `junit.xml` |
| `frontend_unit` | Тот же Node `--test` и glob, что в `npm test`, со встроенным JUnit reporter | `frontend_unit-junit`, только `junit.xml` |
| `playwright_e2e` | Chromium: вся папка E2E; Firefox/WebKit: marker `cross_browser`; реальная SPA/Django/PostgreSQL на каждом runner | `playwright_e2e-chromium-junit`, `playwright_e2e-firefox-junit`, `playwright_e2e-webkit-junit`; каждый только `junit.xml` |
| `frontend_check_build` | Type-check и production build | Artifact не создаётся: тестового JUnit у build нет |

В frontend reporter-флаги стоят перед glob тестовых файлов: передача их через `npm test -- ...` после текущего glob локально не создавала XML. Состав запускаемых тестов сохранён, новый reporter не требует npm-зависимостей.

## Граница безопасности

Raw XML и stdout/stderr тестов находятся только в `RUNNER_TEMP`; они не загружаются в artifacts. Один общий formatter в workflow используется через YAML anchors/aliases. Он создаёт новый XML, а не копирует исходный файл:

- Разрешены только фиксированное имя job, порядковые `case_0001`, числовые counts, ограниченная длительность и итог pass/failure/error/skipped.
- Имена тестов, параметры, исходные failure/error-тексты, stack trace, SQL, properties, stdout/stderr, hostname и пути исключены. Даже название теста не переносится: оно может содержать чувствительный параметр.
- Диагностические сообщения фиксированы. Отсутствующий, повреждённый, слишком большой XML или запрещённый DOCTYPE/ENTITY дают обезличенный error-report и ненулевой exit code formatter.
- Приготовленный заранее выходной файл и symlink-пути отклоняются. Флаг `ready=true` записывается только после создания нового разрешённого XML.

Upload имеет один точный путь `runner.temp/qil-safe-report/junit.xml`, без glob и папок проекта; `include-hidden-files: false`, `if-no-files-found: error`, `retention-days: 7`. `.env`, конфигурация окружения, cookies/CSRF/пароли, raw logs, `.git`, `node_modules`, volumes и DB dumps в этот путь не включаются. Из произвольного входного XML не переносятся текстовые значения.

На успешном run ожидаются ровно пять необходимых компактных JUnit artifacts: backend, frontend unit и три движка. Имя browser artifact включает allowlisted matrix.browser, чтобы независимые uploads не сталкивались. XML formatter по-прежнему принимает только три тестовых job ID; GITHUB_JOB для browser matrix остаётся `playwright_e2e`. На ошибке теста отчёты также доступны: formatter запускается с `always() && !cancelled()`, upload — дополнительно только при `steps.report.outputs.ready == 'true'`. Ненулевой exit code исходных тестов сохраняет failure job; `continue-on-error` не используется. `fail-fast: false` позволяет собрать результаты остальных движков. При отменённом job formatter/upload пропускаются, отмена не считается PASS.

QIL-036 сохраняет эти artifacts при раздельных Python/system-dependencies/browser/startup/test шагах и matrix timeout 30/30/45. Startup preflight использует существующие fixtures с `--setup-only`, не создаёт тестовый JUnit и не заменяет реальные E2E. Его raw output остаётся только в `RUNNER_TEMP/qil-e2e-startup.log`. Если preflight падает, E2E не объявляются выполненными; прежний formatter сообщает отсутствие отчёта безопасным error-report, а job остаётся failure. Для cancelled форматирование/upload по-прежнему пропускаются. Browser cache и дополнительные binary/media artifacts не добавляются. [Lifecycle и приёмка CI](CROSS_BROWSER_ACCEPTANCE.md#qil-036--раздельная-установка-и-бюджет-webkit).

## Screenshot, trace, video и HTML

Текущие fixtures не записывают trace/HAR/video/auth state. Необязательные локальные screenshots используют отдельные opt-in переменные, которые CI не задаёт. Эти файлы, браузерные HTML-отчёты и сырой вывод не публикуются ни при успехе, ни при сбое: универсальная проверенная очистка содержащихся в них cookies/запросов не реализована.

Поэтому дополнительного media-upload с `if: failure()` сейчас нет. Безопасная диагностика при сбое — структурный JUnit и разрешённый QIL-039 summary ниже. Если media-диагностика будет добавлена, для неё нужны отдельная очистка, точный список файлов и `if: failure()`; сырой trace запрещён текущей стратегией.

## QIL-039 — Безопасный Playwright failure summary

Причина изменения: [run 45438460755](https://github.com/rkcz00/qa-interview-lab/actions/runs/45438460755), SHA `db272cc0688eceb96840c22ea7a2bb44d2e7cdeb`, завершился failure трёх browser executions. Raw job log WebKit подтвердил 53 cases и один failure, но исходная политика скрыла имя теста и исключение. Это не доказательство исправления продуктового дефекта; QIL-039 меняет только CI-диагностику.

`tools/playwright_ci.py` сохраняет прежние pytest flags/selection и запускает pytest дочерним процессом с приватными stdout/stderr. Штатный `pytest_runtest_makereport` извлекает только тип исключения и repo-relative координаты, не вызывая форматирование сообщения/traceback. Startup и E2E пишут отдельные временные structured event logs. Отдельный sanitizer затем строит новый summary по allowlist, а не копирует raw log или JUnit failure text.

Формат (synthetic-пример, не результат текущего CI):

```text
Browser: webkit
Failed: 1; Errors: 0
tests/e2e/test_probe.py::test_answer | AssertionError | tests/e2e/test_probe.py:3
```

Публичные поля ограничены:

- browser из chromium/firefox/webkit;
- стабильный nodeid существующей module-level test-функции из AST проверенного checkout; `[parameters]` всегда удаляются;
- exception class из фиксированного списка; неизвестный класс заменяется на `Exception`;
- существующий относительный `tests/.../*.py` и реальный номер строки; приоритет имеет frame самой test-функции;
- counts failed/errors: call failures отдельно от setup/teardown/collection/internal errors. Одинаковые строки параметризованных cases группируются, counts сохраняются.

Неизвестные test IDs, абсолютные/несуществующие пути, неверные номера строк и управляющий текст не отражаются. Sanitizer игнорирует message/traceback/locals/stdout/stderr/env и любые дополнительные поля. Structured input ограничен 1 MB/10 000 events; незавершённый, повреждённый, oversized или symlink input не публикуется. Если подробности недоступны, выводится фиксированный текст и диагностический `Errors: 1`, без выдуманного теста; это не утверждение, что тесты были запущены.

`Publish safe Playwright failure summary` выполняется только с `if: failure()`. Он пишет разрешённую Markdown-таблицу в GitHub Step Summary и короткий job log. При успехе этот шаг skipped; новых diagnostic artifacts нет. Прежние пять обезличенных JUnit artifacts, их formatter/ready-gate и retention 7 дней не меняются. Trace/video/screenshots/HTML, raw logs/XML, cookies, headers, CSRF, passwords, tokens, URLs, environment values и абсолютные пути в новую диагностику не включаются.

Дочерний exit code возвращается без преобразования в success, KeyboardInterrupt остаётся 130; `continue-on-error` и retries не добавлены. Chromium full, Firefox/WebKit critical, fail-fast=false и budgets 30/30/45 сохранены. После formatter/upload шаг `Remove private Playwright temporary files` с `always()` удаляет только пять фиксированных файлов текущего runner: startup/test stdout, raw JUnit и два event logs. Safe JUnit не удаляется. Symlinks/посторонние файлы не удаляются. При принудительной остановке runner выполнение cleanup не гарантируется; приватные файлы не публикуются.

### Проверки QIL-039 и границы

25 локальных synthetic unit/integration tests — PASS: failure, TimeoutError, несколько failures/phase errors, параметр с fake secret/URL/cookie/password, невалидные пути/строки/CLI, malformed/oversized/symlink events, безопасный fallback при внутреннем сбое reporter, неизменный exit code, success без summary, ограниченный cleanup и реальный вложенный pytest с двумя ожидаемыми failures. Вложенные ошибки ожидаемы только внутри зелёного unit-теста; намеренный failing push не создаётся.

YAML/aliases, сохранение остальных jobs и JUnit policy, Bash/Python syntax, Markdown/links, diff/secret scan и точный staged-состав проверяются перед единственным commit/push. CI проверяется для нового SHA: при failure теста job остаётся FAIL, но summary должен присутствовать. Диагностический PASS не означает CI PASS. Продуктовый код/API, миграции, зависимости, .env и семь пользовательских helpers сохраняются.

Изменяемые файлы: workflow, `tools/playwright_ci.py`, `tests/ci/test_safe_playwright.py`, README, CI_REPORTS, CROSS_BROWSER_ACCEPTANCE, QA_STRATEGY, BACKLOG. Новые зависимости не нужны: parser использует stdlib, recorder — уже locked pytest. Локальная команда из корня: `.venv\Scripts\python.exe -B -m unittest discover -s tests/ci -p "test_*.py"`. Новый полезный термин — allowlist: публикуется только заранее разрешённая структура, произвольный текст отбрасывается.

После публикации пользователь может открыть Step Summary failed browser job и сопоставить Test/Exception/Source с исходником. Дополнительные продуктовые исправления не входят в QIL-039. Следующий отдельный шаг — разобрать конкретный failure QIL-038 по новой безопасной диагностике.

## Проверки и предел доказательств

- YAML: все четыре jobs, события, pinned actions, минимальные permissions, общие formatter/upload, точный путь, ready-gate и retention — PASS.
- Локальные canary-примеры: приватные атрибуты/тексты, missing/malformed XML, DOCTYPE и существующий выходной файл — PASS; исходные чувствительные строки не попадают в опубликованный XML/вывод formatter.
- Локальные реально падающие Node/Pytest-примеры — PASS: exit code 1 сохранён, failure отражён обезличенно. Намеренно падающий push/run в GitHub не создавался.
- Реальные frontend/backend/Playwright XML прошли общий formatter: сохранены 130/221/59 testcase соответственно. Frontend unit/type-check/build, 221 backend-тест и 22 подтеста, Django/миграции/pip check, полный Playwright из 59 тестов — PASS. PostgreSQL/процессы/временные файлы очищены; тестовые исходники не менялись.
- Итог нового run и три ZIP/XML artifacts проверяются после разрешённой публикации и фиксируются в отчёте QIL-023. Намеренная failure-ветка GitHub не запускалась.

Компромисс: artifact не содержит имён тестов и подробного traceback. Для подробной диагностики нужен локальный воспроизводимый прогон с теми же зависимостями; сырые данные не публикуются автоматически. Реальная failure-ветка GitHub не запускалась намеренно — подтверждены локальные producer/formatter и статические условия workflow. Долговременный архив и deploy не входят в задачу.

## Источники

- [GitHub: YAML anchors и aliases](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations).
- [Node.js 24: test reporters](https://nodejs.org/download/release/v24.22.1/docs/api/test.html).
- [Pytest: JUnit logging](https://docs.pytest.org/en/stable/reference/reference.html).
- [Upload Artifact: inputs, точные пути и hidden files](https://github.com/actions/upload-artifact).
