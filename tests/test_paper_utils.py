import unittest

import pandas as pd
from postgrest.exceptions import APIError

from paper_utils import (
    build_document_citation_export_rows,
    delete_user_document,
    fetch_collection_counts,
    fetch_paper_collection_ids,
    filter_document_citations,
    get_document_citation_usage_map,
    get_tag_map_for_papers,
    make_bibtex_entry,
    make_ris_entry,
    make_word_citation,
    replace_tags_for_paper,
    sort_papers_dataframe,
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

    def insert(self, values):
        self.calls.append((self.table_name, "insert", dict(values)))
        self.rows.append(dict(values))
        return self

    def upsert(self, values):
        self.calls.append((self.table_name, "upsert", dict(values)))
        self.rows.append(dict(values))
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

    def test_make_bibtex_entry_includes_publication_metadata(self):
        entry = make_bibtex_entry(
            {
                "authors": "Alpha, Beta",
                "year": 2026,
                "title": "Metadata Test",
                "journal": "Journal",
                "volume": "12",
                "issue": "3",
                "pages": "45-67",
                "doi": "https://doi.org/10.1000/example",
                "url": "https://example.com/paper",
            }
        )

        self.assertIn("@article{Alpha2026Metadata,", entry)
        self.assertIn("author = {Alpha and Beta}", entry)
        self.assertIn("journal = {Journal}", entry)
        self.assertIn("number = {3}", entry)
        self.assertIn("doi = {10.1000/example}", entry)

    def test_make_ris_entry_includes_publication_metadata(self):
        entry = make_ris_entry(
            {
                "authors": "Alpha, Beta",
                "year": 2026,
                "title": "Metadata Test",
                "journal": "Journal",
                "volume": "12",
                "issue": "3",
                "pages": "45-67",
                "doi": "https://doi.org/10.1000/example",
                "url": "https://example.com/paper",
            }
        )

        self.assertIn("TY  - JOUR", entry)
        self.assertIn("AU  - Alpha", entry)
        self.assertIn("AU  - Beta", entry)
        self.assertIn("T2  - Journal", entry)
        self.assertIn("DO  - 10.1000/example", entry)
        self.assertTrue(entry.endswith("ER  -"))

    def test_added_order_defaults_to_newest_first(self):
        df = pd.DataFrame(
            [
                {"id": "old", "display_order": 1},
                {"id": "new", "display_order": 2},
            ]
        )

        sorted_df = sort_papers_dataframe(df, "追加順")

        self.assertEqual(sorted_df["id"].tolist(), ["new", "old"])

    def test_added_order_can_show_oldest_first(self):
        df = pd.DataFrame(
            [
                {"id": "old", "display_order": 1},
                {"id": "new", "display_order": 2},
            ]
        )

        sorted_df = sort_papers_dataframe(df, "追加順", added_oldest_first=True)

        self.assertEqual(sorted_df["id"].tolist(), ["old", "new"])

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

    def test_update_item_details_converts_nan_metadata_to_null(self):
        supabase = FakeSupabase({"items": [{"id": "item-1", "user_id": "u1", "extra": {}}]})

        update_paper_details(
            supabase,
            "u1",
            "paper-1",
            float("nan"),
            float("nan"),
            item_id="item-1",
            doi=float("nan"),
            volume=float("nan"),
            issue="2",
        )

        updates = [call for call in supabase.calls if call[0] == "items" and call[1] == "update"]
        self.assertTrue(updates)
        fields = updates[0][2]
        self.assertEqual(fields["abstract_note"], "")
        self.assertEqual(fields["extra"]["legacy_status"], "")
        self.assertIsNone(fields["doi"])
        self.assertIsNone(fields["volume"])
        self.assertEqual(fields["issue"], "2")

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

    def test_replace_tags_for_item_clears_old_links_and_upserts_new_tags(self):
        supabase = FakeSupabase(
            {
                "paper_tags": [{"paper_id": "legacy-1", "tag_id": "old-paper-tag"}],
                "item_tags": [{"item_id": "item-1", "tag_id": "old-item-tag"}],
                "tags": [{"id": "tag-1", "name": "重要", "user_id": "user-1"}],
            }
        )

        replace_tags_for_paper(
            supabase,
            "user-1",
            "legacy-1",
            "item-1",
            "重要",
        )

        self.assertIn(("paper_tags", "delete"), supabase.calls)
        self.assertIn(("paper_tags", "eq", "paper_id", "legacy-1"), supabase.calls)
        self.assertIn(("item_tags", "delete"), supabase.calls)
        self.assertIn(("item_tags", "eq", "item_id", "item-1"), supabase.calls)
        self.assertIn(
            ("item_tags", "upsert", {"item_id": "item-1", "tag_id": "tag-1"}),
            supabase.calls,
        )

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

    def test_filter_document_citations_searches_context_and_paper_fields(self):
        citations = [
            {
                "rendered_text": "1",
                "context_text": "この論文では相互作用を検討した1)。",
                "citation_items": [{"paperId": "paper-1"}],
            },
            {
                "rendered_text": "2",
                "context_text": "別の引用です2)。",
                "citation_items": [{"paperId": "paper-2"}],
            },
        ]
        paper_map = {
            "paper-1": {"title": "Methyl-pi Interactions", "authors": "Scheiner"},
            "paper-2": {"title": "Halogen Bonding", "authors": "Wang"},
        }

        self.assertEqual(
            filter_document_citations(citations, paper_map, "Scheiner"),
            [citations[0]],
        )
        self.assertEqual(
            filter_document_citations(citations, paper_map, "別の引用"),
            [citations[1]],
        )

    def test_build_document_citation_export_rows_excludes_internal_ids(self):
        rows = build_document_citation_export_rows(
            [
                {
                    "sort_order": 1,
                    "rendered_text": "1",
                    "context_text": "この論文では重要である1)。",
                    "updated_at": "2026-05-17",
                    "citation_items": [
                        {
                            "paperId": "paper-1",
                            "referenceNumber": 1,
                            "locator": "p. 10",
                        }
                    ],
                }
            ],
            {
                "paper-1": {
                    "title": "Title",
                    "authors": "Author",
                    "year": 2026,
                    "journal": "Journal",
                    "doi": "10.1000/example",
                }
            },
        )

        self.assertEqual(rows[0]["引用に使った文"], "この論文では重要である1)。")
        self.assertEqual(rows[0]["文献タイトル"], "Title")
        self.assertNotIn("paper_id", rows[0])
        self.assertNotIn("paperId", rows[0])

    def test_document_citation_usage_map_collects_context_by_paper_id(self):
        supabase = FakeSupabase(
            {
                "documents": [
                    {
                        "id": "doc-1",
                        "user_id": "u1",
                        "title": "Manuscript",
                    }
                ],
                "document_citations": [
                    {
                        "document_id": "doc-1",
                        "rendered_text": "1",
                        "context_text": "この論文では重要である1)。",
                        "updated_at": "2026-05-17",
                        "citation_items": [
                            {
                                "paperId": "paper-1",
                                "referenceNumber": 1,
                                "locator": "p. 10",
                            }
                        ],
                    }
                ],
            }
        )

        usage_map = get_document_citation_usage_map(
            supabase,
            "u1",
            [{"id": "paper-1", "item_id": None}],
        )

        self.assertEqual(usage_map["paper-1"][0]["document_title"], "Manuscript")
        self.assertEqual(usage_map["paper-1"][0]["context_text"], "この論文では重要である1)。")
        self.assertEqual(usage_map["paper-1"][0]["reference_number"], 1)


if __name__ == "__main__":
    unittest.main()
