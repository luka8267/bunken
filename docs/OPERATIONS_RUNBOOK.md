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

