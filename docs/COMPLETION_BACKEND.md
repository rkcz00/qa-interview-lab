# Backend completion progress и reset — QIL-034

## Объём и состояние

Текущее задание пользователя ограничено backend по [PROGRESS_SPEC](PROGRESS_SPEC.md) и необходимой типовой совместимостью клиента, без визуальных изменений. Реализованы расчёт, два endpoint, generation для всех семи учебных POST и additive-миграция `assessments/0004_user_progress_state`. UI нового процента/статусов и кнопка reset остаются NOT_IMPLEMENTED; исходный общий QIL-034 в [backlog](BACKLOG.md) поэтому остаётся PARTIAL. QIL-035/QIL-036 не реализуются в этом этапе.

## Серверные гарантии

- `GET /api/v1/completion-progress/` выдаёт только собственные публичные агрегаты по всем Published Topic. Одна PostgreSQL-команда получает согласованные публикацию, результаты и generation; GET не создаёт состояние. Старый GET Progress и Result/PracticeResult не расширяются. Количество компонентов выводится из одного test и practice/null, без полей counts.
- Формула: 30 за Read и 70 поровну за успешные опубликованные activity; без Practice 30/70, с ней 30/35/35. M=0 даёт только 30×Read. Среднее Published вычисляется до ROUND_HALF_UP до двух знаков. Mastery отдельно использует Read и точный порог 80% лучшей сохранённой submitted Attempt.
- Practice passed означает любой сохранённый correct текущей опубликованной Task. Удаление последнего correct может снизить completion, но не mastery. Изменение текста не пересчитывает snapshot-результаты.
- Все учебные POST требуют session/CSRF и `X-Progress-Generation`. В atomic сначала блокируется текущий User, затем проверяются owned ресурс, generation и payload. Невалидный header даёт 400, stale create/read — 409 progress_reset, удалённая/чужая работа — 404 до тела/header.
- `POST /api/v1/progress/reset/` требует ровно confirmation/request_id из SPEC. Удаляет только собственные Read/Attempt/PracticeSubmission во всех состояниях, включая Draft; аккаунт, session, контент и чужие записи сохранены. Увеличение generation и последняя квитанция входят в ту же транзакцию. Ошибка/overflow откатывает всё, включая удаление.
- Повтор последнего UUID с исходным generation возвращает прежний успех, не удаляя новую работу. Другой generation того же UUID даёт reset_request_conflict. Квитанция не является бессрочным журналом reset.

## Совместимость клиента

Типы и runtime decoders используют точный JSON SPEC. Generation хранится в памяти; существующие POST получают его из нового GET. Устаревшая запись не повторяется автоматически с новым header. Поздний приватный ответ отбрасывается и при задержанном чтении HTTP body.

Reset, неопределённый сетевой исход reset или межвкладочный сигнал блокируют старые записи. BroadcastChannel передаёт только сигнал, без идентификаторов, ответов и cookies. Общий экземпляр клиента перезагружает `/progress`: это удаляет старые draft/confirmed/cache и DOM end-marker без рефакторинга UI. Новое чтение возможно после явного открытия материала. API reset принимает исходный generation явно для безопасного транспортного повтора. Storage и автоматический replay не используются.

## Проверки и ограничения

Новые проверки: точная формула/M=0/округление; PostgreSQL constraints и additive migration с сохранением данных; единый read-only снимок; ownership; 400/403/404/409/500, CSRF; rollback; reset receipt; конкурентный reset со всеми шестью прежними записями; оба порядка User-mutex на Read; сохранность чужих данных. Frontend unit проверяют DTO/header, single-flight metadata, stale GET/POST, исходный UUID/generation и безопасный межвкладочный сигнал. Реальный Playwright на desktop/mobile проверяет две вкладки, удержанный Read POST, reset API, очистку старой попытки и новое явное чтение с generation=2.

Локально PASS: полный backend/HTTPX — 404 теста и 22 подтеста; frontend unit — 231; type-check/build; полный Chromium — 105; Firefox/WebKit critical — по 20. Django checks, makemigrations --check, migrate --check и pip check — PASS. Новая миграция применялась только во временной БД, проверены её ограничения и сохранность старых записей. Cleanup временных БД/принадлежащих harness процессов подтверждён проверками fixtures. Markdown/внутренние ссылки, diff и scan секретов проверяются перед commit; CI точного SHA фиксируется отдельно в отчёте публикации, без подмены локальным результатом.

Полноценная пользовательская приёмка новых процентов/reset UI ещё NOT_RUN, поскольку визуальная часть исключена текущим заданием. Существующий Playwright suite проверяет совместимость прежних экранов; две новые параметризованные проверки добавлены к browser critical path.

Все миграции и reset при разработке выполняются только в новых временных PostgreSQL-БД тестового harness. Dev-БД не мигрируется и её прогресс не сбрасывается этим прогоном; `.env`, зависимости и семь пользовательских untracked-скриптов сохраняются. Для повторения полной проверки с доступной локальной PostgreSQL можно использовать существующий `tools/check_practice_backend.py`; он создаёт и очищает только свои временные БД/процессы. Браузерные прогоны используют уже установленные проектные бинарники.
