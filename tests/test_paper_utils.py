import unittest

from postgrest.exceptions import APIError

from paper_utils import (
    delete_user_document,
    fetch_collection_counts,
    fetch_paper_collection_ids,
    get_tag_map_for_papers,
    make_word_citation,
    strip_metadata_columns,
    update_paper_details,
)


class Result:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, table_name, rows, calls, failures):
        self.table_name = table_name
        self.rows = list(rows)
        self.calls = calls
        self.failures = failures

    def select(self, *_args):
        return self

    def update(self, values):
        self.calls.append((self.table_name, "update", dict(values)))
        return self

    def delete(self):
        self.calls.append((self.table_name, "delete"))
        return self

    def eq(self, column, value):
        self.calls.append((self.table_name, "eq", column, value))
        self.rows = [row for row in self.rows if row.get(column) == value]
        return self

    def in_(self, column, values):
        values = set(values)
        self.calls.append((self.table_name, "in", column, tuple(sorted(values))))
        self.rows = [row for row in self.rows if row.get(column) in values]
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        failure = self.failures.get(self.table_name)
        if failure:
            raise failure
        return Result(self.rows)


class FakeSupabase:
    def __init__(self, tables, failures=None):
        self.tables = tables
        self.failures = failures or {}
        self.calls = []

    def table(self, name):
        return Query(name, self.tables.get(name, []), self.calls, self.failures)


class PaperUtilsCollectionTests(unittest.TestCase):
    def test_strip_metadata_columns_keeps_legacy_view_columns(self):
        columns = (
            "id, item_id, title, authors, journal, year, doi, url, volume, issue, "
            "pages, publisher, item_type, status, notes"
        )

        self.assertEqual(
            strip_metadata_columns(columns),
            "id, item_id, title, authors, journal, year, doi, url, status, notes",
        )

    def test_make_word_citation_includes_publication_metadata(self):
        citation = make_word_citation(
            {
                "authors": "Alpha",
                "year": 2026,
                "title": "Metadata Test",
                "journal": "Journal",
                "volume": "12",
                "issue": "3",
                "pages": "45-67",
                "doi": "10.1000/example",
            },
            style="APA",
        )

        self.assertIn("Journal, 12(3), 45-67", citation)
        self.assertIn("https://doi.org/10.1000/example", citation)

    def test_update_legacy_paper_details_can_edit_doi(self):
        supabase = FakeSupabase({"papers": [{"id": "p1", "user_id": "u1"}]})

        update_paper_details(
            supabase,
            "u1",
            "p1",
            "未読",
            "note",
            doi="10.1000/example",
        )

        self.assertIn(
            (
                "papers",
                "update",
                {"status": "未読", "notes": "note", "doi": "10.1000/example"},
            ),
            supabase.calls,
        )

    def test_update_item_details_can_clear_doi(self):
        supabase = FakeSupabase({"items": [{"id": "item-1", "user_id": "u1", "extra": {}}]})

        update_paper_details(
            supabase,
            "u1",
            "paper-1",
            "未読",
            "note",
            item_id="item-1",
            doi="",
        )

        updates = [call for call in supabase.calls if call[0] == "items" and call[1] == "update"]
        self.assertTrue(updates)
        self.assertIsNone(updates[0][2]["doi"])

    def test_uuid_paper_id_uses_collection_items_only(self):
        supabase = FakeSupabase(
            {
                "collection_papers": [{"collection_id": "legacy", "paper_id": 123}],
                "collection_items": [{"collection_id": "c1", "item_id": "item-1"}],
            }
        )

        result = fetch_paper_collection_ids(
            supabase,
            "cf7d05d5-d339-4c52-8f32-4e52bb0ad899",
            "item-1",
        )

        self.assertEqual(result, ["c1"])
        self.assertFalse(
            any(call[0] == "collection_papers" for call in supabase.calls),
            "UUID-backed items must not query legacy collection_papers.paper_id",
        )

    def test_legacy_paper_id_uses_collection_papers(self):
        supabase = FakeSupabase(
            {
                "collection_papers": [{"collection_id": "legacy", "paper_id": "123"}],
                "collection_items": [],
            }
        )

        result = fetch_paper_collection_ids(supabase, "123")

        self.assertEqual(result, ["legacy"])
        self.assertTrue(any(call[0] == "collection_papers" for call in supabase.calls))

    def test_collection_counts_dedupe_migrated_legacy_items(self):
        supabase = FakeSupabase(
            {
                "collection_papers": [{"collection_id": "c1", "paper_id": "p1"}],
                "collection_items": [
                    {"collection_id": "c1", "item_id": "i1"},
                    {"collection_id": "c1", "item_id": "i2"},
                ],
                "items": [
                    {
                        "id": "i1",
                        "legacy_source": "papers",
                        "legacy_paper_id": "p1",
                    },
                    {
                        "id": "i2",
                        "legacy_source": None,
                        "legacy_paper_id": None,
                    },
                ],
            }
        )

        self.assertEqual(fetch_collection_counts(supabase, ["c1"]), {"c1": 2})

    def test_invalid_item_tag_id_does_not_break_tag_map(self):
        supabase = FakeSupabase(
            {
                "paper_tags": [],
                "item_tags": [{"item_id": "item-1", "tag_id": "not-a-uuid"}],
                "tags": [],
            }
        )

        self.assertEqual(get_tag_map_for_papers(supabase, [{"item_id": "item-1"}]), {})

    def test_tag_api_error_keeps_list_rendering(self):
        supabase = FakeSupabase(
            {
                "paper_tags": [],
                "item_tags": [],
                "tags": [],
            },
            failures={"paper_tags": APIError({"message": "simulated failure"})},
        )

        self.assertEqual(get_tag_map_for_papers(supabase, [{"id": "1"}]), {})

    def test_delete_user_document_removes_citations_then_document(self):
        supabase = FakeSupabase(
            {
                "document_citations": [{"document_id": "doc-1"}],
                "documents": [{"id": "doc-1", "user_id": "u1"}],
            }
        )

        delete_user_document(supabase, "u1", "doc-1")

        self.assertEqual(
            supabase.calls,
            [
                ("document_citations", "delete"),
                ("document_citations", "eq", "document_id", "doc-1"),
                ("documents", "delete"),
                ("documents", "eq", "id", "doc-1"),
                ("documents", "eq", "user_id", "u1"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
