"""Tests for receipt_validation.py — rule/alias/quantity matching logic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import receipt_validation as rv


class TestParseAliases:
    def test_splits_on_semicolon(self):
        assert rv.parse_aliases("finsky; фински; финская водка") == [
            "finsky",
            "фински",
            "финская водка",
        ]

    def test_casefolds(self):
        assert rv.parse_aliases("FINSKY") == ["finsky"]

    def test_empty_string_returns_empty_list(self):
        assert rv.parse_aliases("") == []

    def test_none_returns_empty_list(self):
        assert rv.parse_aliases(None) == []

    def test_strips_whitespace_and_drops_empty_parts(self):
        assert rv.parse_aliases(" finsky ; ; фински ") == ["finsky", "фински"]


def _rule(rule_id=1, title="Финская водка", aliases="finsky;фински;финская водка", min_quantity=1, is_active=True):
    return {
        "id": rule_id,
        "title": title,
        "aliases": aliases,
        "min_quantity": min_quantity,
        "is_active": is_active,
    }


class TestMatchItemsAccumulating:
    def test_confirmed_when_one_item_matches_any_active_rule(self):
        items = [{"name": "Водка Finsky 40% 0.5л", "quantity": 1}]
        result = rv.match_items_accumulating(items, [_rule(min_quantity=1)])
        assert result.confirmed is True
        assert result.matched_rule_ids == {1}

    def test_single_receipt_meets_min_quantity_via_one_line(self):
        """min_quantity=3, один чек с quantity=3 в одной строке — засчитывается (раздел 4.6)."""
        items = [{"name": "Водка Finsky", "quantity": 3}]
        result = rv.match_items_accumulating(items, [_rule(min_quantity=3)])
        assert result.confirmed is True
        assert result.item_rule_map == {0: 1}

    def test_quantity_within_single_receipt_irrelevant(self):
        """quantity=1 при min_quantity=3 — всё равно confirmed=True на уровне ОДНОГО чека,
        порог проверяется отдельно через накопленный прогресс (sql_mgt.get_user_rule_progress),
        не здесь (раздел 3.2 ТЗ)."""
        items = [{"name": "Водка Finsky", "quantity": 1}]
        result = rv.match_items_accumulating(items, [_rule(min_quantity=3)])
        assert result.confirmed is True

    def test_not_confirmed_when_no_alias_matches(self):
        items = [{"name": "Хлеб бородинский", "quantity": 1}]
        result = rv.match_items_accumulating(items, [_rule()])
        assert result.confirmed is False
        assert result.matched_rule_ids == set()

    def test_inactive_rule_ignored(self):
        items = [{"name": "Водка Finsky", "quantity": 5}]
        result = rv.match_items_accumulating(items, [_rule(is_active=False)])
        assert result.confirmed is False

    def test_multiple_rules_all_recorded(self):
        items = [
            {"name": "Водка Finsky", "quantity": 1},
            {"name": "Джин Absolut", "quantity": 1},
        ]
        rules = [
            _rule(rule_id=1, aliases="finsky", min_quantity=1),
            _rule(rule_id=2, aliases="absolut", min_quantity=1),
        ]
        result = rv.match_items_accumulating(items, rules)
        assert result.confirmed is True
        assert result.matched_rule_ids == {1, 2}
        assert result.item_rule_map == {0: 1, 1: 2}

    def test_empty_items_not_confirmed(self):
        result = rv.match_items_accumulating([], [_rule()])
        assert result.confirmed is False


class TestFormatRemainingItems:
    def test_single_rule_remaining_one_names_the_item(self):
        """Регрессия: раньше остаток=1 схлопывался в безымянное "1 товар" — пользователь
        не понимал, чего именно не хватает. Теперь формат всегда называет товар."""
        progress = [{"title": "Финская водка", "min_quantity": 1, "progress": 0}]
        assert rv.format_remaining_items(progress) == "• «Финская водка» — ещё 1 шт."

    def test_single_rule_remaining_more_than_one(self):
        progress = [{"title": "Финская водка", "min_quantity": 3, "progress": 1}]
        assert rv.format_remaining_items(progress) == "• «Финская водка» — ещё 2 шт."

    def test_multiple_unfulfilled_rules_all_listed(self):
        progress = [
            {"title": "Водка", "min_quantity": 2, "progress": 0},
            {"title": "Джин", "min_quantity": 1, "progress": 0},
        ]
        text = rv.format_remaining_items(progress)
        assert "«Водка» — ещё 2 шт." in text
        assert "«Джин» — ещё 1 шт." in text

    def test_fulfilled_rules_excluded(self):
        """Одно правило уже выполнено, одно ещё нет — в остатке только невыполненное,
        формат тот же, что и для нескольких правил (единый формат для любого количества)."""
        progress = [
            {"title": "Водка", "min_quantity": 2, "progress": 2},
            {"title": "Джин", "min_quantity": 3, "progress": 1},
        ]
        text = rv.format_remaining_items(progress)
        assert "Водка" not in text
        assert text == "• «Джин» — ещё 2 шт."

    def test_multiple_pending_rules_use_multiline_wording_even_if_others_fulfilled(self):
        progress = [
            {"title": "Водка", "min_quantity": 2, "progress": 2},
            {"title": "Джин", "min_quantity": 1, "progress": 0},
            {"title": "Ром", "min_quantity": 1, "progress": 0},
        ]
        text = rv.format_remaining_items(progress)
        assert "Водка" not in text
        assert "«Джин» — ещё 1 шт." in text
        assert "«Ром» — ещё 1 шт." in text

    def test_all_fulfilled_returns_empty(self):
        progress = [{"title": "Водка", "min_quantity": 1, "progress": 1}]
        assert rv.format_remaining_items(progress) == ""


class TestBuildMessages:
    def test_build_progress_message_uses_default_when_no_template(self):
        text = rv.build_progress_message(None, "1 товар")
        assert "1 товар" in text
        assert text == rv.DEFAULT_PROGRESS_MESSAGE_TEMPLATE.replace("{remaining_items}", "1 товар")

    def test_build_progress_message_uses_custom_template(self):
        text = rv.build_progress_message("Осталось: {remaining_items}!", "2 шт. «Водка»")
        assert text == "Осталось: 2 шт. «Водка»!"

    def test_build_win_message_default(self):
        assert rv.build_win_message(None) == rv.DEFAULT_WIN_MESSAGE

    def test_build_win_message_custom(self):
        assert rv.build_win_message("Ура, вы победили!") == "Ура, вы победили!"

    def test_build_standard_qualify_message_default(self):
        text = rv.build_standard_qualify_message(None, 3)
        assert "{entries_count}" not in text
        assert "3 попытки выиграть" in text

    def test_build_standard_qualify_message_custom(self):
        text = rv.build_standard_qualify_message("Вы участвуете! Билетов: {entries_count}.", 1)
        assert text == "Вы участвуете! Билетов: 1 попытка выиграть."

    def test_standard_qualify_message_default_is_not_win_message(self):
        """Регрессия для качественного различия standard vs guaranteed_prize: дефолтные
        тексты не должны случайно совпасть — иначе стандартный участник решит, что выиграл."""
        assert rv.DEFAULT_STANDARD_QUALIFY_MESSAGE != rv.DEFAULT_WIN_MESSAGE

    def test_default_progress_message_does_not_personify_the_bot(self):
        """Регрессия: раньше текст был "бот досчитает автоматически" — по просьбе владельца
        убрали упоминание бота, заменив на факт (сумма по всем чекам)."""
        assert "бот" not in rv.DEFAULT_PROGRESS_MESSAGE_TEMPLATE.lower()

    def test_build_standard_progress_message_default(self):
        text = rv.build_standard_progress_message(None, "• «Водка» — ещё 1 шт.", 2)
        assert "• «Водка» — ещё 1 шт." in text
        assert "2 попытки выиграть" in text
        assert "бот" not in text.lower()

    def test_build_standard_progress_message_custom_template(self):
        text = rv.build_standard_progress_message(
            "Остаток: {remaining_items}. Попыток: {entries_count}.", "X", 5
        )
        assert text == "Остаток: X. Попыток: 5 попыток выиграть."


class TestComputeEntriesCount:
    def test_no_rules_returns_zero(self):
        assert rv.compute_entries_count([]) == 0

    def test_below_threshold_returns_zero(self):
        assert rv.compute_entries_count([{"progress": 1, "min_quantity": 2}]) == 0

    def test_owner_example_two_receipts_worth_of_progress_is_one_entry(self):
        """Дословный пример владельца: 2 шт. накоплено (двумя чеками), min_quantity=2 —
        это 1 попытка, не 2 (не число чеков, а число собранных комплектов)."""
        assert rv.compute_entries_count([{"progress": 2, "min_quantity": 2}]) == 1

    def test_single_receipt_can_grant_multiple_entries_at_once(self):
        """Один чек с избытком товара сразу даёт несколько попыток — владелец: "третий
        грузанули и там сразу все условия" (комплект не привязан к числу чеков)."""
        assert rv.compute_entries_count([{"progress": 4, "min_quantity": 2}]) == 2

    def test_no_upper_limit(self):
        assert rv.compute_entries_count([{"progress": 30, "min_quantity": 1}]) == 30

    def test_multiple_rules_bottleneck_limits_entries(self):
        """Несколько правил — число комплектов ограничено самым дефицитным (как рецепт:
        сколько раз можно собрать блюдо из того, что есть в наличии)."""
        rule_progress = [
            {"progress": 4, "min_quantity": 2},  # хватило бы на 2 комплекта
            {"progress": 1, "min_quantity": 1},  # но этого — только на 1
        ]
        assert rv.compute_entries_count(rule_progress) == 1


class TestFormatEntriesPhrase:
    @pytest.mark.parametrize(
        "n,expected_word",
        [
            (1, "попытка"),
            (21, "попытка"),
            (2, "попытки"),
            (3, "попытки"),
            (4, "попытки"),
            (22, "попытки"),
            (5, "попыток"),
            (11, "попыток"),
            (12, "попыток"),
            (14, "попыток"),
            (0, "попыток"),
            (100, "попыток"),
        ],
    )
    def test_russian_pluralization(self, n, expected_word):
        phrase = rv.format_entries_phrase(n)
        assert phrase == f"{n} {expected_word} выиграть"


class TestOcrKeywordsForRules:
    def test_includes_only_min_quantity_one_rules(self):
        rules = [_rule(rule_id=1, aliases="finsky", min_quantity=1), _rule(rule_id=2, aliases="vodka2", min_quantity=2)]
        keywords = rv.ocr_keywords_for_rules(rules)
        assert keywords == ["finsky"]

    def test_ignores_inactive_rules(self):
        rules = [_rule(rule_id=1, aliases="finsky", min_quantity=1, is_active=False)]
        assert rv.ocr_keywords_for_rules(rules) == []

    def test_empty_when_no_min_one_rules(self):
        rules = [_rule(rule_id=1, aliases="finsky", min_quantity=3)]
        assert rv.ocr_keywords_for_rules(rules) == []

    def test_aggregates_multiple_rules(self):
        rules = [
            _rule(rule_id=1, aliases="finsky;фински", min_quantity=1),
            _rule(rule_id=2, aliases="absolut", min_quantity=1),
        ]
        keywords = rv.ocr_keywords_for_rules(rules)
        assert keywords == ["finsky", "фински", "absolut"]
