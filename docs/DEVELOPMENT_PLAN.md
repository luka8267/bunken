# BUNKEN development plan

This project is a Zotero-like literature manager with a Streamlit web app and
a linked Word add-in.

## Current repositories

- Web app: this repository root.
- Word add-in: sibling `word_addin/word_addin` repository under the user's
  OneDrive documents folder.

## Current architecture

- Streamlit app reads and writes Supabase through `supabase-py`.
- Legacy references live in `papers`.
- Normalized references live in `items`, with related `creators`,
  `attachments`, `item_tags`, and `collection_items`.
- `paper_items_view` is the compatibility read model used by the web app and
  Word add-in.
- Word add-in stores document citation sync data in `documents` and
  `document_citations`.

## Development order

1. Stabilize reference CRUD
   - Add, list, edit, delete references.
   - Verify both legacy `papers` rows and normalized `items` rows.
   - Keep `paper_items_view.id` stable because Word citations store it as
     `paperId`.

2. Stabilize collections
   - Use `collection_items` for item-backed references.
   - Use `collection_papers` only for legacy numeric/non-UUID paper IDs.
   - Confirm collection counts do not double count migrated records.

3. Stabilize tags
   - Confirm tags work for both `paper_tags` and `item_tags`.
   - Keep tag lookup non-fatal so the literature list can render without tags
     if old data is inconsistent.

4. Improve the UI text
   - Replace mojibake labels with readable Japanese.
   - Keep workflows dense and Zotero-like: library list, details, collections,
     tags, attachments.

5. Verify Word add-in integration
   - Confirm login uses the same Supabase project.
   - Confirm `/api/addin/papers` reads from `paper_items_view`.
   - Confirm citation sync writes `documents` and `document_citations`.
   - Confirm UUID-backed and legacy IDs both render and sync.

6. Add tests
   - Unit-test `paper_utils.py` collection/tag routing with mocks.
   - Add focused tests for `collection_items` vs `collection_papers`.
   - Add add-in API tests for `fetch_papers_by_ids` and citation sync payloads.

7. Improve import/export
   - DOI and URL metadata import.
   - RIS/BibTeX import/export.
   - CSL-based citation formatting when the core flows are stable.

## Smoke test checklist

Run this before pushing app changes:

```powershell
python -m py_compile app.py paper_utils.py auth_utils.py
streamlit run app.py
```

Then verify:

- Login.
- Add a reference.
- Open the literature list.
- Add/edit tags.
- Create a collection.
- Add a new reference to a collection.
- Add an existing reference to a collection.
- Open the collection page and confirm counts and rows.
- Attach and replace a PDF or supporting file if the change touches storage.

For the Word add-in repository:

```powershell
python -m py_compile `
  bunkenn\azure-static-web-apps\api\shared\data_access.py `
  bunkenn\azure-static-web-apps\api\shared\bunken_service.py `
  bunkenn\azure-static-web-apps\api\shared\bunken_models.py `
  bunkenn\azure-static-web-apps\api\addin_papers\__init__.py `
  bunkenn\azure-static-web-apps\api\addin_documents_sync\__init__.py
```

Then verify:

- Add-in login.
- Search references.
- Insert citation.
- Refresh bibliography.
- Sync document citations.

## DB change rule

Do not make schema or data changes until a backup has been created and the
restore path is clear. See `docs/DB_BACKUP_RUNBOOK.md`.
