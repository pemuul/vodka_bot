# ТЗ: Настройки авто-валидации и правил проверки чеков на уровне акции

> Документ подготовлен на основе анализа реального кода проекта VodkaBot (состояние на 2026-07-06).
> Все пути, функции, таблицы, роуты и номера строк проверены по коду. Номера строк могут
> немного сдвинуться при правках — ориентируйся на имена функций.

---

## 1. Назначение документа

Документ описывает реализацию двух доработок:

1. **Авто-валидация на уровне акции** — флаг `auto_validation_enabled` у каждой акции
   (в проекте акции называются «розыгрыши», таблица `prize_draws`). Если флаг выключен,
   чек принимается и сохраняется, но НЕ ставится в очередь автоматической проверки
   (`receipt_ocr_queue`) и ждёт ручной проверки в существующей админке.

2. **Правила проверки чеков на уровне акции** — таблица правил `prize_draw_rules`
   (название товара, SKU, алиасы, минимальное количество, активность). Авто-проверка
   чека использует правила конкретной акции вместо глобальных ключевых слов;
   глобальные ключевые слова остаются как fallback для акций без правил.

Документ рассчитан на то, что реализация выполняется **без повторного глубокого анализа
проекта** — все точки входа уже найдены и перечислены ниже.

---

## 2. Краткая карта текущей архитектуры

Терминология: «акция» = «розыгрыш» = запись в таблице `prize_draws`.

| Область | Файл / функция / таблица | Что там сейчас |
|---|---|---|
| Таблица акций | `table_shem.json` строка 25, таблица `prize_draws` | `id, title, start_date, end_date, status ('upcoming'/'active'/'finished'), create_dt`. Поля авто-валидации **нет** |
| Схема всех таблиц БД | `table_shem.json` | Единственный источник DDL. Миграция: `sql_mgt.create_db()` → `create_or_update_tables()` (строка 177) → `update_table()` (строка 139) добавляет новые колонки через `ALTER TABLE ... ADD COLUMN` автоматически при старте бота/воркера |
| Определение активной акции | `sql_mgt.get_active_draw_id()` (sql_mgt.py:1216) | `SELECT id FROM prize_draws WHERE status='active' AND start_date<=today AND end_date>=today LIMIT 1` |
| Включение режима приёма чеков | `heandlers/menu.py:275-286` | При нажатии узла меню с `item_id == 'check'` ставится параметр `GET_CHECK=True` (только если есть активная акция) |
| Создание чека | `heandlers/media_heandler.py` → `set_photo()` (строки 888-932) | Скачивает фото, сохраняет в `site_bot/static/uploads/`, `draw_id = get_active_draw_id()` (стр. 906), `sql_mgt.add_receipt(..., "В авто обработке", draw_id=draw_id)` (стр. 907-913) |
| Привязка чека к акции | там же, `add_receipt(draw_id=...)` (sql_mgt.py:1229) | Колонка `receipts.draw_id` уже существует (table_shem.json:30) |
| Постановка в авто-очередь | `heandlers/media_heandler.py:914` → `sql_mgt.enqueue_receipt_ocr(receipt_id)` (sql_mgt.py:1268) | **Единственное место** постановки чека в очередь. Вставка в `receipt_ocr_queue` со status='pending' |
| Воркер очереди | `receipt_queue_worker.py` → `_process_queue()` (строки 229-294) | Берёт задачу через `acquire_next_receipt_for_ocr()` (sql_mgt.py:1288), вызывает `media_heandler.process_receipt()`, помечает complete/failed |
| Авто-пайплайн QR/FNS/OCR | `heandlers/media_heandler.py` → `process_receipt()` (строки 734-885) | QR: `_detect_qr()` (стр. 353); дубликат: `find_receipt_by_qr()` (стр. 761-776); ФНС: `_check_vodka_in_receipt()` (стр. 678-731); OCR fallback: `_check_keywords_with_ocr()` (стр. 386-426) → subprocess `_ocr_worker_job()` (стр. 229-272) |
| ФНС-клиент | `fns_api.py` → `get_receipt_by_qr()` (строка 263) | SOAP API ФНС, возвращает `(ticket_dict | None, error_text | None)` |
| Товарные позиции ФНС | `media_heandler._check_vodka_in_receipt()` строки 708-725 | items берутся из `data["items"]` / `data["content"]["items"]` / `data["document"]["receipt"]["items"]`. Сейчас только **логируются** (`_format_receipt_items()`, стр. 638-664), в БД **не сохраняются** |
| Глобальные ключевые слова | таблица `params`, ключ `(user_tg_id=0, param_name='product_keywords')`, значение через `;` | Чтение: `sql_mgt.get_param(0, 'product_keywords')` (media_heandler.py:736-737). Редактирование: `site_bot/main.py` GET/POST `/settings` (строки 1593-1660), шаблон `site_bot/templates/settings.html` (поле `product_names`) |
| Проверка по ключевым словам (ФНС) | media_heandler.py:727-731 | `any(k in item_name.casefold() for k in keywords)` — подстрока в названии позиции |
| Проверка по ключевым словам (OCR) | media_heandler.py:267-268 (`_ocr_worker_job`) | `any(k in text.casefold() for k in keywords)` — подстрока во всём тексте чека |
| Обновление статуса чека | `sql_mgt.update_receipt_status()` (sql_mgt.py:1380) | Статус + комментарий `"Бот: ..."`. Вызывается из `process_receipt()` (media_heandler.py:877) |
| Статусы чеков (реально используемые) | media_heandler.py, receipts.html:144-150 | `"В авто обработке"`, `"Подтверждён"`, `"Чек уже загружен"`, `"Нет товара в чеке"`, `"Ошибка"`. В DDL default `'не подтвержден'` (ботом не используется), legacy `"Распознан"` встречается в фильтре победителей |
| Ручная проверка чеков (уже есть) | `site_bot/main.py` POST `/api/receipts/{receipt_id}` → `update_receipt()` (строки 1962-2031) | Админ меняет статус/акцию/комментарий в модалке на странице `/receipts`; при смене статуса пользователю уходит "✅ Чек подтверждён" / "❌ В чеке не найден нужный товар" (стр. 2002-2013) |
| Уведомления админа о проблемных чеках | `site_bot/main.py` GET `/api/notifications` (строки 873-922) | Показывает чеки со `status == "Ошибка"` и `comment LIKE 'Бот:%'` |
| Выбор победителей | `site_bot/main.py` → `api_determine_winners()` (строка 729) | Кандидаты: чеки с `draw_id == draw акции` и `status IN ("Подтверждён", "Распознан")` (строки 751, 761). **Каждый чек — отдельный лотерейный билет** |
| Админка акций | `site_bot/main.py`: GET `/prize-draws` (476-583), POST `/prize-draws` → `save_draw()` (602-692), DELETE `/prize-draws/{draw_id}` (695-722); Pydantic-модели `StageIn` (585), `DrawIn` (594) | Сохранение по принципу «полная перезапись»: этапы удаляются и вставляются заново (стр. 643-690) |
| Шаблон акций | `site_bot/templates/prize_draws.html` | Bootstrap-модалка редактирования (строки 39-97): поля title/start/end/status (48-76). JS: `openDrawModal()` (165-181), `btn-new-draw` (354-366), `btn-save-draw` (417-461) собирает `currentDraw` и POST-ит JSON на `/prize-draws` |
| Шаблон чеков | `site_bot/templates/receipts.html` | Список + модалка просмотра. `allowedStatuses` (строки 144-150), select статуса (100-108), сохранение `save-receipt` (336-361) |
| SQLAlchemy-таблицы админки | `site_bot/main.py:270-272, 355` | `Table("prize_draws", metadata, autoload_with=engine)` — схема считывается **при импорте**. После миграции БД нужен перезапуск процесса сайта. Паттерн опциональных колонок: `HAS_PDW_RECEIPT_ID` (стр. 354), `has_receipt_draw_id()` (стр. 368-370) |
| Тесты | `tests/` (`conftest.py`, `test_sql_mgt.py`, `test_fns_api.py`, ...) | Фикстура `tmp_db` (conftest.py:24-44) создаёт SQLite из `table_shem.json` — новые таблицы попадут в тестовую БД автоматически |

---

## 3. Бизнес-правила реализации

1. Авто-валидация настраивается **отдельно для каждой акции** (checkbox в админке акции).
2. Значение по умолчанию — **включена** (`1`): старые и новые акции без явной настройки работают как сейчас.
3. Если авто-валидация выключена: чек принимается, сохраняется, привязывается к акции, **не ставится** в `receipt_ocr_queue`, получает статус для ручной проверки. Пользователю уходит существующее сообщение «Чек загружен и находится в статусе Проверка…».
4. Каждый чек — отдельная единица участия в акции (так уже работает `api_determine_winners`). Агрегация покупок пользователя по нескольким чекам НЕ делается.
5. Один пользователь может загрузить много чеков — ничего в этом не менять.
6. Правила проверки (алиасы, min_quantity) берутся из конкретной акции (`receipts.draw_id` → `prize_draw_rules.draw_id`).
7. Проверка количества надёжна **только** по items из ФНС. OCR — fallback только по наличию алиасов в тексте.
8. Если у акции нет активных правил — используется старое поведение: глобальные `product_keywords` и текущая логика статусов (обратная совместимость).
9. Принцип безопасности: **при любом сомнении чек НЕ подтверждается автоматически и остаётся на ручной проверке**. Лучше лишний раз показать чек админу, чем ошибочно засчитать.
10. Ручная проверка уже существует (страница `/receipts`, `update_receipt()`) — новую систему модерации не строить, использовать её.
11. Старые акции и старые чеки не должны сломаться; никакие существующие статусы не переименовывать.

---

## 4. Реализация настройки авто-валидации акции

### 4.1. Что добавить в БД

Таблица акций называется **`prize_draws`** (не «actions»). Boolean-поля в проекте задаются
как `BOOLEAN DEFAULT TRUE/FALSE` или числом (примеры: `item.activ BOOLEAN DEFAULT TRUE`,
`participant_settings.blocked BOOLEAN DEFAULT FALSE` в `table_shem.json`). SQLite хранит их как 0/1.

Изменение — в `table_shem.json`, строка 25, в DDL-строку `prize_draws` добавить колонку:

```text
auto_validation_enabled BOOLEAN DEFAULT 1
```

Итоговая строка:

```json
"prize_draws": "prize_draws (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, start_date DATE NOT NULL, end_date DATE NOT NULL, status TEXT NOT NULL, auto_validation_enabled BOOLEAN DEFAULT 1, create_dt TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
```

Почему `DEFAULT 1`: при `ALTER TABLE ... ADD COLUMN` (который выполнит `sql_mgt.update_table()`
автоматически) все существующие акции получат значение `1` — текущее поведение сохранится.

**SQL руками не писать.** Миграция локально: `python receipt_queue_worker.py --migrate`
(или просто запуск бота). Проверить, что `sql_mgt._parse_table_schema()` корректно парсит
новую колонку — есть тесты в `tests/test_sql_mgt.py`.

Правило чтения флага: авто-валидация считается выключенной **только если значение равно 0/False**.
`NULL`/отсутствие колонки/отсутствие акции → считается включённой (безопасный default).

### 4.2. Что изменить в админке (`site_bot/`)

1. **Pydantic-модель** `DrawIn` (site_bot/main.py:594) — добавить поле:
   ```python
   auto_validation_enabled: bool = True
   ```

2. **Роут чтения** GET `/prize-draws` → функция `prize_draws()` (main.py:476-583):
   - добавить `prize_draws_table.c.auto_validation_enabled` в `draw_query` (стр. 478-484);
   - в словарь `draws.append({...})` (стр. 572-579) добавить
     `"auto_validation_enabled": bool(d["auto_validation_enabled"]) if d["auto_validation_enabled"] is not None else True`.

3. **Роут сохранения** POST `/prize-draws` → `save_draw()` (main.py:602-692) — это и создание
   (insert, стр. 621-629), и редактирование (update, стр. 630-641). В оба `.values(...)`
   добавить `auto_validation_enabled=draw.auto_validation_enabled`.
   Для устойчивости к запуску сайта на немигрированной БД используй существующий паттерн
   опциональных колонок (как `HAS_PDW_RECEIPT_ID`, main.py:354):
   ```python
   HAS_DRAW_AUTO_VALIDATION = 'auto_validation_enabled' in prize_draws_table.c
   ```
   и добавлять поле в values только если `HAS_DRAW_AUTO_VALIDATION`.

4. **Шаблон** `site_bot/templates/prize_draws.html`:
   - в блок основных полей модалки (строки 48-76, ряд `row g-3`) добавить checkbox:
     ```html
     <div class="col-md-2">
       <div class="form-check mt-4">
         <input type="checkbox" id="edit-draw-auto-validation" class="form-check-input" checked />
         <label for="edit-draw-auto-validation" class="form-check-label">Авто-валидация чеков</label>
       </div>
     </div>
     ```
   - JS `openDrawModal()` (стр. 165-181): `document.getElementById("edit-draw-auto-validation").checked = currentDraw.auto_validation_enabled !== false;`
   - JS `btn-new-draw` (стр. 354-366): выставить checkbox в `true`, в объект `currentDraw` добавить `auto_validation_enabled: true`;
   - JS `btn-save-draw` (стр. 417-461): перед POST добавить
     `currentDraw.auto_validation_enabled = document.getElementById("edit-draw-auto-validation").checked;`
   - кнопка «Копировать розыгрыш» (стр. 369-414) клонирует `currentDraw` через JSON — поле скопируется само, менять не нужно.

5. **Перезапуск**: `prize_draws_table` автозагружается при импорте main.py (стр. 270) —
   локально после миграции перезапустить процесс сайта, иначе колонка не будет видна.

### 4.3. Что изменить в pipeline загрузки чека

Точное место — `heandlers/media_heandler.py`, функция `set_photo()`:

- строка 906: `draw_id = await sql_mgt.get_active_draw_id()`
- строки 907-913: `receipt_id = await sql_mgt.add_receipt(web_path, message.chat.id, "В авто обработке", message_id=..., draw_id=draw_id)`
- строка 914: `await sql_mgt.enqueue_receipt_ocr(receipt_id)` ← **единственная точка постановки в очередь**

Новая логика:

```text
Пользователь отправил чек (set_photo, F.photo, GET_CHECK == True)
→ draw_id = get_active_draw_id()
→ auto_validation = await sql_mgt.get_draw_auto_validation(draw_id)   # новая DAL-функция

если auto_validation == True (или draw_id is None):
    receipt_id = add_receipt(..., status="В авто обработке", draw_id=draw_id)
    enqueue_receipt_ocr(receipt_id)          # текущий flow без изменений

если auto_validation == False:
    receipt_id = add_receipt(..., status="На ручной проверке", draw_id=draw_id)
    # enqueue_receipt_ocr НЕ вызывать
    # сообщение пользователю то же самое (строки 915-917): «Чек загружен и находится
    # в статусе Проверка...» — менять не нужно
```

**Новая DAL-функция** в `sql_mgt.py` (рядом с `get_active_draw_id`, стр. 1216):

```python
@with_connection
async def get_draw_auto_validation(draw_id: int | None, conn=None) -> bool:
    """True, если у акции включена авто-валидация. Безопасный default — True."""
    if draw_id is None:
        return True
    schema = await get_table_info(conn, "prize_draws")
    if "auto_validation_enabled" not in schema:
        return True
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT auto_validation_enabled FROM prize_draws WHERE id = ?", (draw_id,)
    )
    row = await cursor.fetchone()
    if row is None or row[0] is None:
        return True
    return bool(row[0])
```

**Новый статус чека — `"На ручной проверке"`.** Почему нужен новый, а не существующий:
- `"В авто обработке"` означает «воркер скоро обработает» — вводил бы админа в заблуждение;
- `"Ошибка"` означает сбой авто-пайплайна и попадает в уведомления `/api/notifications`;
- `'не подтвержден'` (DDL-default) ботом не используется и отсутствует в UI-списке статусов.

Новый статус нужно добавить в массив `allowedStatuses` в `site_bot/templates/receipts.html`
(строки 144-150) — тогда он появится и в select статуса модалки, и в фильтре списка.
Функция `ensureStatusOption()` (стр. 167-177) уже умеет показывать неизвестные статусы,
но для выбора руками статус должен быть в `allowedStatuses`.

Опционально (дёшево, полезно): в GET `/api/notifications` (main.py:873-922) добавить выборку
чеков со статусом `"На ручной проверке"`, чтобы админ видел их в колокольчике. Не обязательно
для готовности задачи.

Опциональная защита (не обязательно): в начале `process_receipt()` (media_heandler.py:734)
можно проверять `get_draw_auto_validation(receipt.draw_id)` и, если выключена, ставить статус
`"На ручной проверке"` и выходить — защищает от «зависших» задач в очереди, созданных до деплоя.

### 4.4. Чекбокс реализации

* [ ] Найти таблицу акций → `prize_draws` (table_shem.json:25) — найдена, см. выше
* [ ] Добавить поле `auto_validation_enabled BOOLEAN DEFAULT 1` в DDL `prize_draws` в `table_shem.json`
* [ ] Убедиться, что default = 1 (старые акции получают «включено»)
* [ ] Добавить checkbox в модалку акции (`prize_draws.html`, блок основных полей)
* [ ] Сохранять checkbox при создании акции (`save_draw()`, insert-ветка)
* [ ] Сохранять checkbox при редактировании акции (`save_draw()`, update-ветка)
* [ ] Добавить `get_draw_auto_validation()` в `sql_mgt.py`
* [ ] Проверять настройку в `set_photo()` перед `enqueue_receipt_ocr()`
* [ ] Добавить статус `"На ручной проверке"` в `allowedStatuses` (`receipts.html`)
* [ ] Не ломать текущий flow: `draw_id is None` / колонки нет / NULL → авто-валидация включена
* [ ] Проверить сценарий: авто-валидация включена → чек в очереди, воркер обработал
* [ ] Проверить сценарий: авто-валидация выключена → записи в `receipt_ocr_queue` нет, статус «На ручной проверке», чек виден и редактируем в `/receipts`

---

## 5. Реализация правил акции по ассортименту/SKU/алиасам/количеству

### 5.1. Структура данных: выбран Вариант B — отдельная таблица `prize_draw_rules`

**Вариант A (JSON-поле `prize_draws.validation_rules_json`)** — отклонён:
- редактирование JSON строкой в модалке неудобно и провоцирует ошибки клиента;
- в админке уже есть паттерн «дочерние сущности акции» (`prize_draw_stages`) с полной
  перезаписью при сохранении — правила ложатся в него без новой архитектуры;
- фильтровать/расширять JSON в SQLite неудобно.

**Вариант B (таблица `prize_draw_rules`)** — принят: повторяет существующий паттерн
`prize_draw_stages` (в БД, в `save_draw()`, в модалке), даёт несколько правил на акцию.

Добавить в `table_shem.json` (рядом с `prize_draw_stages`):

```json
"prize_draw_rules": "prize_draw_rules (id INTEGER PRIMARY KEY AUTOINCREMENT, draw_id INTEGER NOT NULL, title TEXT NOT NULL, sku_code TEXT, aliases TEXT NOT NULL, min_quantity INTEGER DEFAULT 1, is_active BOOLEAN DEFAULT TRUE, create_dt TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
```

- `aliases` — TEXT, варианты написания через `;` (тот же формат, что глобальные
  `product_keywords`, см. `settings.html`: «Введите названия через ;»). Сопоставление —
  подстрока в casefold, та же семантика, что сейчас в media_heandler.py:729.
- `create_dt` — именно `create_dt`, это конвенция проекта (не `created_at`).
- FOREIGN KEY не добавлять — в проекте они не используются, целостность поддерживается кодом
  (как у `prize_draw_stages`).

**DAL-функции** в `sql_mgt.py` (рядом с draw/receipt-функциями):

```python
@with_connection
async def get_draw_rules(draw_id: int, only_active: bool = True, conn=None) -> list[dict]:
    """Правила проверки чеков для акции. Пустой список = правил нет (fallback на keywords)."""
    ...  # SELECT * FROM prize_draw_rules WHERE draw_id = ? (+ AND is_active = 1)
```

### 5.2. Что должно появиться в админке

Блок «Правила проверки чеков» в модалке акции (`prize_draws.html`), под основными полями
(после блока строк 48-76, рядом с кнопками «Добавить этап»). Список строк-правил, у каждой:

| Поле | Ввод | Обязательность |
|---|---|---|
| Название | text | обязательно |
| SKU / код товара | text | опционально |
| Алиасы (через `;`) | text | обязательно |
| Минимальное количество | number, min=1 | default 1 |
| Активно | checkbox | default true |
| Удалить | кнопка | — |

Плюс кнопка «Добавить правило». Пример заполнения:

```text
Название: Финская водка
SKU: finsky-vodka
Алиасы: finsky; фински; финская водка; finsky vodka
Минимальное количество: 1
Активно: да
```

Backend-изменения (`site_bot/main.py`) — по образцу этапов (`stages`):

1. Модель:
   ```python
   class RuleIn(BaseModel):
       id: Optional[int] = None
       title: str
       sku_code: Optional[str] = None
       aliases: str
       min_quantity: int = 1
       is_active: bool = True
   ```
   В `DrawIn` добавить `rules: List[RuleIn] = []`.
2. Autoload таблицы (рядом со стр. 270-272), с защитой на случай немигрированной БД:
   ```python
   try:
       prize_draw_rules_table = Table("prize_draw_rules", metadata, autoload_with=engine)
   except Exception:
       prize_draw_rules_table = None
   ```
3. GET `/prize-draws` (476-583): для каждой акции выбрать правила и положить в
   `draws.append({..., "rules": [...]})`.
4. POST `/prize-draws` `save_draw()` (602-692): после блока этапов — удалить старые правила
   акции (`DELETE WHERE draw_id = new_id`) и вставить новые из `draw.rules`
   (полная перезапись, как со stages, стр. 643-690).
5. DELETE `/prize-draws/{draw_id}` `delete_draw()` (695-722): добавить удаление правил акции.
6. JS в `prize_draws.html`: `openDrawModal()` рендерит `currentDraw.rules`; `btn-new-draw`
   инициализирует `rules: []`; `btn-save-draw` собирает значения инпутов обратно в
   `currentDraw.rules` перед POST. Использовать `<template>` по образцу `tpl-stage-content`.

### 5.3. Как проверять чек (алгоритм авто-пайплайна)

Точка изменения — `media_heandler.process_receipt()` (строки 734-885) и
`_check_vodka_in_receipt()` (строки 678-731).

```text
1.  Пользователь отправляет чек → set_photo().
2.  Определяется активная акция (draw_id), чек создаётся и привязывается.
3.  Проверяется auto_validation_enabled (раздел 4.3).
4.  Если False → статус "На ручной проверке", очередь не используется. КОНЕЦ.
5.  Если True → чек в очереди; воркер вызывает process_receipt(receipt_id):
    a. receipt = await sql_mgt.get_receipt(receipt_id)      # уже есть, возвращает draw_id
    b. rules = await sql_mgt.get_draw_rules(receipt["draw_id"]) if receipt["draw_id"] else []
    c. если rules пуст → keywords = get_param(0, 'product_keywords'), СТАРАЯ логика
       без изменений (статусы "Подтверждён"/"Нет товара в чеке"/"Ошибка" как сейчас).
    d. если rules НЕ пуст → новая логика ниже.
6.  QR найден и ФНС вернула items (_check_vodka_in_receipt):
    - сохранить items в receipt_items (раздел 5.5);
    - для каждого активного правила: matched_qty = сумма quantity позиций, чьё
      casefold-имя содержит любой alias правила;
    - есть правило, где alias найден и matched_qty >= min_quantity
        → статус "Подтверждён", comment "Бот: товар найден по правилу '<title>'
          (кол-во X >= Y)"; пользователю "✅ Чек подтверждён".
    - alias найден, но quantity < min_quantity (или quantity нечисловое при min>1)
        → статус "На ручной проверке", comment "Бот: найден товар по правилу
          '<title>', но количество X < Y — требуется ручная проверка".
          Пользователю ❌ НЕ отправлять (уведомит админ после проверки).
    - ни один alias не найден в items
        → статус "На ручной проверке", comment "Бот: товар по правилам акции не
          найден в данных ФНС — требуется ручная проверка".
7.  QR не найден или ФНС недоступна/ошибка → OCR fallback:
    - в OCR передавать объединённый список алиасов ТОЛЬКО правил с min_quantity == 1
      (существующий контракт _check_keywords_with_ocr(path, keywords) менять не нужно —
      она просто ищет слова в тексте);
    - OCR нашёл alias (значит, правило с min_quantity == 1 выполнено)
        → статус "Подтверждён", comment как сейчас («товар найден через распознавание
          изображения», стр. 826-842);
    - OCR не нашёл / у всех правил min_quantity > 1
        → статус "На ручной проверке", comment "Бот: авто-проверка не смогла
          подтвердить чек (QR/ФНС недоступны, OCR не подтвердил) — требуется
          ручная проверка".
8.  Дубликаты: без изменений — проверка find_receipt_by_qr() (стр. 761-776) выполняется
    ДО всего остального, статус "Чек уже загружен".
9.  Любое исключение пайплайна: как сейчас (mark_receipt_queue_failed → ретрай),
    после исчерпания попыток чек остаётся в невалидированном статусе и виден админу.
```

**Рекомендация по структуре кода** (для тестируемости, БЕЗ дублирования пайплайна):
чистую логику сопоставления вынести в новый маленький модуль `receipt_validation.py`
в корне проекта (рядом с `fns_api.py`):

```python
def parse_aliases(aliases_str: str) -> list[str]          # split(';'), strip, casefold
def match_items_to_rules(items: list[dict], rules: list[dict]) -> MatchResult
    # MatchResult: confirmed: bool, needs_manual: bool, matched_rule_id: int | None, reason: str
def ocr_keywords_for_rules(rules: list[dict]) -> list[str] # алиасы правил с min_quantity == 1
```

Почему отдельный модуль, а не функции внутри `media_heandler.py`: `media_heandler` при
импорте тянет `cv2`, `pyzbar`, `ocr` — unit-тесты чистой логики без этих зависимостей
запускаются только из отдельного модуля. `media_heandler.process_receipt()` просто
вызывает эти функции — сам пайплайн (QR → ФНС → OCR → статус) остаётся один.

### 5.4. Проверка количества — отдельные правила

- Количество проверять **только по items из ФНС** (`item["quantity"]`, см. извлечение
  media_heandler.py:708-718 и `_format_receipt_items` 638-664).
- `min_quantity == 1`: достаточно наличия позиции с совпавшим alias (позиция в чеке = минимум 1 шт.).
- `min_quantity > 1` и `quantity` отсутствует/нечисловое → **ручная проверка** («На ручной проверке»).
- Чек проверяется только через OCR (ФНС недоступна):
  - правила с `min_quantity > 1` через OCR **не подтверждать никогда**;
  - правила с `min_quantity == 1`: OCR нашёл alias → можно подтвердить (текущая бизнес-логика
    это допускает — сейчас OCR-подтверждение уже используется, стр. 826-842).
- Любая неоднозначность (несколько трактовок, нечисловое qty, частичное совпадение) → ручная проверка.

### 5.5. Сохранение товарных позиций из ФНС — таблица `receipt_items`

**Проверено: сейчас items из ФНС НЕ сохраняются** — только логируются
(`logger.info(... _format_receipt_items(items))`, media_heandler.py:720-725). Таблицы
`receipt_items` в `table_shem.json` нет — «не найдено», добавляем минимальную:

```json
"receipt_items": "receipt_items (id INTEGER PRIMARY KEY AUTOINCREMENT, receipt_id INTEGER NOT NULL, raw_name TEXT, quantity REAL, price REAL, sum REAL, matched_rule_id INTEGER, create_dt TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
```

- `quantity REAL` — ФНС может вернуть дробное (весовой товар).
- `price`/`sum` — копейки как приходят из ФНС, без пересчёта (это техданные для отладки).
- `matched_rule_id` — id правила, по которому позиция совпала (NULL, если нет).

DAL в `sql_mgt.py`:

```python
@with_connection
async def save_receipt_items(receipt_id: int, items: list[dict], conn=None) -> None:
    # перед вставкой удалить старые строки этого receipt_id (ретраи воркера!)
@with_connection
async def get_receipt_items(receipt_id: int, conn=None) -> list[dict]: ...
```

Куда встроить сохранение: `_check_vodka_in_receipt()` — **синхронная** функция, выполняется
в executor (media_heandler.py:779-781). Не писать в БД из неё. Вместо этого расширить её
возвращаемое значение — добавить третий элемент `items` (список распарсенных позиций), и
сохранять их в async-контексте `process_receipt()` через `await sql_mgt.save_receipt_items(...)`.

Отображение в админке (быстрое встраивание): в GET `/api/receipts/{receipt_id}`
(site_bot/main.py:1914) добавить в ответ ключ `items` (выборка из `receipt_items`), а в
модалку `receipts.html` (список `list-group`, строки 91-117) — пункт «Товары из ФНС»
со списком `raw_name × quantity` и пометкой совпавшего правила. Это сильно помогает
ручной проверке. Если таблицы нет (немигрированная БД) — возвращать пустой список.

Аналитику продаж НЕ строить — это техническая таблица для прозрачности проверки.

### 5.6. Чекбокс реализации

* [ ] Найти текущую проверку keywords → media_heandler.py:727-731 (ФНС) и 267-268 (OCR) — найдена
* [ ] Найти место, где FNS возвращает items → `_check_vodka_in_receipt()`, стр. 708-718 — найдено
* [ ] Проверить, сохраняются ли FNS items → НЕ сохраняются, только лог (стр. 720-725)
* [ ] Добавить таблицу `prize_draw_rules` в `table_shem.json`
* [ ] Добавить таблицу `receipt_items` в `table_shem.json`
* [ ] Добавить блок правил в модалку акции (`prize_draws.html`) + `RuleIn`/`DrawIn.rules`
* [ ] Сохранение правил в `save_draw()` (полная перезапись, как stages), удаление в `delete_draw()`
* [ ] Поле алиасов (через `;`) и `min_quantity` в форме правила
* [ ] `sql_mgt.get_draw_rules(draw_id)` — получение правил по draw_id
* [ ] Новый модуль `receipt_validation.py` с чистыми функциями сопоставления
* [ ] В `process_receipt()`: правила акции вместо глобальных keywords, если правила есть
* [ ] Fallback на глобальные `product_keywords`, если правил нет — старое поведение бит-в-бит
* [ ] Проверка `item.name` по aliases (casefold, подстрока — как текущая семантика)
* [ ] Проверка `quantity` по `min_quantity` (только ФНС; суммирование по совпавшим позициям)
* [ ] OCR fallback: только алиасы правил с `min_quantity == 1`
* [ ] Никогда не подтверждать `min_quantity > 1` через OCR
* [ ] `save_receipt_items()` + вызов из `process_receipt()` (с очисткой перед повторной вставкой)
* [ ] Показ `receipt_items` в модалке чека (`/api/receipts/{id}` + `receipts.html`)
* [ ] Проверить: после неуспешной авто-проверки статус меняется руками через POST `/api/receipts/{id}` и пользователь получает уведомление (существующий код, стр. 2002-2013)

---

## 6. Новый pipeline проверки чека

### Было

```text
Пользователь отправляет чек (set_photo)
→ draw_id = get_active_draw_id()
→ add_receipt(status="В авто обработке", draw_id)
→ enqueue_receipt_ocr(receipt_id)                     # всегда
→ receipt_queue_worker._process_queue → media_heandler.process_receipt
→ _detect_qr → find_receipt_by_qr (дубликат?) → _check_vodka_in_receipt (ФНС)
→ проверка по ГЛОБАЛЬНЫМ product_keywords (params, user_tg_id=0)
→ OCR fallback (_check_keywords_with_ocr) по тем же keywords
→ update_receipt_status: "Подтверждён" / "Чек уже загружен" / "Нет товара в чеке" / "Ошибка"
→ сообщение пользователю (✅/❌)
```

### Должно стать

```text
Пользователь отправляет чек (set_photo)
→ draw_id = get_active_draw_id()
→ читается get_draw_auto_validation(draw_id)

если auto_validation_enabled == False:
    add_receipt(status="На ручной проверке", draw_id)
    очередь НЕ используется; админ проверяет руками на /receipts (существующий UI)

если auto_validation_enabled == True:
    add_receipt(status="В авто обработке", draw_id) + enqueue_receipt_ocr — как сейчас
    воркер → process_receipt:
        rules = get_draw_rules(receipt.draw_id)
        если rules пуст:
            СТАРЫЙ flow с глобальными product_keywords, без изменений
        если rules есть:
            ФНС items → сохранить в receipt_items → сопоставить aliases + min_quantity:
                выполнено       → "Подтверждён" (+ ✅ пользователю)
                не выполнено /
                сомнение        → "На ручной проверке" (без ❌ пользователю)
            ФНС недоступна → OCR по алиасам правил с min_quantity == 1:
                найдено   → "Подтверждён"
                не найдено → "На ручной проверке"
    дубликат QR → "Чек уже загружен" (без изменений, проверяется первым)
```

---

## 7. Правила для реализационной нейросети

- Не переписывать проект с нуля; не менять стек (aiogram 3, FastAPI, databases, SQLite, Jinja2).
- Не переносить SQLite на PostgreSQL.
- Не переписывать админку — расширять существующие роуты и шаблоны.
- Не переписывать OCR/FNS pipeline — точечные правки `process_receipt()` и `_check_vodka_in_receipt()`.
- Не создавать новую систему ручной модерации — есть `/receipts` + POST `/api/receipts/{id}`.
- Не создавать дублирующий pipeline проверки чеков: пайплайн один — `process_receipt()`.
- Расширять существующие функции, если они подходят; новые функции — только перечисленные в этом ТЗ.
- Сначала открыть места, указанные в разделах 2 и 14, потом менять. Не искать заново то, что уже найдено здесь.
- Не делать одну задачу двумя способами (например, и JSON-поле, и таблицу правил — только таблицу).
- Обратная совместимость: старые акции без настройки → авто-валидация включена; акции без правил → глобальные keywords.
- Новые поля/таблицы — только с безопасными default (`auto_validation_enabled DEFAULT 1`, `min_quantity DEFAULT 1`, `is_active DEFAULT TRUE`).
- Глобальные `product_keywords` НЕ удалять и страницу `/settings` не трогать.
- Если авто-валидация выключена — чек вообще не должен попадать в `receipt_ocr_queue` (проверяется отсутствием записи в таблице).
- Если ФНС не дала quantity — правило с min_quantity > 1 автоматически не подтверждать.
- Если OCR нашёл слово, но правило требует min_quantity > 1 — «На ручной проверке».
- Любое сомнение → «На ручной проверке», не подтверждать.
- Схему БД менять ТОЛЬКО через `table_shem.json` (миграция автоматическая), SQL руками не писать.
- После каждого крупного шага прогонять `python -m pytest tests/ -v` и минимальный ручной сценарий.
- Не уходить в рефакторинг ради красоты (не трогать неймспейсы `heandlers`, опечатки в именах и т.п.).
- Не тратить токены на повторный анализ файлов — использовать карту из раздела 2 и таблицу из раздела 14.

---

## 8. Запрет на самостоятельный деплой / push на production

Реализационная нейросеть **НЕ должна** самостоятельно выкатывать изменения на продовый
сервер (production: 217.198.6.100 / finskyice.com, `/home/VodkaBot`, supervisor-процессы
`vodka_bot`, `vodka_site`, `vodka_bot_check`; БОЕВАЯ БД `/home/VodkaBot/tg_base.sqlite`).

**Запрещено без прямой команды владельца проекта:**

- делать `git push` в production-ветку (`main` репозитория `pemuul/vodka_bot`);
- деплоить изменения на боевой сервер (в т.ч. `git pull` на сервере);
- перезапускать production-процессы;
- менять production-БД (`tg_base.sqlite` на сервере);
- запускать миграции на production (включая `receipt_queue_worker.py --migrate`);
- править файлы напрямую на production-сервере;
- выполнять команды `supervisor`, `supervisorctl`, `systemctl` на production;
- менять nginx-конфиги;
- менять `.env`, токены, ключи, настройки боевого бота (`settings.json` на сервере);
- запускать скрипты, которые могут изменить реальные данные пользователей, чеков, акций или розыгрышей.

**Разрешено:**

- изучать проект;
- работать локально;
- работать в отдельной ветке;
- готовить патч;
- создавать файлы ТЗ;
- писать код без выкладки;
- запускать локальные проверки (pytest, локальная SQLite, локальный запуск сайта);
- описывать команды для деплоя, но не выполнять их;
- подготовить инструкцию «как выкатить», чтобы владелец проекта сам решил, когда применять.

Обязательная формулировка:

> Не выполняй деплой, push, миграции или перезапуск боевых сервисов самостоятельно.
> Закончи реализацию в коде, покажи список изменённых файлов, опиши что нужно проверить
> и подготовь инструкцию для выкладки. Выкатывать на production можно только после
> отдельной прямой команды владельца проекта.

---

## 9. Рекомендуемый порядок реализации

1. Открыть таблицы акций и чеков: `table_shem.json` (строки 25, 30, 34).
2. Открыть создание/редактирование акции: `site_bot/main.py` `save_draw()` (602) + `prize_draws.html`.
3. Открыть pipeline загрузки чека: `heandlers/media_heandler.py` `set_photo()` (888).
4. Открыть постановку в очередь: `sql_mgt.enqueue_receipt_ocr()` (1268), вызов на media_heandler.py:914.
5. Открыть текущую проверку keywords: media_heandler.py:736-737, 727-731, 267-268.
6. Открыть извлечение FNS items: `_check_vodka_in_receipt()` (678-731).
7. Добавить в `table_shem.json`: колонку `auto_validation_enabled` + таблицы `prize_draw_rules`, `receipt_items`; прогнать локальную миграцию (`python receipt_queue_worker.py --migrate` на локальной БД).
8. Добавить checkbox авто-валидации в админку (`DrawIn`, `save_draw()`, GET `/prize-draws`, `prize_draws.html`).
9. Добавить `get_draw_auto_validation()` и проверку в `set_photo()` перед enqueue; статус «На ручной проверке» + `allowedStatuses` в `receipts.html`.
10. Добавить структуру правил: DDL уже в шаге 7; `RuleIn`, `DrawIn.rules`.
11. Добавить админку правил: блок в `prize_draws.html`, чтение в GET `/prize-draws`, перезапись в `save_draw()`, удаление в `delete_draw()`.
12. Добавить DAL: `get_draw_rules()`, `save_receipt_items()`, `get_receipt_items()`.
13. Добавить `receipt_validation.py` и проверку FNS items по aliases/min_quantity в `process_receipt()` (fallback на keywords, если правил нет).
14. Добавить OCR fallback по алиасам правил с `min_quantity == 1`.
15. Включить сохранение `receipt_items` в `process_receipt()`.
16. Добавить отображение items в `/api/receipts/{id}` + `receipts.html`.
17. Прогнать тестовые сценарии из раздела 10 + `python -m pytest tests/ -v`.
18. Убрать временные debug-логи (постоянные `logger.info` пайплайна не трогать).
19. Описать итог: список изменённых файлов, что проверить, инструкция выкладки (НЕ выполнять её).

---

## 10. Тестовые сценарии

Локальная проверка: `cd /Users/romanzhdanov/My_project/VodkaBot/vodka_bot && python -m pytest tests/ -v`.
Для ручных сценариев использовать локальную БД (фикстура `tmp_db` в `tests/conftest.py`
создаёт схему из `table_shem.json` — новые таблицы попадут автоматически).

### Авто-валидация акции

* [ ] Старая акция (создана до миграции, значение колонки = 1) работает как раньше: чек попадает в `receipt_ocr_queue`
* [ ] Новая акция с включённой авто-валидацией отправляет чек в очередь
* [ ] Новая акция с выключенной авто-валидацией: записи в `receipt_ocr_queue` НЕТ, статус чека «На ручной проверке»
* [ ] Галочка сохраняется при создании акции (POST `/prize-draws`, insert)
* [ ] Галочка сохраняется при редактировании акции (POST `/prize-draws`, update) и корректно показывается при повторном открытии модалки
* [ ] Чек при выключенной авто-валидации виден на `/receipts`, статус «На ручной проверке» есть в фильтре и в select статуса
* [ ] Ручное подтверждение такого чека шлёт пользователю «✅ Чек подтверждён» (существующий код `update_receipt()`)
* [ ] `draw_id is None` (нет активной акции, но GET_CHECK остался True) → поведение как сейчас (enqueue)

### Правила акции

* [ ] Создано правило «Финская водка» (SKU `finsky-vodka`, алиасы `finsky; фински; финская водка; finsky vodka`, min_quantity 1, активно)
* [ ] Правила сохраняются/перечитываются при повторном открытии модалки акции
* [ ] Чек с FNS item, содержащим `finsky` → «Подтверждён»
* [ ] Чек с FNS item, содержащим `финская водка` → «Подтверждён»
* [ ] Чек без нужного товара в FNS items → «На ручной проверке» (не «Подтверждён», пользователю ❌ не уходит)
* [ ] Правило с min_quantity=2, в чеке quantity=1 → «На ручной проверке»
* [ ] Правило с min_quantity=2, в чеке quantity=2 (или 2 позиции по 1) → «Подтверждён»
* [ ] Неактивное правило (is_active=false) игнорируется
* [ ] Чек без QR уходит в OCR fallback
* [ ] OCR нашёл alias, правило min_quantity=1 → «Подтверждён»
* [ ] OCR нашёл alias, правило min_quantity=2 → «На ручной проверке»
* [ ] Ошибка/недоступность ФНС не роняет обработку (ретраи очереди работают как раньше)
* [ ] У акции нет правил → глобальные `product_keywords`, старые статусы («Нет товара в чеке» и т.д.) — поведение не изменилось
* [ ] Дубликат QR → «Чек уже загружен» (не изменилось)
* [ ] Ручная проверка после неуспешной авто-проверки работает (смена статуса в модалке чека)
* [ ] В модалке чека видны товары из ФНС (`receipt_items`), у совпавшей позиции видно правило
* [ ] Повторная обработка чека (ретрай воркера) не дублирует строки `receipt_items`

---

## 11. Критерии готовности

* [ ] В акции есть настройка авто-валидации (checkbox в модалке)
* [ ] Настройка сохраняется при создании и редактировании
* [ ] При выключенной авто-валидации чек не попадает в `receipt_ocr_queue`
* [ ] При включённой авто-валидации старый flow работает без изменений
* [ ] В акции можно настроить несколько правил ассортимента
* [ ] В правиле можно указать алиасы (через `;`)
* [ ] В правиле можно указать `min_quantity`
* [ ] Авто-проверка использует правила конкретной акции (по `receipts.draw_id`)
* [ ] Каждый чек проверяется отдельно (агрегации между чеками нет)
* [ ] Подходящий чек подтверждается автоматически
* [ ] Неподходящий чек не подтверждается автоматически
* [ ] Сомнительный чек получает статус «На ручной проверке»
* [ ] Глобальные keywords продолжают работать для акций без правил
* [ ] `python -m pytest tests/ -v` зелёный; добавлены тесты на `receipt_validation`, новые DAL-функции и новые строки схемы
* [ ] Основные сценарии раздела 10 пройдены
* [ ] На production ничего не выкатывалось; подготовлена инструкция выкладки

---

## 12. Риски и ограничения

- Магазины по-разному пишут один товар в чеке («ВОДКА ФИНСКИ 40% 0,5Л» и т.п.) — алиасы
  не покрывают всё; поэтому «нет совпадения по правилам» = ручная проверка, а не авто-отказ.
- OCR ошибается (качество фото, шрифты) — OCR никогда не используется для количества.
- Количество надёжно только по ФНС; ФНС бывает недоступна (таймауты, отсутствие
  `FNS_MASTER_TOKEN` локально) — при ошибке ФНС чек уходит в OCR fallback, при сомнении — на ручную проверку.
- Без QR точность ниже — только OCR-подтверждение при min_quantity == 1.
- 100% авто-валидацию гарантировать нельзя — ручная проверка остаётся частью процесса.
- SQLite остаётся как есть; полная перезапись правил при сохранении акции (паттерн проекта) допустима — объёмы маленькие.
- Сложную SKU-систему (каталог, нормализация, иерархии) не делаем — `sku_code` это просто текстовая метка.
- `site_bot/main.py` автозагружает схему при импорте — на немигрированной БД новые
  колонки/таблицы отсутствуют; использовать паттерн `HAS_...` и try/except autoload,
  порядок на выкладке: миграция → перезапуск сайта.

---

## 13. Что не нужно делать

- не делать опросы;
- не делать стикеры;
- не делать новую систему ручной модерации (использовать `/receipts`);
- не переносить БД на PostgreSQL;
- не делать импорт Excel;
- не делать ML-нормализацию названий товаров;
- не делать аналитику продаж поверх `receipt_items`;
- не делать новую админку (только расширение существующих шаблонов);
- не переписывать OCR (`ocr.py`, subprocess-механику media_heandler);
- не переписывать ФНС-клиент (`fns_api.py` менять НЕ нужно вообще);
- не делать агрегацию покупок пользователя по нескольким чекам;
- не делать отдельный новый backend;
- не делать push/deploy на production;
- не запускать production-миграции;
- не перезапускать production-сервисы (`supervisorctl`, `systemctl`, nginx).

---

## 14. Список файлов для реализации

| Файл | Что в нём сейчас | Что нужно изменить | Риск |
|---|---|---|---|
| `table_shem.json` | DDL всех таблиц; `prize_draws` (стр. 25), `receipts` (30), `receipt_ocr_queue` (34) | Добавить колонку `auto_validation_enabled BOOLEAN DEFAULT 1` в `prize_draws`; добавить таблицы `prize_draw_rules` и `receipt_items` | Низкий: миграция автоматическая (`ALTER TABLE ADD COLUMN` в `sql_mgt.update_table`), default сохраняет поведение |
| `sql_mgt.py` | DAL: `get_active_draw_id` (1216), `add_receipt` (1229), `enqueue_receipt_ocr` (1268), `update_receipt_status` (1380), `get_receipt` (1658) | Добавить `get_draw_auto_validation()`, `get_draw_rules()`, `save_receipt_items()`, `get_receipt_items()`. Существующие функции не менять | Низкий: только новые функции по образцу существующих (`@with_connection`) |
| `heandlers/media_heandler.py` | `set_photo` (888-932) — создание чека + enqueue; `process_receipt` (734-885) — авто-пайплайн; `_check_vodka_in_receipt` (678-731) — ФНС + keywords; `_check_keywords_with_ocr` (386) — OCR | В `set_photo`: проверка авто-валидации перед enqueue, статус «На ручной проверке». В `process_receipt`: загрузка правил акции, ветка правил vs legacy-keywords, сохранение items, новые статусы/комментарии. В `_check_vodka_in_receipt`: вернуть items третьим элементом | **Средний: ядро пайплайна.** Обязательно сохранить legacy-ветку бит-в-бит и проверить оба режима |
| `receipt_validation.py` (**новый**) | — | Чистые функции: `parse_aliases`, `match_items_to_rules`, `ocr_keywords_for_rules` | Низкий: новый изолированный модуль без тяжёлых импортов |
| `site_bot/main.py` | Админка: autoload таблиц (270-272, 355), GET `/prize-draws` (476), `StageIn`/`DrawIn` (585/594), `save_draw` (602), `delete_draw` (695), `/api/notifications` (873), GET `/receipts` (1853), GET/POST `/api/receipts/{id}` (1914/1962) | `DrawIn.auto_validation_enabled` + `rules: List[RuleIn]`; чтение/запись флага и правил в GET/POST `/prize-draws`; удаление правил в `delete_draw`; autoload `prize_draw_rules_table`/`receipt_items_table` с try/except; items в GET `/api/receipts/{id}`; (опц.) «На ручной проверке» в notifications | Средний: не сломать сохранение этапов/победителей; использовать паттерн `HAS_...` для опциональных колонок |
| `site_bot/templates/prize_draws.html` | Модалка акции: основные поля (48-76), JS `openDrawModal` (165), `btn-new-draw` (354), `btn-save-draw` (417), копирование (369) | Checkbox «Авто-валидация чеков»; блок «Правила проверки чеков» (template-строка, добавление/удаление, сбор в `currentDraw.rules`) | Средний: аккуратно с JS-сбором данных; проверить создание, редактирование и копирование акции |
| `site_bot/templates/receipts.html` | Список чеков + модалка; `allowedStatuses` (144-150) | Добавить статус «На ручной проверке» в `allowedStatuses`; блок «Товары из ФНС» в модалке | Низкий |
| `receipt_queue_worker.py` | Воркер очереди: `_process_queue` (229-294) вызывает `media_heandler.process_receipt` | Изменения НЕ обязательны (вся логика в media_heandler). Опционально — защитная проверка авто-валидации | Низкий |
| `fns_api.py` | SOAP-клиент ФНС, `get_receipt_by_qr` (263) | **Не менять** | — |
| `ocr.py` | EasyOCR wrapper (`extract_text`, `release_reader`) | **Не менять** | — |
| `heandlers/menu.py` | `GET_CHECK` при `item_id == 'check'` (275-286) | **Не менять** (приём чеков по-прежнему требует активную акцию) | — |
| `tests/test_sql_mgt.py` | Тесты схемы и DAL (фикстура `tmp_db`) | Добавить: парсинг новых DDL-строк, наличие `auto_validation_enabled`/`prize_draw_rules`/`receipt_items`, тесты новых DAL-функций | Низкий |
| `tests/test_receipt_validation.py` (**новый**) | — | Параметрические тесты `match_items_to_rules`: алиасы, casefold, min_quantity, отсутствие quantity, неактивные правила | Низкий |
| `CLAUDE.md` | Документация проекта | После реализации: новые таблицы в раздел «База данных», обновить «Поток обработки чека» | Низкий |

---

## Финальное напоминание для реализационной нейросети

Все точки входа уже найдены и перечислены — не ищи их заново. Меняй только то, что описано.
При любом сомнении в авто-проверке чека — статус «На ручной проверке». По завершении:
покажи список изменённых файлов, результаты `pytest`, чек-лист раздела 10 и инструкцию
выкладки. **Деплой, push, миграции и перезапуск боевых сервисов — только после отдельной
прямой команды владельца проекта.**
