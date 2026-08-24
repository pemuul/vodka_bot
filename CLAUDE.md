# VodkaBot — документация проекта

## Назначение

Telegram-бот (aiogram 3) для управления магазином / акциями с распознаванием чеков ФНС.
Фреймворк-конструктор: одна кодовая база запускает разные ботов через разные `run_bot.py`.

Ключевые функции:
- Дерево меню из JSON (tree_data.json) без единой строки изменений в коде
- Приём и OCR-распознавание кассовых чеков (pyzbar + EasyOCR + WeChat QR)
- Проверка чеков через SOAP API ФНС (`fns_api.py`)
- Розыгрыши (prize_draws) с этапами и победителями
- Заказы и платежи через Telegram Payments
- Веб-панель администратора (FastAPI + SQLAdmin) в `site_bot/`
- Рассылки (scheduled_messages) по подписчикам
- Полное логирование всех входящих/исходящих сообщений (participant_messages)

---

## Архитектура: процессы

Три независимых процесса под supervisor:

| Процесс | Точка входа | Что делает |
|---|---|---|
| **bot** | `run_bot.py` → `bot.run_bot()` | Polling Telegram, обработка сообщений |
| **receipt_worker** | `run_receipt_worker.py` → `receipt_queue_worker.main()` | OCR + ФНС для очереди чеков |
| **site** | `site_bot/site_flusk_run.py` | FastAPI веб-интерфейс |

Шаблон конфига supervisor — `new_bot_file/supervisor.conf`.

---

## Структура файлов

```
vodka_bot/
├── bot.py                   # Ядро: GlobalObjects, Middleware, run_bot()
├── sql_mgt.py               # Весь слой БД (aiosqlite + sqlite3)
├── fns_api.py               # SOAP-клиент ФНС, парсинг QR-кодов
├── receipt_validation.py    # Сопоставление позиций чека с правилами акции (алиасы, min_quantity)
├── ocr.py                   # EasyOCR wrapper (extract_text, release_reader)
├── keys.py                  # Константы: DB_NAME, MAIN_JSON_FILE, флаги
├── json_data_mgt.py         # TreeObject — дерево меню из JSON
├── run_bot.py               # Точка входа: токен + admins → run_bot()
├── run_receipt_worker.py    # Точка входа receipt_queue_worker
├── receipt_queue_worker.py  # Воркер обработки очереди OCR
├── table_shem.json          # DDL всех таблиц БД
├── new_bot_file/
│   └── settings.json        # Конфиг бота (токен, restart_hour, payments)
├── heandlers/               # Обработчики сообщений (aiogram Router)
│   ├── commands.py          # /start, /help, ...
│   ├── answer_button_menu.py # Inline/Reply кнопки меню
│   ├── media_heandler.py    # Фото/файлы → распознавание чеков
│   ├── admin.py             # Команды для администраторов
│   ├── admin_answer_button.py
│   ├── import_files.py      # Загрузка файлов из меню
│   ├── mailing.py           # Рассылки
│   ├── order.py             # Заказы и их статусы
│   ├── pyments.py           # Telegram Payments flow
│   ├── settings_bot.py      # Настройки из бота
│   ├── answer_button_settings.py
│   ├── answer_button_subscription.py
│   ├── confirm_age_phone.py # Верификация возраста + телефона
│   ├── text_heandler.py     # Произвольный текст
│   └── web_market.py        # Web App (мини-магазин)
├── keyboards/
│   ├── menu_kb.py
│   ├── admin_kb.py
│   ├── settings_kb.py
│   ├── subscriptions_kb.py
│   └── callback_data_classes.py
├── site_bot/
│   ├── main.py              # FastAPI приложение
│   ├── orders_mgt.py        # Управление заказами
│   ├── send_bot_message.py  # Отправка сообщений из веб
│   └── templates/           # Jinja2-шаблоны (participants, receipts, ...)
├── pyment_bot_dir/
│   └── pyment_bot.py        # Отдельный платёжный бот
├── load_files/
│   └── data_tree.json       # Рабочая копия дерева меню (runtime)
└── wechat_qrcode/           # Модели WeChat QR-детектора
```

---

## Ключевые паттерны кода

### GlobalObjects (bot.py)
Синглтон, доступный во всех модулях через `init_object()`:
```python
class GlobalObjects:
    tree_data: TreeObject   # дерево меню
    bot: Bot                # aiogram Bot
    admin_list: list        # tg_id администраторов
    dp: Dispatcher
    command_dict: dict      # описания команд (/help, /promote ...)
    settings_bot: dict      # из settings.json
    ocr_pool: Executor      # ThreadPoolExecutor для OCR
```
Каждый handler-модуль получает `global_objects` через `init_object(global_objects_inp)`.

### with_connection / with_connection_def (sql_mgt.py)
Декораторы для управления соединением с SQLite:
- `@with_connection` — async (aiosqlite)
- `@with_connection_def` — sync (sqlite3)

Соединение передаётся в `conn=` — можно передать своё для транзакций.

### Дерево меню (json_data_mgt.py)
`TreeObject` читает `data_tree.json` и строит дерево узлов.
Каждый узел: `key`, `text`, `media`, `item_id`, `redirect`, `next_layers`.
Навигация по дереву — через `SPLITTER_STR = '/-/'` в callback_data.

### Миграции БД (sql_mgt.py)
`create_db()` → `create_or_update_tables()`:
- Если таблицы нет — создаёт
- Если есть — сравнивает схему, добавляет новые колонки, удаляет лишние (через пересоздание)

Схема хранится в `table_shem.json`. Изменение схемы = правка JSON.

---

## База данных (SQLite: tg_base.sqlite)

| Таблица | Назначение |
|---|---|
| users | Пользователи (tg_id, name, age_18, phone) |
| user_settings | Подписка пользователя |
| user_extended | Username + полный dict Message при регистрации |
| user_params | last_message_id, last_media_message_list |
| user_rule | Роли пользователей (GET_INFO_MESSAGE, ...) |
| admins | Администраторы бота |
| admin_invite | Временные ключи приглашения (TTL 1 час) |
| params | key-value параметры для пользователя |
| params_site | key-value параметры веб-интерфейса |
| visite_log | Логи посещений (user_tg_id, visit_date, visit_count) |
| history_user | История навигации по дереву |
| last_image | Последний media_id для пользователя |
| item | Товары магазина |
| sales_header | Заказы (no, client_id, status, is_paid_for) |
| sales_line | Строки заказа |
| additional_field | Доп. поля заказа (из input_order_fields в settings.json) |
| cancel_order | Отложенная отмена заказа (по таймауту) |
| wallet_log | Кошелёк бота (balance, total_spent_month, ...) |
| questions | Вопросы от пользователей |
| question_messages | Переписка по вопросу |
| scheduled_messages | Запланированные рассылки |
| prize_draws | Акции — теперь **безданный контейнер**: только `id, title, create_dt`. Все даты/статус/настройки переехали на этапы (см. "Один активный этап на всю систему" ниже) |
| prize_draw_stages | Этапы розыгрыша (winners_count, `stage_type` TEXT DEFAULT 'standard': `standard`/`guaranteed_prize`, `progress_message_text`, `win_message_text` — редактируемые шаблоны сообщений для `guaranteed_prize`; `start_date`/`end_date` DATE, `status` TEXT DEFAULT 'upcoming' (`upcoming`/`active`/`finished`), `auto_validation_enabled` BOOLEAN DEFAULT 1 — переехали сюда с `prize_draws` при пивоте на модель "один активный этап на всю систему"; `status='active'` может быть **не более чем у одного этапа во всей БД одновременно**, это проверяется на записи в `site_bot/main.py:save_draw()`) |
| prize_draw_rules | Правила проверки чеков **этапа** (title, sku_code, aliases через `;`, min_quantity, is_active). Привязаны к `stage_id`, не к акции (переехало с `draw_id` одноразовой автомиграцией `sql_mgt.migrate_prize_draw_rules_draw_to_stage()`, см. "Гарантированный приз" ниже) |
| prize_draw_winners | Победители этапа — для `standard` заполняется вручную (кнопка «Определить победителя»), для `guaranteed_prize` — автоматически ботом при выполнении условий |
| participant_settings | Настройки участника (blocked, tester) |
| participant_messages | Полный лог диалога бота с пользователем |
| receipts | Загруженные чеки (number, date, amount, qr, status, `draw_id`, `stage_id` — этап, который был активен в МОМЕНТ ОТПРАВКИ чека, зафиксирован раз и навсегда в `set_photo()`, не пересчитывается при обработке) |
| receipt_ocr_queue | Очередь OCR (pending → processing → done) |
| receipt_items | Товарные позиции чека из ФНС (raw_name, quantity, price, sum, matched_rule_id) |
| images | Загруженные изображения |
| deleted_images | Удалённые изображения |
| notifications | Уведомления для пользователей |

Статусы чека: `не подтвержден` → `подтвержден` / `ошибка` / `дубликат`.
Реально используемые статусы бота: `В авто обработке`, `На ручной проверке`, `Подтверждён`, `Чек уже загружен`, `Нет товара в чеке`, `Лишний чек`, `Ошибка` (см. "Поток обработки чека").
`Лишний чек` — чек пользователя, который уже выполнил условия единственного активного во всей
системе `guaranteed_prize`-этапа; ставится без QR/ФНС-проверки (см. "Гарантированный приз"
ниже).

---

## Поток обработки чека

1. Пользователь присылает фото чека в бот (`heandlers/media_heandler.py` → `set_photo()`)
2. Файл сохраняется в `site_bot/static/uploads/`, определяется единственный активный во всей
   системе этап (`sql_mgt.get_active_stage()`) — если активного этапа нет вообще, пользователю
   сразу отвечают «сейчас акция не проводится», чек не принимается
3. **Ранняя проверка «лишний чек»** (`_is_extra_receipt()`): если этап — `guaranteed_prize` и
   пользователь уже его победитель — статус `"Лишний чек"`, сообщение
   `receipt_validation.EXTRA_RECEIPT_MESSAGE`, чек **не** сохраняется в очередь (оптимизация,
   не тратим QR/ФНС/OCR на заведомо лишний чек); для `standard`-этапа чек никогда не «лишний»
4. Проверяется `active_stage["auto_validation_enabled"]` — теперь это поле **этапа**, не акции
   (checkbox в `/prize-draws` на вкладке этапа, default `1`)
5. **Авто-валидация включена**: статус `"В авто обработке"`, запись в `receipt_ocr_queue`
6. **Авто-валидация выключена**: статус `"На ручной проверке"`, чек в очередь **не ставится**
   — ждёт ручной проверки на `/receipts`
7. Чек сохраняется с `draw_id`/`stage_id` активного на данный момент этапа
   (`sql_mgt.add_receipt()`) — это **пиновка навсегда**: даже если админ переключит активный
   этап, пока чек ждёт очереди, `process_receipt()` всё равно оценит его по тому этапу, под
   который он был реально загружен, а не по «текущему активному на момент обработки»
8. `receipt_queue_worker.py` подбирает задачу из очереди → `media_heandler.process_receipt()`
9. **Повторная проверка «лишний чек»** (защита от гонки — два чека отправлены почти
   одновременно, либо пользователь стал победителем, пока чек ждал в очереди) → тот же
   результат, что и в п.3, по тому же зафиксированному в чеке `stage_id`
10. QR (pyzbar → WeChat QR → enhanced) → дубликат по QR → `"Чек уже загружен"`
11. `fns_api.get_receipt_by_qr()` → SOAP ФНС API; товарные позиции сохраняются в `receipt_items`
12. **Проверка товара по ОДНОМУ этапу — тому, что зафиксирован в `receipts.stage_id`**
    (`sql_mgt.get_stage_rules(stage_id)`; НЕ цикл по всем этапам акции — с пивота на «один
    активный этап» у чека физически может быть только один релевантный этап):
    - если у этапа есть активные правила (оба типа — и `guaranteed_prize`, и `standard`
      используют одну и ту же модель) —
      `receipt_validation.match_items_accumulating()`: количество товара в рамках ОДНОГО чека
      неважно, важен факт наличия товара по алиасам правила; порог проверяется по накопленной
      сумме за ВСЕ подтверждённые чеки пользователя (`sql_mgt.get_user_rule_progress()`, см.
      "Гарантированный приз" ниже)
    - совпадение хотя бы по одному правилу → чек `"Подтверждён"`, дальше по типу этапа:
      `guaranteed_prize` → `sql_mgt.evaluate_guaranteed_prize_stage()` (автопобеда при полном
      выполнении всех правил); `standard` → `sql_mgt.evaluate_standard_stage_progress()`
      (полное выполнение НЕ означает победу — только допуск к розыгрышу, который админ
      по-прежнему проводит вручную кнопкой «Определить победителя»,
      `POST /api/draw-stages/{id}/determine`; эта авто-логика никогда не пишет в
      `prize_draw_winners`)
    - товар НЕ найден ни по одному правилу, а ФНС при этом успешно ответила (данные надёжны)
      → немедленный авто-отказ, статус `"Нет товара в чеке"`, БЕЗ ручной подстраховки
      (сознательное решение владельца проекта: ФНС считается достаточно надёжным источником
      для авто-отказа; риск — конфигурационные баги в алиасах правил теперь не ловятся
      ручной проверкой на этом пути, см. пример ниже)
    - у этапа нет правил (пустой список `get_stage_rules(stage_id)`) → fallback на
      глобальные `product_keywords` (таблица `params`, `user_tg_id=0`), статусы
      `"Подтверждён"` / `"Нет товара в чеке"` (старое поведение, не изменилось)
13. OCR-фallback (если QR не найден или ФНС недоступна — единственный путь, где решение
    объективно неопределённое, поэтому здесь и только здесь сохранена ручная проверка):
    для правил этапа используются только алиасы правил с `min_quantity == 1` (количество
    через OCR не проверяется никогда); атрибуция прогресса конкретному правилу возможна только
    если среди подходящих `min_quantity==1`-правил ровно одно — иначе OCR не подтверждает
    вовсе (`_guaranteed_ocr_rule_id()`, media_heandler.py — распространяется на оба типа
    этапа, несмотря на имя функции). Если OCR тоже не подтвердил — `"На ручной проверке"`,
    единственный оставшийся путь к ручной проверке в этом потоке.
14. Обновление статуса чека, уведомление пользователя (кроме `"На ручной проверке"` — ждёт
    администратора на `/receipts`); для события накопительного прогресса (оба типа этапа) —
    специальный текст (см. "Гарантированный приз" ниже) вместо обычного `"✅ Чек подтверждён"`

---

## Гарантированный приз

### Один активный этап на всю систему (архитектурный пивот)

Изначальный дизайн (см. `TZ_GUARANTEED_PRIZE_STAGE_TYPES.md`) допускал несколько параллельно
активных этапов, и один чек мог засчитаться сразу по нескольким. В процессе ручного
тестирования владелец решил, что это запутывает пользователей, и попросил пересобрать модель:
**активным во всей системе может быть не более одного этапа одновременно** (не на акцию — на
всю БД).

- `prize_draws` урезан до безданного контейнера: `id, title, create_dt`. Даты, статус
  (`upcoming`/`active`/`finished`) и `auto_validation_enabled` переехали на
  `prize_draw_stages` — раньше это были поля акции.
- Одноразовая миграция `sql_mgt.migrate_draw_fields_to_stage()` (вызывается автоматически из
  `create_or_update_tables()`, атомарна, идемпотентна) копирует старые даты/автовалидацию
  акции на ВСЕ её этапы, а старый статус акции — только на ПЕРВЫЙ этап (по `order_index`);
  остальные этапы той же акции получают `'upcoming'`. Затем обязательный проход глобальной
  дедупликации: если после переноса `'active'` оказался больше чем у одного этапа во всей
  БД — оставляет только этап с наименьшим `id`, остальные понижает до `'upcoming'` (лог
  warning). Акция без единого этапа — данные физически некуда перенести, warning в лог.
- `sql_mgt.get_active_stage()` — новый основной способ узнать, что сейчас активно (возвращает
  весь этап целиком, включая `draw_id`). `sql_mgt.get_active_draw_id()` оставлен только как
  тонкая обёртка для мест, которым нужен исключительно `draw_id`.
- `receipts.stage_id` — чек пинится к этапу, который был активен в момент **отправки**
  (`set_photo()`), не пересчитывается при обработке (см. "Поток обработки чека" выше,
  п.2/7/9/12) — обработка может отстать от момента отправки, а активный этап за это время
  мог смениться.
- `site_bot/main.py: save_draw()` блокирует (`400`) сохранение, если в одном payload
  пытаются активировать 2+ этапа сразу, или если другой этап уже активен где-то ещё в БД —
  это единственное место, где инвариант "не больше одного active" реально проверяется на
  запись.
- `prize_draws.html`: поля дат/статуса/автовалидации переехали с уровня акции на вкладку
  каждого этапа; список акций показывает 🟢-бейдж с именем активного этапа
  (`draw.hasActiveStage`, считается на сервере).
- Побочный эффект для `process_receipt()`: раньше он проверял товар по ВСЕМ этапам акции в
  цикле (`sql_mgt.get_draw_stages(draw_id)`); теперь — ровно по одному этапу из
  `receipts.stage_id` (`_merge_item_rule_maps()` и мульти-правило-на-позицию исчезли как
  класс — у чека физически не может быть больше одного релевантного этапа).

Механика накопления прогресса (правила/алиасы/победа), описанная в разделе ниже, от пивота не
изменилась — поменялось только то, ПО КАКОМУ этапу чек оценивается.

Тип этапа `prize_draw_stages.stage_type = 'guaranteed_prize'` (альтернатива `standard`) — приз
получает **каждый** участник, накопивший нужный товар по своим правилам в любом количестве
чеков (не обязательно одним), а не случайно выбранный победитель. Реализовано поверх
существующего пайплайна проверки чеков, без новой таблицы прогресса — прогресс считается на
лету агрегирующим SQL-запросом.

- **Прогресс участника по правилу** (`sql_mgt.get_user_rule_progress()`) — сумма
  `receipt_items.quantity` по всем чекам пользователя в рамках акции со статусом
  `"Подтверждён"`, сматченным на это правило (`matched_rule_id`). Правило считается
  выполненным, когда сумма ≥ `min_quantity`.
- **Победа** (`sql_mgt.evaluate_guaranteed_prize_stage()`, используется и автопайплайном, и
  ручным подтверждением админа) — когда выполнены ВСЕ активные правила этапа, в
  `prize_draw_winners` автоматически вставляется запись (`sql_mgt.add_stage_winner()`);
  повторно пользователь не может выиграть тот же этап (`sql_mgt.is_stage_winner()`).
  **Важно**: чек должен получить статус `"Подтверждён"` в БД РАНЬШЕ пересчёта прогресса —
  иначе агрегирующий запрос не увидит позиции только что обработанного чека (нашли на этом
  живой баг при разработке — см. `TZ_GUARANTEED_PRIZE_STAGE_TYPES.md`, раздел 4.3/4.6).
- **Три исхода уведомления** после проверки чека: (1) чек подтверждён, но условия ещё не
  выполнены — текст с остатком товара, НЕ число оставшихся чеков
  (`receipt_validation.format_remaining_items()` + `build_progress_message()`,
  плейсхолдер `{remaining_items}` в `prize_draw_stages.progress_message_text`); (2) чек
  закрывает все условия — финальный текст (`build_win_message()`,
  `prize_draw_stages.win_message_text`); (3) чек лишний (условия уже выполнены раньше) —
  статус `"Лишний чек"`, см. поток выше. Оба текстовых поля редактируемые, пустое значение →
  дефолт из кода.
- **Ручной ввод товара администратором** (`/receipts`, не привязан к типу этапа — правила
  всех этапов акции доступны в выпадающем списке; только когда нужно — `min_quantity>1`
  требует количество, `min_quantity==1` достаточно факта) — `sql_mgt.add_manual_receipt_item()`
  ДОБАВЛЯЕТ строку в `receipt_items`, не стирая уже сохранённые ФНС-позиции (в отличие от
  `save_receipt_items()`, которая делает `DELETE` перед вставкой). После сохранения
  прогресс/победа автоматически пересчитываются и пользователю уходит уведомление — для
  ОБОИХ типов этапа (`site_bot/main.py: update_receipt()`), админу не нужен отдельный шаг
  «подтвердить приз».
- **Веб-процесс** (`site_bot/main.py`) не подключён к `sql_mgt.db_name` (использует
  `databases`/SQLAlchemy, не aiosqlite) — поэтому там есть параллельные (не переиспользующие
  sql_mgt.py) реализации той же бизнес-логики: `_evaluate_guaranteed_prize_stage()`,
  `_evaluate_standard_stage_progress()`, `_get_user_rule_progress()`, `_get_stage_progress()`,
  `_is_stage_winner()`, `_add_stage_winner()`, `_add_manual_receipt_item()`. При изменении
  логики прогресса/победы — правь **оба** места. Осторожно: `_get_stage_rules()` здесь по
  умолчанию `only_active=False`, а `sql_mgt.get_stage_rules()` — `only_active=True` (разные
  дефолты, легко забыть и получить неактивные правила в выборке) — всегда передавай
  `only_active=True` явно.
- **Миграция `prize_draw_rules.draw_id → stage_id`** (`sql_mgt.migrate_prize_draw_rules_draw_to_stage()`) —
  единственное место в проекте, где схема меняется не декларативно через `table_shem.json`, а
  написанной вручную функцией (нужно ВЫЧИСЛИТЬ новый `stage_id` из старого `draw_id`, а не
  просто скопировать колонку). Копирует каждое старое правило на КАЖДЫЙ существующий этап
  акции (воспроизводя прежнее поведение «правило общее на акцию»); акция без единого этапа —
  правило не переносится, в лог пишется warning. Атомарна (`BEGIN IMMEDIATE`/commit/rollback),
  идемпотентна, вызывается автоматически из `create_or_update_tables()` при каждом старте.

Подробности архитектуры, все решённые развилки и статус проверки каждого пункта —
`TZ_GUARANTEED_PRIZE_STAGE_TYPES.md` (корень репозитория) — описывает исходную версию
(guaranteed_prize-only); распространение накопительной модели на `standard` сделано позже,
см. подраздел ниже.

### Стандартный этап с накопительным прогрессом

`standard`-этап (обычный, случайный розыгрыш) использует ТУ ЖЕ модель накопления прогресса,
что и `guaranteed_prize` (см. выше — общий `match_items_accumulating()`,
`get_user_rule_progress()`), с одним принципиальным отличием: полное выполнение всех правил
этапа НЕ означает автоматическую победу.

- `sql_mgt.evaluate_standard_stage_progress()` / `_evaluate_standard_stage_progress()`
  (веб-эквивалент) — та же форма, что `evaluate_guaranteed_prize_stage()`, но НИКОГДА не
  вызывает `add_stage_winner()`/не пишет в `prize_draw_winners`. Возвращает `outcome`:
  `"no_rules"` / `"progress"` / `"complete"` (не `"won"` — это принципиально другое понятие:
  участник допущен к розыгрышу, а не выиграл).
- Уведомление при `"complete"` — `receipt_validation.build_standard_qualify_message()`
  (дефолт `DEFAULT_STANDARD_QUALIFY_MESSAGE`, «вы участвуете в розыгрыше», НЕ текст победы) —
  редактируется тем же полем `prize_draw_stages.win_message_text`, что и у `guaranteed_prize`
  (разный дефолт и подпись в UI, схема не меняется).
- **Попытка выиграть = полный "комплект" накопленных условий, НЕ чек и НЕ число чеков**
  (уточнение владельца: "не просто каждый чек, а группа чеков от 1 и более в совокупности
  проходящая валидацию"). `receipt_validation.compute_entries_count(rule_progress)` —
  чистая функция: `min(progress // min_quantity)` по всем правилам этапа (если правил
  несколько — число комплектов ограничивает самое дефицитное правило, аналог "сколько раз
  можно собрать рецепт из того, что накопили"). Несколько чеков могут в сумме дать только
  один комплект (2 чека по 1 шт. при `min_quantity=2` — 1 попытка, не 2), а один чек с
  избытком товара может сразу дать несколько (4 шт. при `min_quantity=2` — сразу 2 попытки).
  Используется в `evaluate_standard_stage_progress()`/`_evaluate_standard_stage_progress()`
  (`entries_count` в результате) и в `get_stage_progress()`/`_get_stage_progress()` (батч по
  всем пользователям). Подставляется в сообщения через `{entries_count}`
  (`build_standard_progress_message()`, `build_standard_qualify_message()`, склонение
  "N попыток" — `format_entries_phrase()`). Счётчик показывается и после выполнения условий
  — новые чеки продолжают копить попытки, без верхнего предела.
- **`entry_receipt_ids`** (в `get_stage_progress()`/`_get_stage_progress()`) — отдельное от
  `entries_count` понятие: список id подтверждённых чеков, у которых есть хотя бы одна
  позиция, сматченная на правило ИМЕННО этого этапа (не любой подтверждённый чек
  пользователя в акции). Не считает попытки (`len(entry_receipt_ids) != entries_count`,
  кроме частного случая `min_quantity=1`, где они совпадают) — используется только чтобы
  (а) не пустить чек, не относящийся к этому этапу, в прогресс/попытки, и (б) выбрать
  чек-представитель для отображения в списке победителей (превью, т.к. комплект физически
  не привязан к одному конкретному чеку).
- **Победителя standard-этапа по-прежнему выбирает админ вручную** — `POST
  /api/draw-stages/{stage_id}/determine` (`site_bot/main.py: api_determine_winners()`).
  Если у этапа заданы активные правила, пул случайного розыгрыша строится не из чеков
  напрямую, а из `entries_count` "виртуальных билетов" на каждого пользователя, выполнившего
  все правила (каждый билет — копия одного и того же чека-представителя из
  `entry_receipt_ids` этого пользователя) — так число билетов, которое видит пользователь в
  сообщении, всегда совпадает с тем, что реально участвует в розыгрыше. Если пользователь
  выиграет несколько своих билетов в одном розыгрыше, все такие записи в
  `prize_draw_winners` будут ссылаться на ОДИН и тот же `receipt_id` (представитель), а не
  на разные чеки — это ожидаемо, комплект не привязан 1:1 к чеку. **Живой баг, найденный и
  исправленный в этой доработке**: раньше фильтр брал ЛЮБОЙ подтверждённый чек пользователя
  в рамках акции (`draw_id`), включая не относящиеся к правилам этого этапа — например, чек,
  подтверждённый на другом этапе той же акции, добавлял пользователю лишний билет здесь.
  Регрессия — `tests/test_site_bot_progress.py::TestApiDetermineWinnersEntryScoping`. Если у
  этапа правил нет — поведение не меняется (любой подтверждённый чек акции — билет, как
  раньше).
- **Прогресс участников этапа** виден в админке — `/prize-draws`, кнопка «Прогресс
  участников» на вкладке этапа (для `standard` — с колонкой числа попыток), эндпоинт
  `GET /api/draw-stages/{stage_id}/progress` (`sql_mgt.get_stage_progress()` /
  `_get_stage_progress()` — батч-версия прогресса по ВСЕМ пользователям этапа, не по одному;
  возвращает `entry_receipt_ids`/`entries_count` наряду с `rule_progress`/`complete`).
- **Авто-отказ убирает ручную подстраховку** — если у правила неверно настроен алиас (не
  совпадает с тем, как ФНС реально сокращает название товара — например, алиас `"настойка"`
  не матчится с реальным `"Наст."` в данных ФНС), такой чек теперь автоматически уходит в
  `"Нет товара в чеке"` вместо ручной проверки, и никто не заметит проблему конфигурации.
  Проверяй алиасы на реальных данных ФНС (`fns_via_prod.py` — локальный dev-хелпер, гоняет
  `fns_api.get_receipt_by_qr()` на проде по SSH, не деплоится) перед тем как полагаться на
  авто-отказ в проде.

---

## Поток заказа

1. Пользователь выбирает товары через меню (tree_data.json)
2. `order.py` создаёт `sales_header` + `sales_line`
3. `pyments.py` инициирует Telegram Invoice
4. После оплаты: статус → `PAID`, резерв товара списывается
5. Через таймаут (cancel_minet) неоплаченный заказ отменяется (`cancel_order`)

---

## Конфигурация (settings.json)

```json
{
  "TELEGRAM_BOT_TOKEN": "...",
  "bot_settings": { "restart": { "hour": 10, "minet": 0 } },
  "site": {
    "site_on": true,
    "input_order_fields": [],           // Доп. поля при оформлении
    "API_order_status": { ... }         // Хуки статусов на внешний API
  },
  "pyment_settings": {
    "pyment_limit_per_mounth": 50000,
    "monthly_payment": 1000,
    "procent_pyment_limit": 1
  }
}
```

---

## Технологии (эталонные версии с сервера)

Версии с рабочего production-сервера — это золотой стандарт. Не обновлять без необходимости.

| Библиотека | Версия (прод) | Назначение |
|---|---|---|
| aiogram | **3.21.0** | Telegram Bot API |
| aiosqlite | **0.21.0** | Async SQLite |
| aiohttp | **3.12.14** | HTTP-клиент (зависимость aiogram) |
| fastapi | **0.116.1** | Веб-панель |
| uvicorn | **0.35.0** | ASGI-сервер |
| sqlalchemy | **2.0.41** | ORM для FastAPI |
| sqladmin | **0.21.0** | Автоадмин для FastAPI |
| databases | **0.9.0** | Async DB-слой для SQLAlchemy |
| jinja2 | **3.1.6** | Шаблоны веб-панели |
| pydantic | **2.11.7** | Валидация данных |
| pyzbar | **0.1.9** | Декодер QR из фото |
| opencv-contrib-python-headless | **4.12.0.88** | OpenCV + WeChat QR (contrib=WeChat!) |
| easyocr | **1.7.2** | OCR текста с чека |
| torch | **2.7.1** (+ CUDA 12.x) | PyTorch для EasyOCR (GPU!) |
| torchvision | **0.22.1** | Зависимость EasyOCR |
| numpy | **2.2.6** | Матрицы для OpenCV/EasyOCR |
| pillow | **11.3.0** | Обработка изображений |
| scikit-image | **0.25.2** | Обработка изображений |
| pytesseract | **0.3.13** | Fallback OCR |
| requests | **2.32.4** | SOAP ФНС API |
| cryptography | **45.0.5** | Шифрование |
| zxing-cpp | **2.3.0** | Дополнительный QR-декодер (C++) |
| pyzxing | **1.0.2** | Python-обёртка zxing |
| Flask | **3.1.2** | Установлен (возможно, историческая зависимость) |
| aiofiles | **24.1.0** | Async файловые операции |

Python **3.12.3** в venv на сервере.

---

## Production-сервер (эталонная конфигурация)

Все секреты (пароли, ключи, токены) — в `server_access.md` (в `.gitignore`, в гит не попадает).

**IP**: 217.198.6.100 | **Домен**: finskyice.com | **ОС**: Ubuntu 24.04.2 LTS  
**Железо**: 2 CPU, 3.8GB RAM, 50GB диск, **swap отсутствует**  
**Python**: 3.12.3 (системный = venv) | **nginx**: 1.24.0

### VPN до Telegram — обязательное условие работы бота

Сервер на российском IP — Telegram заблокирован. Split-tunnel: только Telegram IP-диапазоны
идут через VPN-узел `194.87.254.8` (Москва, AS214822 MT FINANCE LLC).

> **С 2026-08-07 используется AmneziaWG (обфусцированный WireGuard), userspace-режим**,
> НЕ обычный `wg0`/kernel-модуль. Причина: старый `wg0` (WireGuard, порт 51822) перестал
> пропускать TCP:443 до Telegram (ICMP и UDP-хендшейк проходили, TCP — нет; похоже на
> блокировку TSPU конкретно этого узла/протокола). Смена на AmneziaWG (порт 32893) с
> **kernel-модулем (`amneziawg-dkms`) тоже не помогла** — тот же баг: TCP не проходит именно
> через in-kernel модуль на этом сервере (виртуализация virtio-net + этот модуль/ядро,
> подтверждено тестом с другого хоста той же связкой ключей — там работало). Рабочая
> конфигурация — **userspace-демон `amneziawg-go`** вместо kernel-модуля.
>
> Сервис: `systemctl status awg0-telegram.service` (юнит `/etc/systemd/system/awg0-telegram.service`,
> `enabled` — переживает ребут, `Restart=on-failure`). Поднимает `awg0` через
> `/usr/local/bin/amneziawg-go -f awg0`, затем `ExecStartPost=/usr/local/bin/awg0-configure.sh`
> делает `awg setconf` + прописывает **только** Telegram-подсети (НЕ default route — иначе
> убьёшь SSH и весь остальной трафик сервера).
>
> Конфиг: `/etc/amnezia/amneziawg/awg0-setconf.conf` (crypto-часть, без Address/DNS —
> `setconf` их не понимает). Ключи и детали — в `server_access.md`.
>
> Старый `wg0` (`/etc/wireguard/wg0.conf`, `wg-quick`, порт 51822) оставлен как есть, но
> **не используется** (down, `wg-quick@wg0` disabled) — рабочий тот же баг с TCP, чинить не стали.
>
> **Диагностика при следующей поломке**: `curl --max-time 10 https://api.telegram.org` с
> сервера. Если `000`/timeout — проверить `systemctl status awg0-telegram`, `awg show`,
> и обязательно сверить ICMP (`ping <telegram-ip>`, обычно проходит) против TCP
> (`curl`/`tcpdump -i awg0 host <telegram-ip>` — SYN уходит, SYN-ACK не приходит = тот же
> паттерн). Если сервис `awg0-telegram` активен, а TCP всё равно не идёт — проверить, не
> собрался ли снова kernel-модуль вместо userspace (`ip -d link show awg0` → `linkinfo` c
> `amneziawg` типом значит kernel-режим, тогда переустановить через `ExecStart=amneziawg-go -f`).

### Структура файлов на сервере (отличается от локальной!)

```
/home/VodkaBot/               ← корень деплоя
├── settings.json             ← конфиг (ТОКЕН, VERSION_BOT="vodka_bot")
├── run_bot.py                ← точка входа бота (читает VERSION_BOT, добавляет в sys.path)
├── run_receipt_worker.py     ← точка входа воркера
├── tg_base.sqlite            ← БОЕВАЯ БД (НА УРОВЕНЬ ВЫШЕ кода!)
├── tg_base_30_12_25.sqlite   ← бэкап БД от 30.12.2025
├── tree_data.json            ← активное дерево меню (вне git!)
├── tree_data_old.json        ← предыдущая версия дерева
├── venv/                     ← virtualenv (Python 3.12.3)
├── vodka_bot/                ← git-репозиторий (сам код)
│   └── site_bot/static/uploads/  ← JPEGs чеков
├── load_files/               ← история версий data_tree_*.json
├── logs/ocr_worker/          ← логи subprocess OCR
├── models/wechat_qrcode/     ← модели WeChat QR (вне git!)
└── test_find_qr.py           ← ручные тест-скрипты для отладки QR/OCR
```

> `tg_base.sqlite`, `tree_data.json` и `models/` живут на уровень выше кода.
> В `settings.json` ключ `run_directory` = `/home/VodkaBot` — добавляется при старте.

### Git репозиторий

```
git@github.com-vodka:pemuul/vodka_bot.git  (ветка: main)
```

Нестандартный SSH-алиас `github.com-vodka` — настроен в `~/.ssh/config` на сервере.
Деплой: `cd /home/VodkaBot/vodka_bot && git pull`

### Supervisor (3 процесса, конфиг: `/etc/supervisor/conf.d/vodka_services.conf`)

```ini
[program:vodka_bot]
command=/home/VodkaBot/venv/bin/python /home/VodkaBot/run_bot.py
environment=FNS_MASTER_TOKEN="..."
directory=/home/VodkaBot
stdout_logfile=/var/log/vodka_bot/out.log
stderr_logfile=/var/log/vodka_bot/err.log

[program:vodka_site]
command=/home/VodkaBot/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
environment=TG_BOT="...",SITE_SESSION_SECRET_KEY="...",SITE_ADMIN_USERNAME="admin",SITE_ADMIN_PASSWORD="..."
directory=/home/VodkaBot/vodka_bot/site_bot
stdout_logfile=/var/log/vodka_site/out.log
stderr_logfile=/var/log/vodka_site/err.log

[program:vodka_bot_check]
command=/home/VodkaBot/venv/bin/python /home/VodkaBot/run_receipt_worker.py
environment=FNS_MASTER_TOKEN="..."
directory=/home/VodkaBot
stdout_logfile=/var/log/vodka_bot/out_check.log
stderr_logfile=/var/log/vodka_bot/err_check.log
```

### nginx

- `finskyice.com:443` → `proxy_pass http://127.0.0.1:8000`, SSL Certbot
- `finskyice.com:80` → 301 редирект на HTTPS
- `client_max_body_size 20M`, WebSocket headers настроены

### Cron

```
0 3 * * *  certbot renew --quiet --post-hook "systemctl reload nginx"
```

Certbot systemd-таймер обновляет сертификат каждые 12 часов, если до истечения < 30 дней.

### Мониторинг

**Zabbix-агент** запущен — сервер подключён к внешней системе мониторинга.

### Переменные окружения для receipt_worker
- `TELEGRAM_BOT_TOKEN` — перекрывает токен из settings.json
- `RECEIPT_WORKER_SETTINGS_PATH` — путь к settings.json
- `FNS_MASTER_TOKEN` — мастер-токен ФНС API
- `OCR_LANGUAGES` — языки EasyOCR (по умолчанию `ru`)
- `OCR_QUANTIZE` — квантование модели (1/0, по умолчанию 1)
- `OCR_IN_SUBPROCESS` — OCR в subprocess (1/0, по умолчанию 1)

### Переменные окружения для site_bot (веб-панель)
- `SITE_SESSION_SECRET_KEY` — ключ подписи cookie-сессий (`SessionMiddleware`)
- `SITE_ADMIN_USERNAME` — логин админ-панели (по умолчанию `admin`)
- `SITE_ADMIN_PASSWORD` — пароль админ-панели

Без этих переменных `site_bot/main.py` падает на дефолты из кода (`YOUR_SECRET_KEY_HERE`,
`admin`/`password`) — **небезопасно для прод**. До 2026-08-07 реальные значения на проде
существовали только как незакоммиченный локальный патч поверх `site_bot/main.py` (терялся бы
при `git reset --hard`/чистом клоне). Реальные значения — в `server_access.md` (не в git).
При деплое этой ветки на прод их нужно прописать в `environment=` блока `vodka_site` в
`/etc/supervisor/conf.d/vodka_services.conf` и сделать `supervisorctl update && supervisorctl restart vodka_site`.

---

## Деплой

```
# Установка зависимостей
pip install -r requirements.txt

# Первый запуск — создание БД
python receipt_queue_worker.py --migrate

# Запуск через supervisor
cp new_bot_file/supervisor.conf /etc/supervisor/conf.d/mybot.conf
supervisorctl update && supervisorctl start mybot_bot mybot_site mybot_worker
```

---

## Тесты

```bash
# Запуск всех тестов
cd /Users/romanzhdanov/My_project/VodkaBot/vodka_bot
python -m pytest tests/ -v

# Только быстрые (без сети/OCR)
python -m pytest tests/ -v -m "not slow"
```

Тесты находятся в `tests/`. Покрывают:
- `test_sql_mgt.py` — парсинг схемы, функции without_connection, логика нормализации,
  DAL акций/этапов/правил/чеков (`get_active_stage`, `get_stage_rules`,
  `get_draw_stages`, `save_receipt_items`, `get_receipt_items`), накопительный прогресс
  (`get_user_rule_progress`, `is_stage_winner`, `add_stage_winner`,
  `evaluate_guaranteed_prize_stage`, `evaluate_standard_stage_progress`, `get_stage_progress`,
  `add_manual_receipt_item`), миграции `migrate_prize_draw_rules_draw_to_stage()` и
  `migrate_draw_fields_to_stage()` (пивот на единственный активный этап)
- `test_fns_api.py` — парсинг QR-строк, `_parse_qr_datetime`, `qr_to_params`
- `test_json_data_mgt.py` — TreeObject, дерево меню
- `test_receipt_queue_worker.py` — `_load_settings`, логика воркера (требует pyzbar/easyocr — см. ниже)
- `test_receipt_validation.py` — сопоставление алиасов/OCR-фallback (`receipt_validation.py`),
  включая `match_items_accumulating`, `format_remaining_items`, `compute_entries_count`
  (комплекты условий, не число чеков — дословный пример владельца покрыт отдельным тестом),
  `format_entries_phrase` (русское склонение "N попыток"),
  `build_progress_message`/`build_win_message`/`build_standard_qualify_message`/
  `build_standard_progress_message`
- `test_media_heandler_guaranteed_prize.py` — pure/DB-хелперы накопительного прогресса в
  `media_heandler.py` (`_is_extra_receipt`, `_guaranteed_ocr_rule_id` и т.д.) + end-to-end
  тесты `process_receipt()` с мокнутыми QR/ФНС/OCR на реальной SQLite (требует pyzbar/easyocr
  — см. ниже), включая накопление прогресса, авто-отказ и счётчик попыток для
  `standard`-этапов

- `test_site_bot_progress.py` — веб-часть (`site_bot/main.py`) покрыта минимально: новые
  `_evaluate_standard_stage_progress`/`_get_stage_progress` прямыми вызовами без HTTP-слоя
  (модуль импортируется заново на временную БД через
  `VODKA_DB_PATH`) — сознательное решение, полного тестового покрытия эндпоинтов там нет.
  Исключение — `TestApiDetermineWinnersEntryScoping`: вызывает `api_determine_winners()`
  напрямую как обычную корутину (у неё нет `Depends()`, HTTP-слой не нужен) — регрессия на
  баг с лишними лотерейными билетами, см. "Гарантированный приз" выше.

`test_receipt_queue_worker.py` импортирует `media_heandler.py`, которому нужны `pyzbar`
(нативная либа `zbar`) и `easyocr`/`torch`. На Apple Silicon с Homebrew intel-таском
(`/usr/local`) `pyzbar` может найти x86_64-версию `libzbar.dylib` вместо arm64 —
поставь `zbar` через arm64-Homebrew (`/opt/homebrew/bin/brew install zbar`) и запускай
тесты с `DYLD_LIBRARY_PATH=/opt/homebrew/lib DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`,
если видишь `OSError: ... incompatible architecture`.

---

## Инструкции для Claude

### При изменении схемы БД
1. Правь `table_shem.json` — НЕ пиши SQL вручную
2. Проверь, что `_parse_table_schema` корректно парсит новую строку
3. Обнови тест `tests/test_sql_mgt.py` — добавь проверку новой таблицы/колонки

### При добавлении handler-модуля
1. Создай файл в `heandlers/`
2. Добавь `router = Router()`, `global_objects = None`, `init_object()`
3. Зарегистрируй в `bot.py` → `await init_other_object(new_handler)`
4. Напиши тест с mock `global_objects`

### При изменении fns_api.py
- Всегда запускай `tests/test_fns_api.py` — там критичные парсеры QR-timestamp
- Новые форматы QR добавлять как параметрический тест `@pytest.mark.parametrize`

### Документация
При существенных изменениях архитектуры обновляй этот файл:
- Новая таблица → добавь в раздел "База данных"
- Новый процесс → добавь в раздел "Архитектура: процессы"
- Новый flow → добавь раздел "Поток ..."

### Тесты
- Любая новая чистая функция (без aiogram/sqlite) → покрывай unit-тестом
- Функции с БД — тестируй через in-memory SQLite (`:memory:`)
- Функции с Telegram API — mock через `unittest.mock.AsyncMock`
- Не мокируй `sql_mgt.db_name` глобально — используй `monkeypatch` или передавай `conn`
