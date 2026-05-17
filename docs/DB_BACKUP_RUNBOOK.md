# DB backup runbook

Use this before any Supabase schema change, migration, data repair, backfill, or
delete/update operation.

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
db_backups/backup_YYYYMMDD_HHMM_before_<change_name>_manifest.txt
```

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
