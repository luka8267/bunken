import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests

import bibliography_utils as bibliography
import paper_utils


MESSAGE = {
    "DOI": "10.1021/jp953141+", "title": ["An accurate title"],
    "author": [{"family": "Lo Presti", "given": "Leonardo"}, {"family": "Roux", "given": "Benoît"}],
    "container-title": ["Journal"], "issued": {"date-parts": [[2023]]},
    "published-print": {"date-parts": [[2024]]}, "volume": "30", "issue": "1",
    "page": "1-8", "article-number": "0018", "publisher": "Publisher",
}


class MemoryQuery:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters, self.operation, self.payload, self.columns = [], "select", None, "*"

    def select(self, columns):
        self.columns = columns
        return self

    def eq(self, column, value):
        self.filters.append(lambda row: row.get(column) == value)
        return self

    def in_(self, column, values):
        self.filters.append(lambda row: row.get(column) in values)
        return self

    def gt(self, column, value):
        self.filters.append(lambda row: row.get(column, 0) > value)
        return self

    def order(self, *_args):
        return self

    def limit(self, *_args):
        return self

    def update(self, fields):
        self.operation, self.payload = "update", fields
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def upsert(self, rows, on_conflict):
        self.operation, self.payload, self.conflict = "upsert", rows, on_conflict.split(",")
        return self

    def execute(self):
        rows = self.db.tables[self.table]
        targets = [row for row in rows if all(predicate(row) for predicate in self.filters)]
        if self.operation != "select":
            self.db.events.append(f"{self.table}:{self.operation}")
        if self.operation == "update":
            for row in targets:
                row.update(self.payload)
                row["updated_at"] = "t2"
        elif self.operation == "delete":
            self.db.tables[self.table] = [row for row in rows if row not in targets]
        elif self.operation == "upsert":
            for payload in self.payload:
                existing = next((row for row in rows if all(row.get(key) == payload.get(key) for key in self.conflict)), None)
                if existing:
                    existing.update(payload)
                else:
                    rows.append({"id": f"new-{len(rows)}", **payload})
            targets = rows
        if self.columns != "*":
            targets = [{key: row.get(key) for key in self.columns.split(",")} for row in targets]
        return SimpleNamespace(data=copy.deepcopy(targets))


class MemoryDB:
    def __init__(self):
        self.tables = {
            "items": [{"id": "i1", "user_id": "u1", "title": "An accurate title", "updated_at": "t1", "doi": "10.1021/jp953141", "year": 2023, "publication_title": "Old journal", "abstract_note": "keep my note"}],
            "creators": [{"id": "a1", "item_id": "i1", "creator_type": "author", "position": 1, "literal_name": "Wrong name", "first_name": None, "last_name": None},
                         {"id": "e1", "item_id": "i1", "creator_type": "editor", "position": 1, "literal_name": "Editor"}],
        }
        self.events, self.files = [], {}
        self.storage = SimpleNamespace(from_=lambda bucket: self)

    def table(self, name):
        return MemoryQuery(self, name)

    def upload(self, path, body, options):
        self.events.append("backup:upload")
        self.files[path] = body

    def download(self, path):
        return self.files[path]


def prepared(db):
    paper = {"id": "p1", "item_id": "i1", "title": "An accurate title", "authors": "Wrong name", "doi": "10.1021/jp953141", "updated_at": "t1"}
    review = bibliography.review_paper(paper, bibliography.metadata_from_crossref(MESSAGE))
    return bibliography.prepare_backup(db, "u1", [review])


class BibliographyTests(unittest.TestCase):
    def test_crossref_preserves_structured_names_year_and_article_id(self):
        metadata = bibliography.metadata_from_crossref(MESSAGE)
        self.assertEqual(metadata["authors"], "Lo Presti, Leonardo; Roux, Benoît")
        self.assertEqual(metadata["year"], 2024)
        self.assertEqual(metadata["pages"], "0018")

    def test_canonical_plus_is_accepted_without_losing_it_in_the_url(self):
        response = Mock(status_code=200)
        response.json.return_value = {"message": MESSAGE}
        with patch("bibliography_utils.requests.get", return_value=response) as get:
            metadata = bibliography.fetch_doi_metadata("10.1021/jp953141")
        self.assertEqual(metadata["doi"], "10.1021/jp953141+")
        with patch("bibliography_utils.requests.get", return_value=response) as get:
            bibliography.fetch_doi_metadata("10.1021/jp953141+")
            self.assertIn("%2B", get.call_args.args[0])

    def test_unrelated_canonical_doi_and_title_are_rejected(self):
        response = Mock(status_code=200)
        response.json.return_value = {"message": {**MESSAGE, "DOI": "10.9999/unrelated"}}
        with patch("bibliography_utils.requests.get", return_value=response):
            with self.assertRaises(ValueError):
                bibliography.fetch_doi_metadata("10.1021/jp953141")
        review = bibliography.review_paper({"title": "Completely unrelated biology experiment"}, bibliography.metadata_from_crossref(MESSAGE))
        self.assertEqual(review["changes"], {})

    def test_rate_limits_retry_with_a_bound(self):
        response = Mock(status_code=429, headers={"Retry-After": "1"})
        response.raise_for_status.side_effect = requests.HTTPError("rate limited")
        with patch("bibliography_utils.requests.get", return_value=response) as get, patch("bibliography_utils.time.sleep") as sleep:
            with self.assertRaises(requests.HTTPError):
                bibliography.fetch_doi_metadata("10.1234/test")
            self.assertEqual(get.call_count, 3)
            self.assertEqual(sleep.call_count, 2)

    def test_case_only_doi_differences_and_empty_provider_values_are_not_updates(self):
        review = bibliography.review_paper({"title": "An accurate title", "doi": "10.1234/ABC", "pages": "manual pages"}, {"title": "An accurate title", "doi": "10.1234/abc", "pages": ""})
        self.assertEqual(review["changes"], {})

    def test_backups_precede_writes_and_notes_and_editors_are_untouched(self):
        db = MemoryDB()
        backup = prepared(db)
        result = bibliography.apply_backup(db, "u1", backup)
        self.assertEqual(db.events[0], "backup:upload")
        self.assertEqual(result["outcomes"][0]["status"], "更新済み")
        self.assertEqual(db.tables["items"][0]["abstract_note"], "keep my note")
        self.assertTrue(any(row["creator_type"] == "editor" for row in db.tables["creators"]))
        authors = [row for row in db.tables["creators"] if row["creator_type"] == "author"]
        self.assertEqual(authors[0]["last_name"], "Lo Presti")
        self.assertEqual(authors[1]["first_name"], "Benoît")
        self.assertIn(result["backup_path"], db.files)

    def test_backup_failure_aborts_every_database_write(self):
        db = MemoryDB()
        backup = prepared(db)
        with patch.object(db, "upload", side_effect=RuntimeError("unavailable")):
            with self.assertRaises(RuntimeError):
                bibliography.apply_backup(db, "u1", backup)
        self.assertEqual(db.events, [])

    def test_stale_preview_and_other_users_are_blocked(self):
        db = MemoryDB()
        backup = prepared(db)
        db.tables["items"][0]["updated_at"] = "changed"
        result = bibliography.apply_backup(db, "u1", backup)
        self.assertNotEqual(result["outcomes"][0]["status"], "更新済み")
        self.assertEqual(db.events, ["backup:upload"])
        with self.assertRaises(ValueError):
            bibliography.apply_backup(db, "another-user", backup)

    def test_restore_restores_original_authors_and_preserves_notes_and_new_backup(self):
        db = MemoryDB()
        backup = prepared(db)
        bibliography.apply_backup(db, "u1", backup)
        result = bibliography.restore_backup(db, "u1", backup)
        self.assertEqual(result["restored"], ["i1"])
        self.assertEqual(db.tables["items"][0]["publication_title"], "Old journal")
        self.assertEqual(db.tables["items"][0]["abstract_note"], "keep my note")
        authors = [row for row in db.tables["creators"] if row["creator_type"] == "author"]
        self.assertEqual(len(authors), 1)
        self.assertEqual(authors[0]["literal_name"], "Wrong name")
        self.assertEqual(len(db.files), 2)

    def test_cross_item_restore_and_backup_path_traversal_are_blocked(self):
        db = MemoryDB()
        backup = prepared(db)
        backup["entries"][0]["before"]["authors"][0]["item_id"] = "other-item"
        with self.assertRaises(ValueError):
            bibliography.restore_backup(db, "u1", backup)
        with self.assertRaises(ValueError):
            bibliography.read_backup(db, "u1", "another-user/metadata-backups/test.json")
        self.assertEqual(db.events, [])

    def test_endnote_export_uses_family_given_without_splitting_compound_surnames(self):
        row = {"title": "Title", "authors": "bad old string", "author_list": MESSAGE["author"], "volume": "nan", "publisher": "nan", "doi": "doi.org/10.1021/jp953141%2B"}
        text = paper_utils.make_ris_entry(row)
        self.assertIn("AU  - Lo Presti, Leonardo", text)
        self.assertIn("AU  - Roux, Benoît", text)
        self.assertIn("DO  - 10.1021/jp953141+", text)
        self.assertNotIn("nan", text)
        self.assertEqual(paper_utils.paper_to_csl_json(row)["author"][0]["family"], "Lo Presti")

    def test_updated_authors_are_loaded_structurally_for_exports(self):
        db = MemoryDB()
        bibliography.apply_backup(db, "u1", prepared(db))
        result = SimpleNamespace(data=[{"id": "p1", "item_id": "i1", "title": "Title", "authors": "Leonardo Lo Presti, Benoît Roux"}])
        paper_utils.attach_author_lists(db, result)
        text = paper_utils.make_ris_entry(result.data[0])
        self.assertIn("AU  - Lo Presti, Leonardo", text)
        self.assertIn("AU  - Roux, Benoît", text)

    def test_restore_cannot_overwrite_an_editor_via_a_forged_author_id(self):
        db = MemoryDB()
        backup = prepared(db)
        backup["entries"][0]["before"]["authors"][0]["id"] = "e1"
        with self.assertRaises(ValueError):
            bibliography.restore_backup(db, "u1", backup)
        self.assertEqual(db.events, [])


if __name__ == "__main__":
    unittest.main()
