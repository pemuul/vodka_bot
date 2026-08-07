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


def _item_quantity(item: dict) -> tuple[float | None, bool]:
    """Вернуть (quantity, is_numeric) для позиции чека ФНС."""
    qty = item.get("quantity")
    if qty is None:
        qty = item.get("qty")
    if qty is None:
        return None, False
    try:
        return float(qty), True
    except (TypeError, ValueError):
        return None, False


def _format_qty(value: float) -> str:
    return f"{value:g}"


@dataclass
class MatchResult:
    confirmed: bool
    needs_manual: bool
    matched_rule_id: int | None
    reason: str
    item_rule_map: dict[int, int] = field(default_factory=dict)


def match_items_to_rules(items: list[dict], rules: list[dict]) -> MatchResult:
    """Сопоставить позиции чека (ФНС) с активными правилами акции.

    Правило считается выполненным, если найдена позиция с алиасом и
    (для min_quantity <= 1) сам факт наличия позиции достаточен, либо
    (для min_quantity > 1) суммарное числовое количество позиций >= min_quantity.
    """
    active_rules = [r for r in rules if r.get("is_active", True)]

    item_rule_map: dict[int, int] = {}
    rule_matches: dict[int, dict] = {}

    for rule in active_rules:
        rule_id = rule["id"]
        aliases = parse_aliases(rule.get("aliases"))
        min_quantity = rule.get("min_quantity") or 1
        matched_quantity = 0.0
        quantity_known = True
        matched_any = False

        for idx, item in enumerate(items):
            name = str(item.get("name", "")).casefold()
            if any(alias in name for alias in aliases):
                matched_any = True
                item_rule_map.setdefault(idx, rule_id)
                qty, is_numeric = _item_quantity(item)
                if is_numeric:
                    matched_quantity += qty
                else:
                    quantity_known = False

        if matched_any:
            rule_matches[rule_id] = {
                "title": rule.get("title"),
                "min_quantity": min_quantity,
                "matched_quantity": matched_quantity,
                "quantity_known": quantity_known,
            }

    # Есть ли правило, полностью подтверждённое количеством
    for rule_id, info in rule_matches.items():
        if info["min_quantity"] <= 1:
            qty_ok = True
        else:
            qty_ok = info["quantity_known"] and info["matched_quantity"] >= info["min_quantity"]
        if qty_ok:
            return MatchResult(
                confirmed=True,
                needs_manual=False,
                matched_rule_id=rule_id,
                reason=(
                    f"Бот: товар найден по правилу '{info['title']}' "
                    f"(кол-во {_format_qty(info['matched_quantity'])} >= {info['min_quantity']})"
                ),
                item_rule_map=item_rule_map,
            )

    if rule_matches:
        rule_id, info = next(iter(rule_matches.items()))
        qty_display = _format_qty(info["matched_quantity"]) if info["quantity_known"] else "неизвестно"
        return MatchResult(
            confirmed=False,
            needs_manual=True,
            matched_rule_id=rule_id,
            reason=(
                f"Бот: найден товар по правилу '{info['title']}', "
                f"но количество {qty_display} < {info['min_quantity']} — требуется ручная проверка"
            ),
            item_rule_map=item_rule_map,
        )

    return MatchResult(
        confirmed=False,
        needs_manual=True,
        matched_rule_id=None,
        reason="Бот: товар по правилам акции не найден в данных ФНС — требуется ручная проверка",
        item_rule_map=item_rule_map,
    )


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
