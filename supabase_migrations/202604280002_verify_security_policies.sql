-- Read-only verification query for production Supabase.
-- Expected: all rows in the final "missing_required_policy" query should be absent.

select
    schemaname,
    tablename,
    rowsecurity
from pg_tables
where schemaname = 'public'
  and tablename in ('profiles', 'papers', 'tags', 'paper_tags')
order by tablename;

select
    schemaname,
    tablename,
    policyname,
    permissive,
    roles,
    cmd,
    qual,
    with_check
from pg_policies
where schemaname = 'public'
  and tablename in ('profiles', 'papers', 'tags', 'paper_tags')
order by tablename, policyname;

select
    policyname,
    cmd,
    qual,
    with_check
from pg_policies
where schemaname = 'storage'
  and tablename = 'objects'
  and policyname like 'paper_files_%'
order by policyname;

select missing_required_policy
from (
    values
        ('profiles_select_own'),
        ('profiles_insert_own'),
        ('profiles_update_own'),
        ('papers_select_own'),
        ('papers_insert_own'),
        ('papers_update_own'),
        ('papers_delete_own'),
        ('tags_select_own'),
        ('tags_insert_own'),
        ('tags_update_own'),
        ('tags_delete_own'),
        ('paper_tags_select_own_papers'),
        ('paper_tags_insert_own_papers_and_tags'),
        ('paper_tags_update_own_papers_and_tags'),
        ('paper_tags_delete_own_papers')
) as required(missing_required_policy)
where not exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and policyname = required.missing_required_policy
);
