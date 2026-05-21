# User manual

This is the daily-use guide for the bunken literature manager.

## Login

Open the Streamlit app and log in with your bunken account. Password reset uses
the Supabase redirect URL configured in production.

## Add papers

Use `追加` to add papers by:

- DOI
- URL metadata
- manual entry
- PDF upload
- supporting file upload

Use tags and reading status when adding a paper if you already know how it
should be organized.

## Manage the library

Use `一覧` for normal library work.

- Left pane: collection, tag, and smart filters.
- Center pane: paper list and quick status changes.
- Right pane: overview, PDF, reading notes, tags, citation export, Word usage,
  and editing.

Useful smart filters:

- DOIなし
- PDFなし
- PDFあり
- 未読
- 引用予定
- メタデータ不足

## Read PDFs

Use `PDF読書` for a reading-focused workflow.

- Select a PDF-backed paper.
- Adjust page, zoom, and viewer height.
- Save basic notes, PDF reading notes, and citation-planning notes.
- Quickly mark papers as 読書中, 読了, or 引用予定.

If a paper has no PDF, open its edit tab and upload one.

## Import papers

Use `インポート` for:

- BibTeX
- RIS
- DOI list
- PDF files

Before importing, review the editable preview table. Missing fields and
duplicate candidates are shown. For duplicates, choose:

- スキップ
- 既存を更新
- 別文献として追加

## Improve data quality

Use `一覧` actions for DOI acquisition and metadata completion.

Use `重複確認` for:

- author and journal normalization candidates
- duplicate detection
- field-by-field merge choices
- merge history
- restore of kept paper metadata
- recreation of deleted duplicate snapshots

## Word add-in workflow

In Word:

1. Open bunken Word.
2. Log in.
3. Search by title, author, journal, DOI, year, tag, or collection.
4. Select a paper.
5. Insert a citation.
6. Update the reference list.
7. Use the document citation panel to check synced citations.

In the web app, open `文書引用` to see which Word documents use each paper and
the text around each citation.

## Export

From `一覧`, `コレクション`, or a selected paper:

- export Word references
- export BibTeX
- export RIS
- export citation usage CSV from `文書引用`

## Troubleshooting

If the web app shows an error:

1. Retry once.
2. Note the menu, action, and time.
3. If it happened after a DB change, stop further changes.
4. Check `docs/OPERATIONS_RUNBOOK.md`.

If the Word add-in shows old UI or 404:

1. Close Word.
2. Clear the Office add-in cache.
3. Reopen Word and load the shared-folder or production manifest again.
