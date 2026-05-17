import unittest

from postgrest.exceptions import APIError

from paper_utils import (
    fetch_collection_counts,
    fetch_paper_collection_ids,
    get_tag_map_for_papers,
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


if __name__ == "__main__":
    unittest.main()
