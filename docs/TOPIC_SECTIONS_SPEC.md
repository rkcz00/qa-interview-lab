# Разделы Topic и совместимость статьи — QIL-033

Статус: правила утверждены пользователем 23 ноября 2026 года. Модели, migration, endpoints и reader этого документа — **NOT_IMPLEMENTED**, задача QIL-036. Публикация документа не означает появления разделов в текущей БД/API.

Основания: [PRD](PRD.md), [архитектура](ARCHITECTURE.md), [прогресс и test flow](PROGRESS_SPEC.md), [QA](QA_STRATEGY.md), [backlog](BACKLOG.md). Стек, sessions/CSRF и snapshot Attempt/Practice сохраняются.

## 1. Состав темы

Одна Topic содержит упорядоченные разделы одной составной статьи, один общий словарь, один тест Question/Choice и максимум одну PracticeTask через TopicPractice. Несколько тестов/практик на раздел, вложенность глав, Markdown/HTML-редактор и загрузка файлов не входят в объём. Язык reader и словаря общий; язык теста независим; UI русский.

| Модель | Поля | Ограничения |
| --- | --- | --- |
| TopicSection | id, topic, position, status, created_at, updated_at | BigAutoField; FK Topic CASCADE; position >=1; status draft/published, default draft; UNIQUE(topic, position) |
| TopicSectionTranslation | id, section, language, title, article_body | FK Section CASCADE; language ru/en; UNIQUE(section, language); текст не NULL, пустота разрешена в Draft |

Все даты timezone-aware UTC; PK в API — строки положительных целых. Родитель section.topic и translation.section после создания неизменяем. Позиции общие для RU/EN, могут иметь промежутки; порядок position, затем id. UNIQUE позиции проверяется отложенно в конце транзакции, чтобы атомарно переставлять разделы. Изменение позиции не создаёт новые section IDs.

TopicTranslation сохраняет title темы RU/EN. После миграции источником article_body являются только разделы; прежнее поле TopicTranslation.article_body временно сохраняется read-only как legacy-копия для безопасного перехода, не редактируется параллельно и не участвует в сборке нового ответа.

## 2. Публикация и конкуренция

Topic создаётся Draft. Published Topic требует title RU/EN, минимум один Published TopicSection, прежние полный словарь и валидный тест. Каждый Published-раздел требует непустые title/article_body RU/EN; пробельная строка пуста. Draft-раздел может быть неполным и не попадает в learner responses, оглавление, сборку Article или end-marker. Неполный Draft-раздел не блокирует публикацию остального допустимого дерева. Published-раздел родительской Draft Topic learner недоступен.

Все изменения разделов, переводов, порядка и статуса выполняются через существующую транзакционную запись дерева Topic: блокировка Topic + expected_revision. Любое изменение увеличивает Topic.revision. Правка Published разрешена, если итоговое дерево полно. Нельзя снять/удалить последний Published-раздел у Published Topic без одновременного перевода самой Topic в Draft. Для массового действия проверяются ревизии всех затронутых тем в стабильном порядке и применяется полный rollback.

Ошибки Admin сохраняют точные статусы: 409 edit_conflict для устаревшей ревизии; 400 incomplete_content для публикации/правки, нарушающей полноту. Первое успешное изменение не теряется. В learner API revision/expected_revision не передаются. Content Admin получает стандартные view/add/change/delete на две новые модели, итого 13 контентных моделей (8 базовых + 3 Practice + 2 sections). Прав на User, Group, Attempt, TopicProgress, PracticeSubmission или техническое UserProgressState нет.

## 3. Точные learner-маршруты

| Метод/путь | Успех | Правила |
| --- | --- | --- |
| GET /api/v1/topics/{topic_id}/sections/ | 200, SectionsArticle | Все Published-разделы в едином reader |
| GET /api/v1/topics/{topic_id}/ | 200, прежний Article | Сборка article_body по разделам; прежние четыре поля |
| POST /api/v1/topics/{topic_id}/read/ | 200, прежний Progress | Прежнее тело {}; CSRF + X-Progress-Generation по PROGRESS_SPEC |

GET принимает только один language=ru|en, default ru. Пустой/повторный/неизвестный query → 400 validation_error; без session → 403 authentication_required. Невалидный/неизвестный ID и Draft Topic → одинаковый 404 not_found. Нет fallback на другой язык. GET ничего не записывает, ответы no-store. Непредусмотренный метод → 405 method_not_allowed. Неожиданная ошибка целостности Published-контента → безопасный 500 internal_error, без выдачи частичной статьи или fallback Draft; domain validation обязана предотвращать её при записи.

SectionsArticle имеет ровно topic_id, title, language, sections. Элемент sections имеет ровно section_id, position, title, article_body; language наследуется от envelope. Позиция — JSON integer, ID — строка. Пример только синтетических публичных текстов:

```json
{
  "data": {
    "topic_id": "12",
    "title": "Учебная тема",
    "language": "ru",
    "sections": [
      {"section_id": "101", "position": 10, "title": "Раздел A", "article_body": "Текст A."},
      {"section_id": "102", "position": 20, "title": "Раздел B", "article_body": "Текст B."}
    ]
  }
}
```

Один GET возвращает согласованный снимок всех Published-разделов выбранного языка. status Draft-разделов, внутренние revision, правильные ответы, keys и snapshots отсутствуют. Отдельных section-detail и section-read endpoints в этом инкременте нет.

### 3.1. Старый Article GET

Путь, language и форма сохраняются: data содержит ровно topic_id, title, language, article_body. Поля sections и revision в старый DTO не добавляются, чтобы не нарушать строгие runtime decoders.

- При одном Published-разделе article_body равен его тексту **дословно**, без заголовка и trim.
- При двух и более для каждого раздела берётся `title + "\n\n" + article_body`; блоки соединяются ровно `"\n\n"` в порядке position/id.
- Используется только запрошенный язык и Published-разделы; HTML/Markdown не интерпретируется.

Для примера выше прежний endpoint возвращает:

```json
{"data": {"topic_id": "12", "title": "Учебная тема", "language": "ru", "article_body": "Раздел A\n\nТекст A.\n\nРаздел B\n\nТекст B."}}
```

Catalog/Terms/Result DTO не расширяются. Term остаётся привязанным к Topic, а не к отдельной секции. Новая обязательность generation в POST read — отдельно согласованное изменение mutating-протокола, а не изменение Article GET.

## 4. Reader и Read

Reader остаётся на `/topics/{topic_id}?language=ru|en`; оглавление использует безопасные внутренние якоря `#section-{section_id}`. Все Published-разделы отображаются последовательно на одной странице. Прямой URL, reload и Back/Forward сохраняют язык/якорь; новые разделы не создают отдельную Topic или языковой прогресс.

End-marker располагается после последнего отображённого Published-раздела. Автопрочтение разрешено, только когда весь ответ успешно загружен/отображён, его актуальный marker ненулевой, CSS-видимый и полностью пересекает viewport активной вкладки. Loading, ошибка/частичная загрузка, hidden, stale marker, 0x0 и фоновые события не создают Read. RU/EN, повторный scroll и reload не запускают второй in-flight POST и не меняют первую дату; правила предыдущих исправлений автопрочтения сохраняются.

До конца последнего раздела весь article-компонент даёт 0; после подтверждённого Read — 30. Просмотр словаря не учитывается. Это фиксация достижения конца, не доказательство последовательного чтения каждого абзаца. Отдельные пользовательские SectionRead, частичный процент статьи и раздельные страницы не добавляются.

Первый article_read_at и mastery сохраняются при миграции, edit/reorder/добавлении раздела и unpublish. Новая редакция не сбрасывает Read и не требует новой отметки для прежних читателей. Для ранее не читавшего пользователя применяется текущий набор Published-разделов. Только явный reset из PROGRESS_SPEC удаляет Read; stale end-marker после reset не должен автоматически восстановить его. Изменение публикации Topic может изменить общий процент через состав каталога, но не удаляет историю/освоение.

## 5. Неразрушительная миграция

QIL-036 добавляет таблицы и копирует прежний текст, без удаления/переименования Topic, User, Attempt, PracticeSubmission и TopicProgress:

1. На каждую существующую Topic создаётся один TopicSection с position=10 и тем же статусом.
2. Каждый существующий TopicTranslation копируется в перевод раздела: language, title и article_body без изменения символов. У Draft сохраняется существующая неполнота, отсутствующие переводы не сочиняются. Published до миграции обязан иметь полный RU/EN.
3. Проверяются counts, FK, полнота Published и дословная идентичность Article GET для единственного раздела.
4. Topic IDs, первые Read-даты, результаты/ответы/snapshots и пользовательские связи не меняются. Прежнее поле тела пока не удаляется; последующее удаление требует отдельной миграции и согласования.

Не запускается loader/seed и не обновляется демо JSON. Демо-тема остаётся отдельной с прежним ID/текстами. Это план будущей миграции; в QIL-033 она не создаётся и не применяется.

## 6. Приёмка и отложенные возможности

SEC-01–SEC-08 в [QA-стратегии](QA_STRATEGY.md) покрывают constraints/RU/EN, атомарную публикацию и optimistic conflict, скрытие Draft, две формы API, дословную legacy-совместимость, миграцию и сохранность Read/snapshots, marker после последнего раздела, desktop/mobile и языки. Практика и оценивание Attempt остаются по своим snapshot.

Будущее отдельное решение: обязательное чтение каждого раздела, частичный article_progress, разделы на отдельных страницах, новый Read при редактуре, тесты по разделам. Наличие структуры sections само по себе эти функции не включает. Следующая интеграционная приёмка QIL-037 зависит от QIL-034–QIL-036 и не запускается из документационной задачи.
