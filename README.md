# bunken

## Development docs

- [Development plan](docs/DEVELOPMENT_PLAN.md)
- [User manual](docs/USER_MANUAL.md)
- [Operations runbook](docs/OPERATIONS_RUNBOOK.md)
- [DB backup runbook](docs/DB_BACKUP_RUNBOOK.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Release checklist](docs/RELEASE_CHECKLIST.md)

## Current feature highlights

- Zotero-style 3-pane literature management with collections, tags, smart
  filters, bulk actions, and PDF ZIP export.
- PDF reading workflow with page rendering, reading notes, citation-planning
  notes, and position-linked rectangle annotations.
- DOI, BibTeX, RIS, PDF, and Chrome extension imports with duplicate checks.
- CSL citation formatting with searchable installed styles.
- Word add-in integration for paper search, citation insertion, locator/page
  edits, multiple-citation editing, bibliography regeneration, and document
  citation sync.

## Local development

Create `.streamlit/secrets.toml`:

```toml
SUPABASE_URL = "https://<project-ref>.supabase.co"
SUPABASE_KEY = "<anon-or-publishable-key>"
PASSWORD_RESET_REDIRECT_URL = "http://localhost:8501" # optional
```

Run checks:

```powershell
python -m py_compile app.py paper_utils.py auth_utils.py tests\test_paper_utils.py
python -m unittest discover -s tests -v
```

Run locally:

```powershell
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

## Operating rule

Before any DB migration, backfill, repair, delete, or bulk update, create a DB
backup from the repository root. Do not use `supabase_migrations/` or
`db_backups/` as the working directory.

## Password reset setup

In Supabase Dashboard > Authentication > URL Configuration, add the app URL to
Redirect URLs. If the reset destination should be explicit, add this Streamlit
secret:

```toml
PASSWORD_RESET_REDIRECT_URL = "https://your-app-url.example.com"
```
