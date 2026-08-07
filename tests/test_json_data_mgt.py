"""Tests for json_data_mgt.py — TreeObject and menu tree logic."""

import json
import os
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from json_data_mgt import TreeObject, Tree_data, create_folder


# ---------------------------------------------------------------------------
# TreeObject unit tests
# Note: TreeObject.__init__ only sets key/text/media/item_id via load_data_from_dict.
# next_layers is populated externally by Tree_data._create_tree_obj, so tests
# for children use Tree_data as the factory.
# ---------------------------------------------------------------------------

LEAF_NODE_DATA = {
    "text": "Добро пожаловать!",
    "media": "photo.jpg",
    "id": "root_id",
    "redirect": None,
}


class TestTreeObjectInit:
    def test_loads_text(self):
        node = TreeObject("root", LEAF_NODE_DATA)
        assert node.text == "Добро пожаловать!"

    def test_loads_key(self):
        node = TreeObject("root", LEAF_NODE_DATA)
        assert node.key == "root"

    def test_loads_media(self):
        node = TreeObject("root", LEAF_NODE_DATA)
        assert node.media == "photo.jpg"

    def test_loads_item_id(self):
        node = TreeObject("root", LEAF_NODE_DATA)
        assert node.item_id == "root_id"

    def test_text_none_when_absent(self):
        data = {"media": "img.jpg"}
        node = TreeObject("x", data)
        assert node.text is None

    def test_media_none_when_absent(self):
        data = {"text": "hello"}
        node = TreeObject("x", data)
        assert node.media is None

    def test_item_id_none_when_absent(self):
        data = {"text": "hello"}
        node = TreeObject("x", data)
        assert node.item_id is None


# ---------------------------------------------------------------------------
# Tree_data — loads from JSON file in the correct flat-key format
# ---------------------------------------------------------------------------

def _write_tree_json(tmp_path, data: dict) -> str:
    """Write tree JSON to a temp file and return its path."""
    f = tmp_path / "tree.json"
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(f)


class TestTreeData:
    def test_loads_root_text(self, tmp_path):
        data = {
            "text": "Главное меню",
            "media": None,
            "item_1": {
                "text": "Раздел 1",
                "media": None,
            }
        }
        path = _write_tree_json(tmp_path, data)
        td = Tree_data(path)
        assert td.tree_obj.text == "Главное меню"

    def test_children_created_from_non_special_keys(self, tmp_path):
        data = {
            "text": "Root",
            "media": None,
            "child_a": {"text": "A"},
            "child_b": {"text": "B"},
        }
        path = _write_tree_json(tmp_path, data)
        td = Tree_data(path)
        names = list(td.tree_obj.next_layers.keys())
        assert "child_a" in names
        assert "child_b" in names

    def test_special_words_not_children(self, tmp_path):
        # Only include special keys that don't trigger validation errors:
        # - "redirect" key presence (even None) is treated as a redirect node by the validator
        # - "id: None" is safe to include
        data = {
            "text": "Root",
            "media": "img.jpg",
            "id": None,
            "real_child": {"text": "Child"},
        }
        path = _write_tree_json(tmp_path, data)
        td = Tree_data(path)
        names = list(td.tree_obj.next_layers.keys())
        assert "real_child" in names
        assert "text" not in names
        assert "media" not in names
        assert "id" not in names

    def test_child_text_accessible(self, tmp_path):
        data = {
            "text": "Root",
            "child_x": {"text": "Child X"},
        }
        path = _write_tree_json(tmp_path, data)
        td = Tree_data(path)
        child = td.tree_obj.next_layers["child_x"]
        assert child.text == "Child X"

    def test_empty_tree_no_children(self, tmp_path):
        data = {"text": "Empty"}
        path = _write_tree_json(tmp_path, data)
        td = Tree_data(path)
        assert len(td.tree_obj.next_layers) == 0

    def test_deep_nesting(self, tmp_path):
        data = {
            "text": "L1",
            "l2": {
                "text": "L2",
                "l3": {
                    "text": "L3",
                }
            }
        }
        path = _write_tree_json(tmp_path, data)
        td = Tree_data(path)
        l3 = td.tree_obj.next_layers["l2"].next_layers["l3"]
        assert l3.text == "L3"

    def test_get_obj_from_path(self, tmp_path):
        data = {
            "text": "Root",
            "section": {
                "text": "Section",
            }
        }
        path = _write_tree_json(tmp_path, data)
        td = Tree_data(path)
        obj = td.get_obj_from_path("/-/section")
        assert obj.text == "Section"

    def test_id_registered_in_id_dict(self, tmp_path):
        data = {
            "text": "Root",
            "promo": {
                "id": "promo_section",
                "text": "Акции",
            }
        }
        path = _write_tree_json(tmp_path, data)
        td = Tree_data(path)
        assert "promo_section" in td.id_dict

    def test_duplicate_id_raises(self, tmp_path):
        from exception_error_json_tree import ValidJSONData
        data = {
            "text": "Root",
            "a": {"id": "dup", "text": "A"},
            "b": {"id": "dup", "text": "B"},
        }
        path = _write_tree_json(tmp_path, data)
        # check_json_file_valid catches IdAlreadyExists internally and re-raises ValidJSONData
        with pytest.raises(ValidJSONData):
            Tree_data(path)


# ---------------------------------------------------------------------------
# create_folder helper
# ---------------------------------------------------------------------------

class TestCreateFolder:
    def test_creates_new_folder(self, tmp_path):
        target = str(tmp_path / "new_subfolder")
        assert not os.path.exists(target)
        create_folder(target)
        assert os.path.isdir(target)

    def test_existing_folder_not_raises(self, tmp_path):
        target = str(tmp_path / "existing")
        os.makedirs(target)
        create_folder(target)
        assert os.path.isdir(target)
