import ast
from pathlib import Path
import unittest

import pandas as pd
import paper_utils


def load_metadata_functions():
    source = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8"))
    names = {
        "crossref_message_to_metadata", "clean_display_text",
        "get_missing_publication_metadata_fields", "has_missing_publication_metadata",
        "build_existing_doi_metadata_candidates",
    }
    nodes = [node for node in source.body if (
        isinstance(node, ast.FunctionDef) and node.name in names
    ) or (
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "PUBLICATION_METADATA_FIELDS" for target in node.targets)
    )]
    namespace = {
        "paper_utils_module": paper_utils, "pd": pd,
        "normalize_doi": paper_utils.normalize_doi, "clean_optional_id": lambda value: value,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app_metadata", "exec"), namespace)
    return namespace


class ArticleNumberTests(unittest.TestCase):
    def test_crossref_article_number_used_when_page_is_missing(self):
        convert = load_metadata_functions()["crossref_message_to_metadata"]
        for value in (None, "", float("nan"), "nan", "NaN"):
            with self.subTest(page=value):
                self.assertEqual(convert({"page": value, "article-number": "e25338"})[6], "e25338")

    def test_existing_page_range_takes_precedence_over_article_number(self):
        convert = load_metadata_functions()["crossref_message_to_metadata"]
        self.assertEqual(convert({"page": "10-18", "article-number": "e25338"})[6], "10-18")

    def test_pagination_normalization_preserves_electronic_ids(self):
        for value in ("e25338", "125108", "00123", "S10-S18", "10–18"):
            self.assertEqual(paper_utils.normalize_publication_pages(value), value)
        self.assertEqual(paper_utils.normalize_publication_pages(125108.0), "125108")
        for value in (None, float("nan"), pd.NA, "nan", "None", "<NA>"):
            self.assertEqual(paper_utils.normalize_publication_pages(value), "")

    def test_bibtex_eid_is_imported_without_overwriting_pages(self):
        text = '@article{test,\n title = {Title},\n eid = {e25338},\n}\n'
        self.assertEqual(paper_utils.parse_bibtex_entries(text)[0]["pages"], "e25338")
        text = '@article{test,\n title = {Title},\n pages = {10-18},\n eid = {e25338},\n}\n'
        self.assertEqual(paper_utils.parse_bibtex_entries(text)[0]["pages"], "10-18")

    def test_article_number_survives_csl_bibtex_ris_and_reference_output(self):
        row = {"id": "p1", "title": "Title", "authors": "Smith", "journal": "Journal", "year": 2026, "pages": "e25338"}
        self.assertEqual(paper_utils.paper_to_csl_json(row)["page"], "e25338")
        self.assertIn("pages = {e25338}", paper_utils.make_bibtex_entry(row))
        self.assertIn("SP  - e25338", paper_utils.make_ris_entry(row))
        self.assertIn("e25338", paper_utils.make_word_citation_fallback(row))
        for value in ("nan", float("nan")):
            row["pages"] = value
            self.assertNotIn("page", paper_utils.paper_to_csl_json(row))
            for render in (paper_utils.make_bibtex_entry, paper_utils.make_ris_entry, paper_utils.make_word_citation_fallback):
                self.assertNotIn("nan", render(row).lower())

    def test_existing_nan_is_a_metadata_gap_but_manual_correction_is_not(self):
        namespace = load_metadata_functions()
        convert = namespace["crossref_message_to_metadata"]
        namespace["fetch_doi"] = lambda doi: convert({"article-number": "e25338"})
        paper = {"id": "p1", "item_id": "i1", "doi": "10.1002/qua.25338", "pages": "nan", "volume": "117", "issue": "6", "publisher": "Wiley"}
        self.assertIn("pages", dict(namespace["get_missing_publication_metadata_fields"](paper)))
        candidates = namespace["build_existing_doi_metadata_candidates"]([paper])
        self.assertEqual(candidates[0]["candidate"]["pages"], "e25338")
        paper["pages"] = "hand-corrected-article-number"
        self.assertEqual(namespace["build_existing_doi_metadata_candidates"]([paper]), [])


if __name__ == "__main__":
    unittest.main()
