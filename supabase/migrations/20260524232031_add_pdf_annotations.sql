create table if not exists public.pdf_annotations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    paper_id text not null,
    page_number integer not null check (page_number > 0),
    annotation_type text not null default 'page_note'
        check (annotation_type in ('highlight', 'page_note', 'citation_note')),
    selected_text text,
    note text,
    color text not null default '#fff6db',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists pdf_annotations_user_paper_page_idx
    on public.pdf_annotations (user_id, paper_id, page_number, created_at);

create or replace function public.set_pdf_annotations_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists set_pdf_annotations_updated_at on public.pdf_annotations;
create trigger set_pdf_annotations_updated_at
    before update on public.pdf_annotations
    for each row
    execute function public.set_pdf_annotations_updated_at();

alter table public.pdf_annotations enable row level security;

drop policy if exists pdf_annotations_own_all
    on public.pdf_annotations;

create policy pdf_annotations_own_all
    on public.pdf_annotations
    for all
    using (
        user_id = auth.uid()
        and (
            exists (
                select 1
                from public.items
                where items.id::text = pdf_annotations.paper_id
                and items.user_id = auth.uid()
            )
            or exists (
                select 1
                from public.papers
                where papers.id::text = pdf_annotations.paper_id
                and papers.user_id = auth.uid()
            )
        )
    )
    with check (
        user_id = auth.uid()
        and (
            exists (
                select 1
                from public.items
                where items.id::text = pdf_annotations.paper_id
                and items.user_id = auth.uid()
            )
            or exists (
                select 1
                from public.papers
                where papers.id::text = pdf_annotations.paper_id
                and papers.user_id = auth.uid()
            )
        )
    );

grant select, insert, update, delete on table public.pdf_annotations to authenticated;
