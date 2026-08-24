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
EXTRA_RECEIPT_MESSAGE = (
    "❌ Вы уже выполнили условия этой акции — приз уже ваш, этот чек лишний и в розыгрыше "
    "не участвует."
)


def build_progress_message(template: str | None, remaining_items: str) -> str:
    """Подставить {remaining_items} в редактируемый (или дефолтный) шаблон промежуточного
    сообщения гарантированного приза (раздел 4.10 ТЗ). Для standard-этапов используется
    build_standard_progress_message() — у него есть ещё {entries_count}."""
    text = template or DEFAULT_PROGRESS_MESSAGE_TEMPLATE
    return text.replace("{remaining_items}", remaining_items)


def build_win_message(template: str | None) -> str:
    """Текст финального поздравления — редактируемый (или дефолтный, раздел 4.10 ТЗ)."""
    return template or DEFAULT_WIN_MESSAGE


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
DEFAULT_STANDARD_QUALIFY_MESSAGE = (
    "Отлично! Вы выполнили все условия акции и теперь участвуете в розыгрыше приза 🎉\n\n"
    "Каждый следующий подтверждённый чек — ещё один шанс выиграть, можно продолжать. "
    "Сейчас у вас {entries_count} 🎟️\n\n"
    "Победителя определим позже — следите за уведомлениями от бота. Удачи! 🍀"
)


def build_standard_progress_message(
    template: str | None, remaining_items: str, entries_count: int
) -> str:
    """Промежуточное сообщение standard-этапа — остаток товара + текущее число попыток
    (подтверждённых чеков, зачтённых в розыгрыш этого этапа)."""
    text = template or DEFAULT_STANDARD_PROGRESS_MESSAGE_TEMPLATE
    text = text.replace("{remaining_items}", remaining_items)
    return text.replace("{entries_count}", format_entries_phrase(entries_count))


def build_standard_qualify_message(template: str | None, entries_count: int) -> str:
    """Условия standard-этапа выполнены — участник допущен к розыгрышу, но НЕ победитель
    (в отличие от build_win_message для guaranteed_prize, где условия = автопобеда).
    Дальнейшие чеки продолжают копить попытки, поэтому тоже показываем счётчик."""
    text = template or DEFAULT_STANDARD_QUALIFY_MESSAGE
    return text.replace("{entries_count}", format_entries_phrase(entries_count))


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
