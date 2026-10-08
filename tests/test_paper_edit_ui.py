import ast
import importlib
from pathlib import Path
import unittest
from unittest.mock import patch

import paper_utils
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def make_edit_app():
    module = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    functions = [
        node for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"render_paper_edit_form", "normalize_import_year"}
    ]
    script = '''
import re
import streamlit as st
import paper_utils as paper_utils_module
from paper_utils import READING_STATUSES, normalize_doi, normalize_paper_metadata_edit
supabase = object()
SUPPORTING_FILE_TYPES = ["pdf"]
clean_optional_id = lambda value: value
normalize_url = lambda value: value or ""
clear_library_caches = lambda: None
if "test_updates" not in st.session_state:
    st.session_state["test_updates"] = []
def update_paper_details(*args, **kwargs):
    st.session_state["test_updates"].append(kwargs)
''' + ast.unparse(ast.Module(body=functions, type_ignores=[])) + '''
paper = {
    "id": "p1", "item_id": "i1", "title": "Old title", "authors": "Alice, Bob",
    "journal": "Old journal", "year": 2025, "status": "未読", "notes": "note",
}
render_paper_edit_form(paper, "u1", key_prefix="test")
'''
    return AppTest.from_string(script).run()


class PaperEditUITests(unittest.TestCase):
    def test_startup_refreshes_cached_helper_module_once(self):
        module = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        start = next(
            index for index, node in enumerate(module.body)
            if isinstance(node, ast.Import)
            and any(alias.name == "paper_utils" for alias in node.names)
        )
        bootstrap = ast.Module(body=module.body[start:start + 2], type_ignores=[])
        code = compile(bootstrap, str(APP_PATH), "exec")
        original = paper_utils.normalize_paper_metadata_edit
        try:
            del paper_utils.normalize_paper_metadata_edit
            with patch("importlib.reload", wraps=importlib.reload) as reload_module:
                namespace = {}
                exec(code, namespace)
                self.assertTrue(hasattr(namespace["paper_utils_module"], "normalize_paper_metadata_edit"))
                exec(code, {})
                self.assertEqual(reload_module.call_count, 1)
        finally:
            paper_utils.normalize_paper_metadata_edit = original

    def test_renders_core_fields_and_saves_changed_metadata(self):
        app = make_edit_app()
        self.assertFalse(app.exception)
        app.text_area(key="test_title_p1").set_value("Corrected title")
        app.text_area(key="test_authors_p1").set_value("Alice, Carol")
        app.text_input(key="test_journal_p1").set_value("New journal")
        app.text_input(key="test_year_p1").set_value("2026")
        app.button(key="test_save_p1").click().run()
        self.assertFalse(app.exception)
        saved = app.session_state["test_updates"][0]
        self.assertEqual(saved["title"], "Corrected title")
        self.assertEqual(saved["authors"], "Alice, Carol")
        self.assertEqual(saved["journal"], "New journal")
        self.assertEqual(saved["year"], 2026)
        self.assertEqual(app.session_state["post_action_success"], "文献情報を保存しました。")

    def test_title_only_edit_does_not_replace_author_records(self):
        app = make_edit_app()
        app.text_area(key="test_title_p1").set_value("Corrected title")
        app.button(key="test_save_p1").click().run()
        self.assertFalse(app.exception)
        saved = app.session_state["test_updates"][0]
        self.assertNotIn("authors", saved)
        self.assertNotIn("journal", saved)
        self.assertNotIn("year", saved)

    def test_invalid_title_and_year_are_not_saved(self):
        for key, value in (("test_title_p1", " "), ("test_year_p1", "20xx")):
            with self.subTest(key=key):
                app = make_edit_app()
                (app.text_area if "title" in key else app.text_input)(key=key).set_value(value)
                app.button(key="test_save_p1").click().run()
                self.assertFalse(app.exception)
                self.assertTrue(app.error)
                self.assertEqual(app.session_state["test_updates"], [])

    def test_unknown_year_can_be_saved_as_blank(self):
        app = make_edit_app()
        app.text_input(key="test_year_p1").set_value("")
        app.button(key="test_save_p1").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["test_updates"][0]["year"], "")


if __name__ == "__main__":
    unittest.main()
