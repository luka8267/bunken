-- Run this in the Supabase SQL Editor after confirming SUPABASE_KEY is the anon key.
-- These policies assume:
-- - papers.user_id stores auth.uid()
-- - profiles.id stores auth.uid()
-- - storage object names start with the user id, e.g. <user_id>/pdfs/file.pdf

alter table public.profiles enable row level security;
alter table public.papers enable row level security;
alter table public.tags enable row level security;
alter table public.paper_tags enable row level security;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own"
on public.profiles
for select
to authenticated
using (id = auth.uid());

drop policy if exists "profiles_insert_own" on public.profiles;
create policy "profiles_insert_own"
on public.profiles
for insert
to authenticated
with check (id = auth.uid());

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own"
on public.profiles
for update
to authenticated
using (id = auth.uid())
with check (id = auth.uid());

drop policy if exists "papers_select_own" on public.papers;
create policy "papers_select_own"
on public.papers
for select
to authenticated
using (user_id = auth.uid());

drop policy if exists "papers_insert_own" on public.papers;
create policy "papers_insert_own"
on public.papers
for insert
to authenticated
with check (user_id = auth.uid());

drop policy if exists "papers_update_own" on public.papers;
create policy "papers_update_own"
on public.papers
for update
to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());

drop policy if exists "papers_delete_own" on public.papers;
create policy "papers_delete_own"
on public.papers
for delete
to authenticated
using (user_id = auth.uid());

-- The current tags table is shared by name. Associations are protected via paper_tags.
drop policy if exists "tags_select_authenticated" on public.tags;
create policy "tags_select_authenticated"
on public.tags
for select
to authenticated
using (true);

drop policy if exists "tags_insert_authenticated" on public.tags;
create policy "tags_insert_authenticated"
on public.tags
for insert
to authenticated
with check (true);

drop policy if exists "paper_tags_select_own_papers" on public.paper_tags;
create policy "paper_tags_select_own_papers"
on public.paper_tags
for select
to authenticated
using (
    exists (
        select 1
        from public.papers
        where papers.id = paper_tags.paper_id
          and papers.user_id = auth.uid()
    )
);

drop policy if exists "paper_tags_insert_own_papers" on public.paper_tags;
create policy "paper_tags_insert_own_papers"
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
);

drop policy if exists "paper_tags_delete_own_papers" on public.paper_tags;
create policy "paper_tags_delete_own_papers"
on public.paper_tags
for delete
to authenticated
using (
    exists (
        select 1
        from public.papers
        where papers.id = paper_tags.paper_id
          and papers.user_id = auth.uid()
    )
);

drop policy if exists "paper_files_select_own" on storage.objects;
create policy "paper_files_select_own"
on storage.objects
for select
to authenticated
using (
    bucket_id = 'paper-pdfs'
    and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists "paper_files_insert_own" on storage.objects;
create policy "paper_files_insert_own"
on storage.objects
for insert
to authenticated
with check (
    bucket_id = 'paper-pdfs'
    and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists "paper_files_delete_own" on storage.objects;
create policy "paper_files_delete_own"
on storage.objects
for delete
to authenticated
using (
    bucket_id = 'paper-pdfs'
    and (storage.foldername(name))[1] = auth.uid()::text
);
