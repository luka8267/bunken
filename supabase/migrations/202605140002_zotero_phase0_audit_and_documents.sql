-- Phase 0/1 database alignment for Zotero-like library and Word add-in sync.
-- Safe to run on an existing project: it creates missing document sync objects,
-- enables RLS, adds grants for the Data API, and creates a fallback
-- paper_items_view only when it does not already exist.

create table if not exists public.documents (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    word_document_id text not null,
    title text not null default '',
    citation_style text not null default 'vancouver',
    locale text not null default 'ja-JP',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, word_document_id)
);

create table if not exists public.document_citations (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.documents(id) on delete cascade,
    citation_key text not null,
    word_control_id text not null default '',
    citation_items jsonb not null default '[]'::jsonb,
    rendered_text text not null default '',
    sort_order integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (document_id, citation_key)
);

alter table public.documents
    add column if not exists id uuid default gen_random_uuid(),
    add column if not exists user_id uuid references auth.users(id) on delete cascade,
    add column if not exists word_document_id text,
    add column if not exists title text not null default '',
    add column if not exists citation_style text not null default 'vancouver',
    add column if not exists locale text not null default 'ja-JP',
    add column if not exists created_at timestamptz not null default now(),
    add column if not exists updated_at timestamptz not null default now();

alter table public.document_citations
    add column if not exists id uuid default gen_random_uuid(),
    add column if not exists document_id uuid references public.documents(id) on delete cascade,
    add column if not exists citation_key text,
    add column if not exists word_control_id text not null default '',
    add column if not exists citation_items jsonb not null default '[]'::jsonb,
    add column if not exists rendered_text text not null default '',
    add column if not exists sort_order integer not null default 0,
    add column if not exists created_at timestamptz not null default now(),
    add column if not exists updated_at timestamptz not null default now();

create unique index if not exists documents_user_word_document_id_key
on public.documents (user_id, word_document_id);

create unique index if not exists document_citations_document_id_citation_key_key
on public.document_citations (document_id, citation_key);

do $$
begin
    if to_regclass('public.paper_items_view') is null then
        execute $view$
            create view public.paper_items_view
            with (security_invoker = true)
            as
            select
                papers.id,
                papers.title,
                papers.authors,
                papers.journal,
                papers.year,
                papers.doi,
                papers.user_id,
                papers.display_order,
                papers.status,
                papers.notes,
                papers.url,
                papers.pdf_path,
                papers.supporting_path
            from public.papers
        $view$;
    end if;
end $$;

do $$
begin
    if to_regclass('public.paper_items_view') is not null then
        execute 'alter view public.paper_items_view set (security_invoker = true)';
    end if;
end $$;

alter table public.documents enable row level security;
alter table public.document_citations enable row level security;

drop policy if exists "documents_select_own" on public.documents;
create policy "documents_select_own"
on public.documents
for select
to authenticated
using (user_id = auth.uid());

drop policy if exists "documents_insert_own" on public.documents;
create policy "documents_insert_own"
on public.documents
for insert
to authenticated
with check (user_id = auth.uid());

drop policy if exists "documents_update_own" on public.documents;
create policy "documents_update_own"
on public.documents
for update
to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());

drop policy if exists "documents_delete_own" on public.documents;
create policy "documents_delete_own"
on public.documents
for delete
to authenticated
using (user_id = auth.uid());

drop policy if exists "document_citations_select_own_documents" on public.document_citations;
create policy "document_citations_select_own_documents"
on public.document_citations
for select
to authenticated
using (
    exists (
        select 1
        from public.documents
        where documents.id = document_citations.document_id
          and documents.user_id = auth.uid()
    )
);

drop policy if exists "document_citations_insert_own_documents" on public.document_citations;
create policy "document_citations_insert_own_documents"
on public.document_citations
for insert
to authenticated
with check (
    exists (
        select 1
        from public.documents
        where documents.id = document_citations.document_id
          and documents.user_id = auth.uid()
    )
);

drop policy if exists "document_citations_update_own_documents" on public.document_citations;
create policy "document_citations_update_own_documents"
on public.document_citations
for update
to authenticated
using (
    exists (
        select 1
        from public.documents
        where documents.id = document_citations.document_id
          and documents.user_id = auth.uid()
    )
)
with check (
    exists (
        select 1
        from public.documents
        where documents.id = document_citations.document_id
          and documents.user_id = auth.uid()
    )
);

drop policy if exists "document_citations_delete_own_documents" on public.document_citations;
create policy "document_citations_delete_own_documents"
on public.document_citations
for delete
to authenticated
using (
    exists (
        select 1
        from public.documents
        where documents.id = document_citations.document_id
          and documents.user_id = auth.uid()
    )
);

grant usage on schema public to authenticated;
grant select, insert, update on table public.profiles to authenticated;
grant select, insert, update, delete on table public.papers to authenticated;
grant select, insert, update, delete on table public.tags to authenticated;
grant select, insert, update, delete on table public.paper_tags to authenticated;
grant select on public.paper_items_view to authenticated;
grant select, insert, update, delete on table public.documents to authenticated;
grant select, insert, update, delete on table public.document_citations to authenticated;
grant usage, select on all sequences in schema public to authenticated;
