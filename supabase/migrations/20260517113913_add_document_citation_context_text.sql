alter table public.document_citations
    add column if not exists context_text text not null default '';
