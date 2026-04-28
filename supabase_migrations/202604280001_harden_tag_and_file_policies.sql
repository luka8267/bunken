-- Harden per-user tag isolation and enforce owned storage paths.
-- Apply after 202604230001_security_policies.sql.

alter table public.tags
add column if not exists user_id uuid references auth.users(id) on delete cascade;

-- The original SQLite-era schema used UNIQUE(name). Drop any single-column
-- unique constraint on tags.name so different users can use the same tag name.
do $$
declare
    constraint_name text;
begin
    for constraint_name in
        select c.conname
        from pg_constraint c
        join pg_class t on t.oid = c.conrelid
        join pg_namespace n on n.oid = t.relnamespace
        where n.nspname = 'public'
          and t.relname = 'tags'
          and c.contype = 'u'
          and c.conkey = array[
              (
                  select attnum
                  from pg_attribute
                  where attrelid = t.oid
                    and attname = 'name'
                    and not attisdropped
              )
          ]::smallint[]
    loop
        execute format('alter table public.tags drop constraint %I', constraint_name);
    end loop;
end $$;

do $$
declare
    index_name text;
begin
    for index_name in
        select i.relname
        from pg_index x
        join pg_class i on i.oid = x.indexrelid
        join pg_class t on t.oid = x.indrelid
        join pg_namespace n on n.oid = t.relnamespace
        left join pg_constraint c on c.conindid = x.indexrelid
        where n.nspname = 'public'
          and t.relname = 'tags'
          and x.indisunique
          and c.oid is null
          and pg_get_indexdef(x.indexrelid) like '%(name)%'
          and pg_get_indexdef(x.indexrelid) not like '%,%'
    loop
        execute format('drop index public.%I', index_name);
    end loop;
end $$;

-- Create one owned tag row for each user/tag combination already in use.
insert into public.tags (name, user_id)
select distinct source_tags.name, papers.user_id
from public.tags source_tags
join public.paper_tags on paper_tags.tag_id = source_tags.id
join public.papers on papers.id = paper_tags.paper_id
where papers.user_id is not null
  and not exists (
      select 1
      from public.tags owned_tags
      where owned_tags.name = source_tags.name
        and owned_tags.user_id = papers.user_id
  );

-- Re-point paper_tags from formerly shared tags to the matching owned tag.
update public.paper_tags
set tag_id = owned_tags.id
from public.tags source_tags,
     public.papers,
     public.tags owned_tags
where paper_tags.tag_id = source_tags.id
  and papers.id = paper_tags.paper_id
  and owned_tags.name = source_tags.name
  and owned_tags.user_id = papers.user_id
  and source_tags.user_id is distinct from papers.user_id;

delete from public.tags
where user_id is null
  and not exists (
      select 1
      from public.paper_tags
      where paper_tags.tag_id = tags.id
  );

alter table public.tags
alter column user_id set not null;

create unique index if not exists tags_user_id_name_key
on public.tags (user_id, name);

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'papers_pdf_path_owned_by_user'
          and conrelid = 'public.papers'::regclass
    ) then
        alter table public.papers
        add constraint papers_pdf_path_owned_by_user
        check (pdf_path is null or split_part(pdf_path, '/', 1) = user_id::text);
    end if;

    if not exists (
        select 1
        from pg_constraint
        where conname = 'papers_supporting_path_owned_by_user'
          and conrelid = 'public.papers'::regclass
    ) then
        alter table public.papers
        add constraint papers_supporting_path_owned_by_user
        check (supporting_path is null or split_part(supporting_path, '/', 1) = user_id::text);
    end if;
end $$;

drop policy if exists "tags_select_authenticated" on public.tags;
drop policy if exists "tags_insert_authenticated" on public.tags;
drop policy if exists "tags_select_own" on public.tags;
create policy "tags_select_own"
on public.tags
for select
to authenticated
using (user_id = auth.uid());

drop policy if exists "tags_insert_own" on public.tags;
create policy "tags_insert_own"
on public.tags
for insert
to authenticated
with check (user_id = auth.uid());

drop policy if exists "tags_update_own" on public.tags;
create policy "tags_update_own"
on public.tags
for update
to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());

drop policy if exists "tags_delete_own" on public.tags;
create policy "tags_delete_own"
on public.tags
for delete
to authenticated
using (user_id = auth.uid());

drop policy if exists "paper_tags_insert_own_papers" on public.paper_tags;
drop policy if exists "paper_tags_insert_own_papers_and_tags" on public.paper_tags;
create policy "paper_tags_insert_own_papers_and_tags"
on public.paper_tags
for insert
to authenticated
with check (
    exists (
        select 1
        from public.papers
        where papers.id = paper_tags.paper_id
          and papers.user_id = auth.uid()
    )
    and exists (
        select 1
        from public.tags
        where tags.id = paper_tags.tag_id
          and tags.user_id = auth.uid()
    )
);

drop policy if exists "paper_tags_update_own_papers_and_tags" on public.paper_tags;
create policy "paper_tags_update_own_papers_and_tags"
on public.paper_tags
for update
to authenticated
using (
    exists (
        select 1
        from public.papers
        where papers.id = paper_tags.paper_id
          and papers.user_id = auth.uid()
    )
)
with check (
    exists (
        select 1
        from public.papers
        where papers.id = paper_tags.paper_id
          and papers.user_id = auth.uid()
    )
    and exists (
        select 1
        from public.tags
        where tags.id = paper_tags.tag_id
          and tags.user_id = auth.uid()
    )
);

drop policy if exists "papers_insert_own" on public.papers;
create policy "papers_insert_own"
on public.papers
for insert
to authenticated
with check (
    user_id = auth.uid()
    and (pdf_path is null or split_part(pdf_path, '/', 1) = auth.uid()::text)
    and (supporting_path is null or split_part(supporting_path, '/', 1) = auth.uid()::text)
);

drop policy if exists "papers_update_own" on public.papers;
create policy "papers_update_own"
on public.papers
for update
to authenticated
using (user_id = auth.uid())
with check (
    user_id = auth.uid()
    and (pdf_path is null or split_part(pdf_path, '/', 1) = auth.uid()::text)
    and (supporting_path is null or split_part(supporting_path, '/', 1) = auth.uid()::text)
);
