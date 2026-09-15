"""Чистые функции сопоставления товарных позиций чека с правилами акции.

Модуль не тянет тяжёлые зависимости (cv2, pyzbar, ocr), поэтому unit-тесты
логики сопоставления запускаются без них.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def parse_aliases(aliases_str: str | None) -> list[str]:
    """Разбить строку алиасов через ';' на список casefold-строк."""
    if not aliases_str:
        return []
    return [a.strip().casefold() for a in aliases_str.split(";") if a.strip()]


def _format_qty(value: float) -> str:
    return f"{value:g}"


def fill_placeholder(template: str, placeholder: str, value: str) -> str:
    """Подставить значение в шаблон, не оставив висящей разметки при пустом значении.

    Пустым остаток бывает штатно — ровно тогда, когда условия этапа уже выполнены. Наивная
    замена на "" оставляла в тексте заголовок без содержимого («Осталось докупить:» и дальше
    пустота) — на прод это не ушло только потому, что владелец переписал шаблон и выкинул этот
    блок; у любого этапа с дефолтным текстом отправилось бы как есть. Поэтому при пустом
    значении удаляем строку с плейсхолдером целиком, а вместе с ней — предшествующую строку,
    если она выглядит заголовком к нему (заканчивается двоеточием), и схлопываем образовавшиеся
    подряд идущие пустые строки.
    """
    marker = "{" + placeholder + "}"
    if marker not in template:
        return template
    if value:
        return template.replace(marker, value)

    lines = template.split("\n")
    kept: list[str] = []
    for line in lines:
        if marker in line:
            # строка-заголовок прямо над плейсхолдером уходит вместе с ним
            while kept and not kept[-1].strip():
                kept.pop()
            if kept and kept[-1].rstrip().endswith(":"):
                kept.pop()
            continue
        kept.append(line)

    text = "\n".join(kept)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()


@dataclass
class AccumulatingMatchResult:
    confirmed: bool
    item_rule_map: dict[int, int] = field(default_factory=dict)
    matched_rule_ids: set[int] = field(default_factory=set)


def match_items_accumulating(items: list[dict], rules: list[dict]) -> AccumulatingMatchResult:
    """Сопоставить позиции чека с активными правилами этапа (standard и guaranteed_prize).

    Количество товара в рамках ОДНОГО чека не имеет значения — важен только факт, что
    нашёлся товар по алиасам хотя бы одного активного правила. Итоговое количество
    суммируется по всем подтверждённым чекам пользователя отдельно — см.
    sql_mgt.get_user_rule_progress() / evaluate_guaranteed_prize_stage() /
    evaluate_standard_stage_progress().
    """
    active_rules = [r for r in rules if r.get("is_active", True)]
    item_rule_map: dict[int, int] = {}
    matched_rule_ids: set[int] = set()

    for rule in active_rules:
        rule_id = rule["id"]
        aliases = parse_aliases(rule.get("aliases"))
        for idx, item in enumerate(items):
            name = str(item.get("name", "")).casefold()
            if any(alias in name for alias in aliases):
                item_rule_map.setdefault(idx, rule_id)
                matched_rule_ids.add(rule_id)

    return AccumulatingMatchResult(
        confirmed=bool(matched_rule_ids),
        item_rule_map=item_rule_map,
        matched_rule_ids=matched_rule_ids,
    )


DEFAULT_PROGRESS_MESSAGE_TEMPLATE = (
    "Чек принят ✅\n\n"
    "Осталось докупить:\n"
    "{remaining_items}\n\n"
    "Учитывается сумма по всем вашим чекам акции 🧮"
)
DEFAULT_WIN_MESSAGE = (
    "Поздравляем🎉\n"
    "Все условия выполнены – значит, приз скоро будет вашим 🏆\n\n"
    "Мы свяжемся с вами в ближайшее время, чтобы уточнить данные для отправки подарка 🎁\n\n"
    "Спасибо, что вы с нами! 🫶🏻"
)
DEFAULT_EXTRA_RECEIPT_MESSAGE = (
    "Вы уже выполнили все условия акции – приз уже ваш! 🎁\n"
    "Согласно правилам акции, один победитель – один приз.\n"
    "Не волнуйтесь, скоро у нас будут новые розыгрыши. Спасибо, что вы с нами 🫶🏻"
)


def build_progress_message(template: str | None, remaining_items: str) -> str:
    """Подставить {remaining_items} в редактируемый (или дефолтный) шаблон промежуточного
    сообщения гарантированного приза (раздел 4.10 ТЗ). Для standard-этапов используется
    build_standard_progress_message() — у него есть ещё {entries_count}."""
    text = template or DEFAULT_PROGRESS_MESSAGE_TEMPLATE
    return fill_placeholder(text, "remaining_items", remaining_items)


def build_win_message(template: str | None) -> str:
    """Текст финального поздравления — редактируемый (или дефолтный, раздел 4.10 ТЗ)."""
    return template or DEFAULT_WIN_MESSAGE


def build_extra_receipt_message(template: str | None) -> str:
    """Текст для «лишнего» чека — пользователь уже победитель guaranteed_prize-этапа и
    прислал ещё один чек (раздел 4.4/9 ТЗ) — редактируемый (или дефолтный)."""
    return template or DEFAULT_EXTRA_RECEIPT_MESSAGE


def _pluralize_ru(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение по числительному (1 попытка / 2 попытки / 5 попыток)."""
    n_abs = abs(n)
    if n_abs % 100 in (11, 12, 13, 14):
        return many
    last_digit = n_abs % 10
    if last_digit == 1:
        return one
    if 2 <= last_digit <= 4:
        return few
    return many


def format_entries_phrase(entries_count: int) -> str:
    """"N попыток выиграть" с правильным склонением — см. compute_entries_count()."""
    word = _pluralize_ru(entries_count, "попытка", "попытки", "попыток")
    return f"{entries_count} {word} выиграть"


def compute_entries_count(rule_progress: list[dict]) -> int:
    """Число полных "комплектов" условий этапа, накопленных пользователем, — это и есть
    попытки выиграть для standard-этапа (уточнение владельца: "не просто каждый чек, а
    группа чеков от 1 и более в совокупности проходящая валидацию"). НЕ равно числу чеков:
    несколько чеков могут в сумме дать только один комплект (например: чек 1 = 1 шт., чек
    2 = 1 шт., при min_quantity=2 — вместе это 1 комплект/попытка), а один чек с достаточным
    количеством может сразу дать несколько комплектов (чек на 4 шт. при min_quantity=2 —
    сразу 2 комплекта). Если правил несколько — число комплектов ограничено самым
    дефицитным правилом (аналог "сколько раз можно собрать рецепт из того, что накопили").
    Не персонализирует "чек" в тексте сообщений — комплект может состоять из любого числа
    чеков, в т.ч. одного.
    """
    if not rule_progress:
        return 0
    return min(int(rp["progress"] // rp["min_quantity"]) for rp in rule_progress)


# standard: чем больше накоплено комплектов условий — тем больше шансов (каждый комплект =
# билет), в отличие от guaranteed_prize, где выполнение условий = гарантированная победа.
DEFAULT_STANDARD_PROGRESS_MESSAGE_TEMPLATE = (
    "Чек принят ✅\n\n"
    "Осталось докупить:\n"
    "{remaining_items}\n\n"
    "Учитывается сумма по всем вашим чекам акции 🧮\n"
    "Каждый подтверждённый чек — отдельный шанс выиграть. Сейчас у вас {entries_count} 🎟️"
)


def build_standard_progress_message(
    template: str | None, remaining_items: str, entries_count: int
) -> str:
    """Сообщение о принятом чеке на standard-этапе — остаток товара (если он есть) + текущее
    число попыток. Шлётся и когда условия ещё не выполнены, и когда уже выполнены: во втором
    случае остаток пуст и блок про него схлопывается (см. fill_placeholder)."""
    text = template or DEFAULT_STANDARD_PROGRESS_MESSAGE_TEMPLATE
    text = fill_placeholder(text, "remaining_items", remaining_items)
    return fill_placeholder(text, "entries_count", format_entries_phrase(entries_count))


# ---------------------------------------------------------------------------
# Единый источник «статус чека → текст пользователю».
#
# Раньше таблица дублировалась в боте (media_heandler) и в панели (site_bot/main.py), и в
# каждой был свой набор статусов: «На ручной проверке» и «Ошибка» не отправляли пользователю
# вообще ничего — чек молча повисал до тех пор, пока админ случайно не заметит его в списке
# (на проде такие чеки ждали ответа до 17 часов). Теперь список один, и тест следит, чтобы у
# каждого статуса из FINAL_RECEIPT_STATUSES был непустой текст.
# ---------------------------------------------------------------------------
MESSAGE_RECEIPT_CONFIRMED = "✅ Чек подтверждён"
MESSAGE_DUPLICATE_RECEIPT = "❌ Чек уже загружен"
MESSAGE_NO_GOODS = "❌ В чеке не найден нужный товар"

STATUS_USER_MESSAGES: dict[str, str] = {
    "Подтверждён": MESSAGE_RECEIPT_CONFIRMED,
    "Чек уже загружен": MESSAGE_DUPLICATE_RECEIPT,
    "Нет товара в чеке": MESSAGE_NO_GOODS,
}

# Статусы, в которых пользователю НАМЕРЕННО ничего не отправляется — решение владельца
# проекта, зафиксированное в CLAUDE.md («Поток обработки чека», п. 14): чек ждёт
# администратора на /receipts, и человек получит ответ тогда, когда решение действительно
# будет принято. Промежуточное «мы посмотрим» тут только плодит лишнее сообщение и обещание
# срока, который никто не гарантировал.
#
# Поэтому чек, ушедший на ручную проверку, не должен теряться у АДМИНИСТРАТОРА — это и есть
# настоящее лекарство от «чек висит без ответа». Раньше он не попадал в ленту уведомлений
# (/api/notifications отбирал только статус «Ошибка», который с переездом правил на этап
# больше не выставляется), и заметить его было неоткуда — см. site_bot/main.py.
SILENT_RECEIPT_STATUSES: frozenset[str] = frozenset({
    "На ручной проверке",
    "Ошибка",
})

# Статусы, в которых обработка чека завершена. Либо у статуса есть текст, либо он явно
# помечен «молчим» — третьего быть не должно, это проверяет тест.
# «В авто обработке» сюда не входит — промежуточное состояние, ответ придёт позже.
# «Лишний чек» тоже: он отправляется отдельным редактируемым текстом этапа ещё в set_photo().
FINAL_RECEIPT_STATUSES: tuple[str, ...] = (
    "Подтверждён",
    "Чек уже загружен",
    "Нет товара в чеке",
    "На ручной проверке",
    "Ошибка",
)


def build_status_message(status: str | None) -> str | None:
    """Текст пользователю по финальному статусу чека. None — отправлять нечего."""
    if not status:
        return None
    return STATUS_USER_MESSAGES.get(status)


def is_silent_status(status: str | None) -> bool:
    """True, если по этому статусу пользователю намеренно ничего не пишут (см.
    SILENT_RECEIPT_STATUSES). Нужно, чтобы отличать осознанное молчание от статуса, для
    которого текст просто забыли добавить, — второе пишется в лог как ошибка."""
    return status in SILENT_RECEIPT_STATUSES


def is_contradictory_acceptance(
    status: str | None, rule_progress: list[dict] | None
) -> bool:
    """True, если чек подтверждён по правилам этапа, но его вклад в прогресс нулевой.

    Именно это ушло живому человеку трижды подряд 14.09.2026: чек получил статус «Подтверждён»,
    а накопленный прогресс так и остался нулевым (позиция была записана без количества) — и в
    текст подставилось «0 попыток выиграть». Причину устранили, но две половины фразы
    по-прежнему считаются разными запросами: статус пишется одним, прогресс другим, и ничто не
    обязывает их сойтись. Поэтому расхождение проверяется явно.

    Ноль попыток сам по себе — нормальное состояние: при min_quantity = 3 и одном купленном
    товаре комплект ещё не собран, и «осталось докупить 2 шт., попыток пока 0» — честный текст.
    Противоречие именно в том, что чек засчитан, а прогресс по ВСЕМ правилам нулевой: такого
    после подтверждения быть не может, потому что статус пишется до пересчёта и собственные
    позиции чека уже должны в нём учитываться.
    """
    if status != "Подтверждён" or not rule_progress:
        return False
    return all((rp.get("progress") or 0) <= 0 for rp in rule_progress)


def format_remaining_items(rule_progress: list[dict]) -> str:
    """Собрать текст остатка товара для промежуточного сообщения (раздел 3.5/4.10 ТЗ).

    rule_progress — список правил этапа с полями title/min_quantity/progress. Учитывает
    только ещё не выполненные правила (progress < min_quantity); остаток — это КОЛИЧЕСТВО
    товара, а не число чеков (пользователь может закрыть весь остаток одним чеком).

    Формат одинаковый для одного и нескольких правил — построчный список, всегда с
    названием товара (раньше единственный недостающий товар с остатком=1 схлопывался в
    безымянное "1 товар", из-за чего пользователь не понимал, чего именно не хватает).
    """
    pending = [
        rp for rp in rule_progress if rp["progress"] < rp["min_quantity"]
    ]
    if not pending:
        return ""

    lines = []
    for rp in pending:
        remaining = rp["min_quantity"] - rp["progress"]
        lines.append(f"• «{rp['title']}» — ещё {_format_qty(remaining)} шт.")
    return "\n".join(lines)


def ocr_keywords_for_rules(rules: list[dict]) -> list[str]:
    """Алиасы активных правил с min_quantity == 1 (единственные, что можно подтвердить через OCR)."""
    keywords: list[str] = []
    for rule in rules:
        if not rule.get("is_active", True):
            continue
        min_quantity = rule.get("min_quantity") or 1
        if min_quantity != 1:
            continue
        keywords.extend(parse_aliases(rule.get("aliases")))
    return keywords
