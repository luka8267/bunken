# Operations runbook

This project uses Supabase for production data and Streamlit for the web app.
Use this runbook before deployments, migrations, backfills, and incident fixes.

## Environments

- Local app: `.streamlit/secrets.toml`
- Production app: Streamlit/Vercel secrets
- Database: linked Supabase project via Supabase CLI
- Word add-in API: `word_addin` deployment

Do not run DB-changing commands from `supabase_migrations/` or `db_backups/` as
the working directory. Use the repository root.

## Environment variables and secrets

Web app local secrets live in `.streamlit/secrets.toml`:

```toml
SUPABASE_URL = "https://<project-ref>.supabase.co"
SUPABASE_KEY = "<anon-or-publishable-key>"
PASSWORD_RESET_REDIRECT_URL = "http://localhost:8501" # optional
```

Web app production secrets use the same names in Streamlit Cloud. Use an anon or
publishable key only. Do not put a service-role key in Streamlit.

Word add-in production variables live in Vercel:

```text
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=<anon-or-publishable-key>
BUNKEN_ENABLE_DEBUG_ENDPOINTS=false
```

Local shell variables used for maintenance:

```powershell
setx SUPABASE_ACCESS_TOKEN "<sbp_token>"
setx SUPABASE_DB_PASSWORD "<database_password>"
```

After `setx`, open a new terminal. Never commit `.streamlit/secrets.toml`,
Vercel `.env` files, service-role keys, access tokens, or DB passwords.

## Before any DB change

1. Confirm the target project.
   ```powershell
   supabase projects list
   supabase status
   ```
2. Inspect the pending SQL and rollback path.
3. Create a backup using `docs/DB_BACKUP_RUNBOOK.md`.
4. Run the migration in the smallest safe scope.
5. Run verification SQL.
6. Smoke-test the web app and the Word add-in.
7. Commit migration and verification notes.

## Rollback policy

- Prefer a targeted row/table restore from the backup.
- Stop additional writes before restoring if possible.
- Re-run verification SQL after restoring.
- Record the failed migration, timestamp, and restore source.

## User operation backups

Duplicate merges write snapshots to `public.duplicate_merge_backups` before any
metadata transfer or delete happens. Use the app's `重複確認 > 統合履歴・復元`
panel to inspect the keeper and duplicate snapshots.

- The in-app restore returns the kept paper's metadata to the pre-merge snapshot.
- The deleted duplicate can be recreated from the stored `duplicate_snapshot`
  in the same panel.
- Keep RLS enabled on backup tables and grant only the minimum API access needed
  for authenticated users.

## Deployment smoke tests

Web app:

- Login works.
- List filters work.
- Detail tabs render.
- Import preview works without importing duplicates.
- One known citation export works in APA, BibTeX, and RIS.

Word add-in:

- Login works.
- Word-side paper search returns current Supabase data.
- Citation insertion works.
- Reference list regeneration works.
- Citation style switching updates existing citations.
- Document citation sync reports context text counts.

## Monitoring and error triage

When an error appears:

1. Capture the user action, timestamp, and page/menu.
2. Check Streamlit or deployment logs.
3. Check Supabase API/RLS errors.
4. If the error follows a DB change, pause further writes and follow rollback policy.
5. Add a regression test when the failure is reproducible locally.

## Error log locations

Local web app:

```powershell
python -m streamlit run app.py
```

Read the terminal where Streamlit is running. For dependency or syntax failures,
run:

```powershell
python -m py_compile app.py paper_utils.py auth_utils.py tests\test_paper_utils.py
python -m unittest discover -s tests -v
```

Streamlit Cloud:

- Open the app dashboard.
- Use app logs around the user-reported timestamp.
- Check secrets if errors mention missing `SUPABASE_URL` or `SUPABASE_KEY`.

Supabase:

- Dashboard > Logs > API for PostgREST/RLS errors.
- Dashboard > Logs > Auth for login/session errors.
- Dashboard > Logs > Postgres for SQL errors.
- SQL editor for policy and migration verification queries.

Vercel Word add-in:

- Vercel project > Deployments > latest deployment > Functions logs.
- Test:

```powershell
curl.exe -L "https://<vercel-app>.vercel.app/api/addin/papers?_debug=version"
curl.exe -L "https://<vercel-app>.vercel.app/taskpane.html"
```

Word Desktop:

- Clear cache when taskpane JS or manifest changes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Clear-WordAddinCache.ps1 -CloseWord
```

## Release checklist

Run this before merging or pushing a release to `main`:

```powershell
git status --short --branch
python -m py_compile app.py paper_utils.py auth_utils.py tests\test_paper_utils.py
python -m unittest discover -s tests -v
supabase migration list
```

If DB migrations or data changes are included, create a backup first using
`docs/DB_BACKUP_RUNBOOK.md`.

Smoke-test:

- local or deployed login
- 文献一覧 and 3-pane selection
- DOI/metadata buttons open without errors
- import preview opens without accidental import
- PDF読書 opens for a PDF-backed paper
- PDF rectangle annotation can be created and revisited with `ページへ`
- Word add-in login, search, citation insert, reference update

Chrome extension:

```powershell
cd "C:\Users\run_r\OneDrive\ドキュメント\word_addin\word_addin"
node tests\test_chrome_extension.js
node scripts\verify-chrome-extension-real-pages.js
```

Publisher pages can block server-side verification. Treat ACS/ScienceDirect 403
as a site-access limitation, then verify in the browser extension itself.

Supabase advisors:

```powershell
supabase db advisors --linked
```

The currently known remaining warning is `auth_leaked_password_protection`.
Enable it from Supabase Auth settings before public release if possible.
