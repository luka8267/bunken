# DB backup runbook

Use this before any Supabase schema change, migration, data repair, backfill, or
delete/update operation.

Run every command from the repository root. Do not use `supabase_migrations/` or
`db_backups/` as the working directory.

## Tables to protect

For this app, back up at least these tables before DB changes:

- `profiles`
- `papers`
- `items`
- `creators`
- `attachments`
- `tags`
- `paper_tags`
- `item_tags`
- `collections`
- `collection_papers`
- `collection_items`
- `documents`
- `document_citations`

If a change touches storage paths, also record the affected Storage bucket paths
from `papers.pdf_path`, `papers.supporting_path`, and `attachments.storage_path`.

## Backup naming

Save backup files under `db_backups/`, which is ignored by Git.

Recommended names:

```text
db_backups/backup_YYYYMMDD_HHMM_before_<change_name>.sql
db_backups/backup_YYYYMMDD_HHMM_before_<change_name>_data.sql
db_backups/backup_YYYYMMDD_HHMM_before_<change_name>_manifest.txt
```

## Full remote backup

Use this for schema changes, migrations, and risky repairs:

```powershell
$stamp = Get-Date -Format "yyyyMMdd_HHmm"
$name = "before_<change_name>"
New-Item -ItemType Directory -Force db_backups | Out-Null
supabase db dump --linked --file "db_backups/backup_${stamp}_${name}.sql"
supabase db dump --linked --data-only --use-copy --file "db_backups/backup_${stamp}_${name}_data.sql"
supabase migration list > "db_backups/backup_${stamp}_${name}_manifest.txt"
git rev-parse HEAD >> "db_backups/backup_${stamp}_${name}_manifest.txt"
```

Use a specific password only when the CLI prompts or your environment requires
it:

```powershell
supabase db dump --linked --password "$env:SUPABASE_DB_PASSWORD" --file "db_backups/backup_${stamp}_${name}.sql"
```

Never commit files under `db_backups/`.

## Targeted table backup

Use this before a narrow data repair where full backup is unnecessary but a
rollback source is still required:

```powershell
$stamp = Get-Date -Format "yyyyMMdd_HHmm"
$name = "before_<change_name>"
supabase db dump --linked --data-only --use-copy --schema public --file "db_backups/backup_${stamp}_${name}_public_data.sql"
```

If the change touches only a few rows, also save a SQL or CSV note with:

- the exact `where` clause
- the expected row count
- the verification query
- the restore query

## Minimum preflight

Before changing data:

1. Confirm the target Supabase project.
2. Confirm the exact SQL to run.
3. Confirm whether the change is reversible.
4. Export the affected tables.
5. Run the change in the smallest possible scope.
6. Run verification SQL.
7. Keep the backup until the app and Word add-in smoke tests pass.

## Verification after DB changes

Run the relevant verification migration or SQL, then smoke-test the app.

For normalized items, run:

```sql
-- supabase_migrations/202605160003_verify_normalized_items_security.sql
```

Check that `missing_required_*` result sets are empty.

For collection backfills, check counts:

```sql
select
  (select count(*) from public.collection_papers) as legacy_collection_papers,
  (select count(*) from public.collection_items) as normalized_collection_items;
```

For malformed item tag references:

```sql
select item_id, tag_id
from public.item_tags
where tag_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
```

## Restore policy

If a DB change causes errors:

1. Stop further writes if possible.
2. Record the failing operation and timestamp.
3. Restore only the affected tables/rows from the backup when feasible.
4. Re-run verification SQL.
5. Re-test the web app and Word add-in.

## Restore from backup

Prefer targeted restore over full project restore. Full restore is disruptive
and should be used only when the whole database state is known to be bad.

### Targeted row/table restore

1. Identify the affected table, rows, and backup file.
2. Create a fresh backup before restoring so the failed state is also recoverable.
3. Restore into a temporary table or local database first when possible.
4. Copy only the needed rows back into the live table.
5. Re-run RLS-sensitive app flows as the affected user.

Example pattern:

```sql
-- Run only after adapting table and key names.
begin;

-- Optional: keep the current bad state.
create table if not exists public.restore_audit_YYYYMMDD as
select *
from public.items
where id in ('...');

-- Restore only known-good values.
update public.items as target
set
  title = source.title,
  doi = source.doi,
  publication_title = source.publication_title
from restore_source_items as source
where target.id = source.id
  and target.user_id = source.user_id;

commit;
```

### Full restore drill

Use this only for a local rehearsal or a project-wide failure:

```powershell
# Rehearsal target should be local or a separate Supabase project.
supabase db reset --local
# Then apply the SQL backup with psql or the Supabase SQL editor in chunks.
```

For production full restore, prefer Supabase Dashboard point-in-time recovery if
available on the current plan. If not available, restore from the latest dump in
a maintenance window and keep the app read-only/offline while restoring.

## Release backup rule

Before every release that includes DB migrations or data repair:

- create a backup with the commands above
- run `supabase migration list`
- record the backup file name in the release notes
- verify web app login, list, import preview, and Word add-in citation update
