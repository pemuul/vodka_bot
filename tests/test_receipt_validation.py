"""Tests for receipt_validation.py — rule/alias/quantity matching logic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


class TestMatchItemsToRules:
    def test_confirmed_when_alias_found_min_quantity_one(self):
        items = [{"name": "Водка Finsky 40% 0.5л", "quantity": 1}]
        result = rv.match_items_to_rules(items, [_rule(min_quantity=1)])
        assert result.confirmed is True
        assert result.needs_manual is False
        assert result.matched_rule_id == 1

    def test_confirmed_case_insensitive_alias(self):
        items = [{"name": "ВОДКА ФИНСКАЯ ВОДКА 0.5Л", "quantity": 1}]
        result = rv.match_items_to_rules(items, [_rule(min_quantity=1)])
        assert result.confirmed is True

    def test_needs_manual_when_no_item_matches(self):
        items = [{"name": "Хлеб бородинский", "quantity": 1}]
        result = rv.match_items_to_rules(items, [_rule()])
        assert result.confirmed is False
        assert result.needs_manual is True
        assert result.matched_rule_id is None

    def test_needs_manual_when_quantity_below_min(self):
        items = [{"name": "Водка Finsky", "quantity": 1}]
        result = rv.match_items_to_rules(items, [_rule(min_quantity=2)])
        assert result.confirmed is False
        assert result.needs_manual is True
        assert result.matched_rule_id == 1

    def test_confirmed_when_quantity_meets_min_via_multiple_items(self):
        items = [
            {"name": "Водка Finsky", "quantity": 1},
            {"name": "Водка Finsky", "quantity": 1},
        ]
        result = rv.match_items_to_rules(items, [_rule(min_quantity=2)])
        assert result.confirmed is True

    def test_needs_manual_when_quantity_non_numeric_and_min_above_one(self):
        items = [{"name": "Водка Finsky", "quantity": "н/д"}]
        result = rv.match_items_to_rules(items, [_rule(min_quantity=2)])
        assert result.confirmed is False
        assert result.needs_manual is True

    def test_confirmed_when_quantity_non_numeric_but_min_is_one(self):
        items = [{"name": "Водка Finsky", "quantity": "н/д"}]
        result = rv.match_items_to_rules(items, [_rule(min_quantity=1)])
        assert result.confirmed is True

    def test_inactive_rule_is_ignored(self):
        items = [{"name": "Водка Finsky", "quantity": 5}]
        result = rv.match_items_to_rules(items, [_rule(is_active=False)])
        assert result.confirmed is False
        assert result.needs_manual is True
        assert result.matched_rule_id is None

    def test_empty_items_needs_manual(self):
        result = rv.match_items_to_rules([], [_rule()])
        assert result.confirmed is False
        assert result.needs_manual is True

    def test_item_rule_map_records_matched_index(self):
        items = [{"name": "Водка Finsky", "quantity": 1}]
        result = rv.match_items_to_rules(items, [_rule(rule_id=42)])
        assert result.item_rule_map == {0: 42}

    def test_qty_uses_qty_key_fallback(self):
        items = [{"name": "Водка Finsky", "qty": 3}]
        result = rv.match_items_to_rules(items, [_rule(min_quantity=2)])
        assert result.confirmed is True


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
