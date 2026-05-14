-- Add Zotero-like collections without changing or deleting existing papers.
-- Collections are per-user folders; collection_papers only stores membership.

create table if not exists public.collections (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    name text not null,
    parent_id uuid references public.collections(id) on delete cascade,
    sort_order integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.collection_papers (
    collection_id uuid not null references public.collections(id) on delete cascade,
    paper_id uuid not null references public.papers(id) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (collection_id, paper_id)
);

alter table public.collections
    add column if not exists id uuid default gen_random_uuid(),
    add column if not exists user_id uuid references auth.users(id) on delete cascade,
    add column if not exists name text,
    add column if not exists parent_id uuid references public.collections(id) on delete cascade,
    add column if not exists sort_order integer not null default 0,
    add column if not exists created_at timestamptz not null default now(),
    add column if not exists updated_at timestamptz not null default now();

alter table public.collection_papers
    add column if not exists collection_id uuid references public.collections(id) on delete cascade,
    add column if not exists paper_id uuid references public.papers(id) on delete cascade,
    add column if not exists created_at timestamptz not null default now();

create index if not exists collections_user_parent_name_idx
on public.collections (user_id, coalesce(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), name);

create index if not exists collections_user_sort_idx
on public.collections (user_id, sort_order, name);

create index if not exists collection_papers_paper_id_idx
on public.collection_papers (paper_id);

alter table public.collections enable row level security;
alter table public.collection_papers enable row level security;

drop policy if exists "collections_select_own" on public.collections;
create policy "collections_select_own"
on public.collections
for select
to authenticated
using (user_id = auth.uid());

drop policy if exists "collections_insert_own" on public.collections;
create policy "collections_insert_own"
on public.collections
for insert
to authenticated
with check (user_id = auth.uid());

drop policy if exists "collections_update_own" on public.collections;
create policy "collections_update_own"
on public.collections
for update
to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());

drop policy if exists "collections_delete_own" on public.collections;
create policy "collections_delete_own"
on public.collections
for delete
to authenticated
using (user_id = auth.uid());

drop policy if exists "collection_papers_select_own" on public.collection_papers;
create policy "collection_papers_select_own"
on public.collection_papers
for select
to authenticated
using (
    exists (
        select 1
        from public.collections
        where collections.id = collection_papers.collection_id
          and collections.user_id = auth.uid()
    )
);

drop policy if exists "collection_papers_insert_own" on public.collection_papers;
create policy "collection_papers_insert_own"
on public.collection_papers
for insert
to authenticated
with check (
    exists (
        select 1
        from public.collections
        join public.papers on papers.id = collection_papers.paper_id
        where collections.id = collection_papers.collection_id
          and collections.user_id = auth.uid()
          and papers.user_id = auth.uid()
    )
);

drop policy if exists "collection_papers_delete_own" on public.collection_papers;
create policy "collection_papers_delete_own"
on public.collection_papers
for delete
to authenticated
using (
    exists (
        select 1
        from public.collections
        where collections.id = collection_papers.collection_id
          and collections.user_id = auth.uid()
    )
);

grant select, insert, update, delete on table public.collections to authenticated;
grant select, insert, delete on table public.collection_papers to authenticated;
