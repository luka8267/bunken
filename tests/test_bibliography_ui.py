import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import bibliography_utils as bibliography
from test_bibliography_utils import MESSAGE


PAPER = {"id": "p1", "item_id": "i1", "title": "An accurate title", "authors": "Wrong name", "doi": "10.1021/jp953141", "updated_at": "t1"}
SCRIPT = '''
import streamlit as st
from bibliography_ui import render_bibliography_review
from test_bibliography_utils import MemoryDB
if "db" not in st.session_state:
    st.session_state["db"] = MemoryDB()
records = [{"id": "p1", "item_id": "i1", "title": "An accurate title", "authors": "Wrong name", "doi": "10.1021/jp953141", "updated_at": "t1"}]
render_bibliography_review.__wrapped__(st.session_state["db"], "u1", records, lambda: None)
'''


class BibliographyUITests(unittest.TestCase):
    def test_network_requires_consent_and_updates_require_backup_and_confirmation(self):
        review = bibliography.review_paper(PAPER, bibliography.metadata_from_crossref(MESSAGE))
        with patch("bibliography_ui.bibliography.build_review", return_value=[review]) as fetch:
            app = AppTest.from_string(SCRIPT).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.button(key="bibliography_review_u1_fetch").disabled)
            fetch.assert_not_called()
            app.checkbox(key="bibliography_review_u1_consent").check().run()
            app.button(key="bibliography_review_u1_fetch").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["db"].events, [])
            app.checkbox(key="bibliography_review_u1_all").check().run()
            app.button(key="bibliography_review_u1_prepare").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["db"].events, [])
            self.assertTrue(app.button(key="bibliography_review_u1_apply").disabled)
            confirmation = next(box for box in app.checkbox if box.label.startswith("差分とバックアップ"))
            confirmation.check().run()
            app.button(key="bibliography_review_u1_apply").click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            self.assertEqual(app.session_state["db"].events[0], "backup:upload")
            self.assertEqual(app.session_state["db"].tables["items"][0]["doi"], "10.1021/jp953141+")
            self.assertEqual(app.session_state["bibliography_review_u1"]["result"]["outcomes"][0]["status"], "更新済み")

    def test_changed_selection_requires_new_backup(self):
        review = bibliography.review_paper(PAPER, bibliography.metadata_from_crossref(MESSAGE))
        with patch("bibliography_ui.bibliography.build_review", return_value=[review]):
            app = AppTest.from_string(SCRIPT).run()
            app.checkbox(key="bibliography_review_u1_consent").check().run()
            app.button(key="bibliography_review_u1_fetch").click().run()
            app.checkbox(key="bibliography_review_u1_all").check().run()
            app.button(key="bibliography_review_u1_prepare").click().run()
            self.assertIn("backup", app.session_state["bibliography_review_u1"])
            app.multiselect(key="bibliography_review_u1_fields").set_value(["title"]).run()
            self.assertFalse(app.exception)
            self.assertNotIn("backup", app.session_state["bibliography_review_u1"])
            self.assertEqual(app.session_state["db"].events, [])


if __name__ == "__main__":
    unittest.main()
