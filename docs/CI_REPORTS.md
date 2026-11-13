# CI-отчёты и безопасные artifacts — QIL-023

## Исходный аудит

Через официальный GitHub REST API проверен [успешный run 43428542799](https://github.com/rkcz00/qa-interview-lab/actions/runs/43428542799), SHA `19bb5eea74ac6870f5a3f32811cdd24280f8de05`. В памяти открыт единственный ZIP `backend-test-report`: один `backend.xml`, 221 testcase, без failure/error, properties, system-out/system-err. Известных секретов и подозрительных присваиваний не обнаружено; файлы на диск не извлекались.

Найдены пробелы: frontend unit не формировал XML; Playwright XML загружался только при сбое; raw JUnit при будущем падении мог включить exception, assertion diff или параметры с чувствительными значениями. `--show-capture=no` управляет выводом Pytest и сам по себе не очищает весь XML.

## Что публикуется

Четыре обязательных jobs и минимальные `permissions: contents: read` сохраняются. Приложение, API, тесты, зависимости и browser setup не меняются.

| Job | Источник | Artifact |
| --- | --- | --- |
| `backend_api` | Все backend/API-тесты Pytest, реальная PostgreSQL и HTTPX/TCP | `backend_api-junit`, только `junit.xml` |
| `frontend_unit` | Тот же Node `--test` и glob, что в `npm test`, со встроенным JUnit reporter | `frontend_unit-junit`, только `junit.xml` |
| `playwright_e2e` | Вся папка E2E, реальная SPA/Django/PostgreSQL | `playwright_e2e-junit`, только `junit.xml` |
| `frontend_check_build` | Type-check и production build | Artifact не создаётся: тестового JUnit у build нет |

В frontend reporter-флаги стоят перед glob тестовых файлов: передача их через `npm test -- ...` после текущего glob локально не создавала XML. Состав запускаемых тестов сохранён, новый reporter не требует npm-зависимостей.

## Граница безопасности

Raw XML и stdout/stderr тестов находятся только в `RUNNER_TEMP`; они не загружаются в artifacts. Один общий formatter в workflow используется через YAML anchors/aliases. Он создаёт новый XML, а не копирует исходный файл:

- Разрешены только фиксированное имя job, порядковые `case_0001`, числовые counts, ограниченная длительность и итог pass/failure/error/skipped.
- Имена тестов, параметры, исходные failure/error-тексты, stack trace, SQL, properties, stdout/stderr, hostname и пути исключены. Даже название теста не переносится: оно может содержать чувствительный параметр.
- Диагностические сообщения фиксированы. Отсутствующий, повреждённый, слишком большой XML или запрещённый DOCTYPE/ENTITY дают обезличенный error-report и ненулевой exit code formatter.
- Приготовленный заранее выходной файл и symlink-пути отклоняются. Флаг `ready=true` записывается только после создания нового разрешённого XML.

Upload имеет один точный путь `runner.temp/qil-safe-report/junit.xml`, без glob и папок проекта; `include-hidden-files: false`, `if-no-files-found: error`, `retention-days: 7`. `.env`, конфигурация окружения, cookies/CSRF/пароли, raw logs, `.git`, `node_modules`, volumes и DB dumps в этот путь не включаются. Из произвольного входного XML не переносятся текстовые значения.

На успешном run ожидаются ровно три необходимых компактных JUnit artifacts. На ошибке теста они также доступны: formatter запускается с `always() && !cancelled()`, upload — дополнительно только при `steps.report.outputs.ready == 'true'`. Ненулевой exit code исходных тестов сохраняет failure job; `continue-on-error` не используется. При отменённом job formatter/upload пропускаются, отмена не считается PASS.

## Screenshot, trace, video и HTML

Текущие fixtures не записывают trace/HAR/video/auth state. Необязательные локальные screenshots используют отдельные opt-in переменные, которые CI не задаёт. Эти файлы, браузерные HTML-отчёты и сырой вывод не публикуются ни при успехе, ни при сбое: универсальная проверенная очистка содержащихся в них cookies/запросов не реализована.

Поэтому дополнительного media-upload с `if: failure()` сейчас нет. Безопасная диагностика при сбое — структурный JUnit. Если media-диагностика будет добавлена, для неё нужны отдельная очистка, точный список файлов и `if: failure()`; сырой trace запрещён текущей стратегией.

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
