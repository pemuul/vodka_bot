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
| prize_draws | Розыгрыши (start_date, end_date, status: active/finished, `auto_validation_enabled` BOOLEAN DEFAULT 1) |
| prize_draw_stages | Этапы розыгрыша (winners_count) |
| prize_draw_rules | Правила проверки чеков акции (title, sku_code, aliases через `;`, min_quantity, is_active) |
| prize_draw_winners | Победители этапа |
| participant_settings | Настройки участника (blocked, tester) |
| participant_messages | Полный лог диалога бота с пользователем |
| receipts | Загруженные чеки (number, date, amount, qr, status) |
| receipt_ocr_queue | Очередь OCR (pending → processing → done) |
| receipt_items | Товарные позиции чека из ФНС (raw_name, quantity, price, sum, matched_rule_id) |
| images | Загруженные изображения |
| deleted_images | Удалённые изображения |
| notifications | Уведомления для пользователей |

Статусы чека: `не подтвержден` → `подтвержден` / `ошибка` / `дубликат`.
Реально используемые статусы бота: `В авто обработке`, `На ручной проверке`, `Подтверждён`, `Чек уже загружен`, `Нет товара в чеке`, `Ошибка` (см. "Поток обработки чека").

---

## Поток обработки чека

1. Пользователь присылает фото чека в бот (`heandlers/media_heandler.py` → `set_photo()`)
2. Файл сохраняется в `site_bot/static/uploads/`, определяется активная акция (`get_active_draw_id()`)
3. Проверяется `sql_mgt.get_draw_auto_validation(draw_id)` — акции могут отключить авто-проверку
   (checkbox в `/prize-draws`, поле `prize_draws.auto_validation_enabled`, default `1`)
4. **Авто-валидация включена** (или у чека нет акции): статус `"В авто обработке"`,
   запись в `receipt_ocr_queue` (как раньше)
5. **Авто-валидация выключена**: статус `"На ручной проверке"`, чек в очередь **не ставится**
   — ждёт ручной проверки на `/receipts`
6. `receipt_queue_worker.py` подбирает задачу из очереди → `media_heandler.process_receipt()`
7. QR (pyzbar → WeChat QR → enhanced) → дубликат по QR → `"Чек уже загружен"`
8. `fns_api.get_receipt_by_qr()` → SOAP ФНС API; товарные позиции сохраняются в `receipt_items`
9. **Проверка товара** — правила акции (`prize_draw_rules`, таблица `receipts.draw_id` →
   `prize_draw_rules.draw_id`) имеют приоритет над глобальными ключевыми словами:
   - у акции есть активные правила → сопоставление по алиасам (`;`-разделённые варианты
     написания) и `min_quantity` (`receipt_validation.match_items_to_rules()`); совпадение
     и достаточное количество → `"Подтверждён"`, иначе → `"На ручной проверке"`
     (никогда не отклоняется автоматически — принцип «при сомнении на ручную проверку»)
   - у акции нет правил → старое поведение: глобальные `product_keywords` (таблица `params`,
     `user_tg_id=0`), статусы `"Подтверждён"` / `"Нет товара в чеке"`
10. OCR-фallback (если QR не найден или ФНС недоступна): для правил акции используются
    только алиасы правил с `min_quantity == 1` (количество через OCR не проверяется никогда)
11. Обновление статуса чека, уведомление пользователя (кроме `"На ручной проверке"` — ждёт
    администратора на `/receipts`)

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
  DAL акций/правил/чеков (`get_draw_auto_validation`, `get_draw_rules`, `save_receipt_items`, `get_receipt_items`)
- `test_fns_api.py` — парсинг QR-строк, `_parse_qr_datetime`, `qr_to_params`
- `test_json_data_mgt.py` — TreeObject, дерево меню
- `test_receipt_queue_worker.py` — `_load_settings`, логика воркера (требует pyzbar/easyocr — см. ниже)
- `test_receipt_validation.py` — сопоставление алиасов/min_quantity/OCR-фallback (`receipt_validation.py`)

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
