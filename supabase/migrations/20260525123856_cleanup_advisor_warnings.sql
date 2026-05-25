-- Clean up Supabase advisor warnings that are safe to fix in SQL.
-- Changes are schema/RLS-only; no application data is modified.

create or replace function public.set_pdf_annotations_updated_at()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop index if exists public.document_citations_document_id_citation_key_key;
drop index if exists public.documents_user_word_document_id_key;

drop policy if exists items_own_all on public.items;
create policy items_own_all
    on public.items
    for all
    to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists attachments_own_all on public.attachments;
create policy attachments_own_all
    on public.attachments
    for all
    to authenticated
    using (
        user_id = (select auth.uid())
        and exists (
            select 1
            from public.items
            where items.id = attachments.item_id
              and items.user_id = (select auth.uid())
        )
    )
    with check (
        user_id = (select auth.uid())
        and exists (
            select 1
            from public.items
            where items.id = attachments.item_id
              and items.user_id = (select auth.uid())
        )
    );

drop policy if exists creators_own_items_all on public.creators;
create policy creators_own_items_all
    on public.creators
    for all
    to authenticated
    using (
        exists (
            select 1
            from public.items
            where items.id = creators.item_id
              and items.user_id = (select auth.uid())
        )
    )
    with check (
        exists (
            select 1
            from public.items
            where items.id = creators.item_id
              and items.user_id = (select auth.uid())
        )
    );

drop policy if exists collections_select_own on public.collections;
drop policy if exists collections_insert_own on public.collections;
drop policy if exists collections_update_own on public.collections;
drop policy if exists collections_delete_own on public.collections;
drop policy if exists collections_own_all on public.collections;
create policy collections_own_all
    on public.collections
    for all
    to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists collection_items_own_all on public.collection_items;
create policy collection_items_own_all
    on public.collection_items
    for all
    to authenticated
    using (
        exists (
            select 1
            from public.collections
            where collections.id = collection_items.collection_id
              and collections.user_id = (select auth.uid())
        )
        and exists (
            select 1
            from public.items
            where items.id = collection_items.item_id
              and items.user_id = (select auth.uid())
        )
    )
    with check (
        exists (
            select 1
            from public.collections
            where collections.id = collection_items.collection_id
              and collections.user_id = (select auth.uid())
        )
        and exists (
            select 1
            from public.items
            where items.id = collection_items.item_id
              and items.user_id = (select auth.uid())
        )
    );

drop policy if exists "Anyone can view tags" on public.tags;
drop policy if exists tags_select_own on public.tags;
drop policy if exists tags_insert_own on public.tags;
drop policy if exists tags_update_own on public.tags;
drop policy if exists tags_delete_own on public.tags;
create policy tags_own_all
    on public.tags
    for all
    to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists item_tags_own_all on public.item_tags;
create policy item_tags_own_all
    on public.item_tags
    for all
    to authenticated
    using (
        exists (
            select 1
            from public.items
            where items.id = item_tags.item_id
              and items.user_id = (select auth.uid())
        )
        and exists (
            select 1
            from public.tags
            where tags.id::text = item_tags.tag_id
              and tags.user_id = (select auth.uid())
        )
    )
    with check (
        exists (
            select 1
            from public.items
            where items.id = item_tags.item_id
              and items.user_id = (select auth.uid())
        )
        and exists (
            select 1
            from public.tags
            where tags.id::text = item_tags.tag_id
              and tags.user_id = (select auth.uid())
        )
    );

drop policy if exists documents_select_own on public.documents;
drop policy if exists documents_insert_own on public.documents;
drop policy if exists documents_update_own on public.documents;
drop policy if exists documents_delete_own on public.documents;
drop policy if exists documents_own_all on public.documents;
create policy documents_own_all
    on public.documents
    for all
    to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists document_citations_select_own_documents on public.document_citations;
drop policy if exists document_citations_insert_own_documents on public.document_citations;
drop policy if exists document_citations_update_own_documents on public.document_citations;
drop policy if exists document_citations_delete_own_documents on public.document_citations;
drop policy if exists document_citations_own_all on public.document_citations;
create policy document_citations_own_all
    on public.document_citations
    for all
    to authenticated
    using (
        exists (
            select 1
            from public.documents
            where documents.id = document_citations.document_id
              and documents.user_id = (select auth.uid())
        )
    )
    with check (
        exists (
            select 1
            from public.documents
            where documents.id = document_citations.document_id
              and documents.user_id = (select auth.uid())
        )
    );

drop policy if exists duplicate_merge_backups_own_all on public.duplicate_merge_backups;
create policy duplicate_merge_backups_own_all
    on public.duplicate_merge_backups
    for all
    to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists pdf_annotations_own_all on public.pdf_annotations;
create policy pdf_annotations_own_all
    on public.pdf_annotations
    for all
    to authenticated
    using (
        user_id = (select auth.uid())
        and (
            exists (
                select 1
                from public.items
                where items.id::text = pdf_annotations.paper_id
                  and items.user_id = (select auth.uid())
            )
            or exists (
                select 1
                from public.papers
                where papers.id::text = pdf_annotations.paper_id
                  and papers.user_id = (select auth.uid())
            )
        )
    )
    with check (
        user_id = (select auth.uid())
        and (
            exists (
                select 1
                from public.items
                where items.id::text = pdf_annotations.paper_id
                  and items.user_id = (select auth.uid())
            )
            or exists (
                select 1
                from public.papers
                where papers.id::text = pdf_annotations.paper_id
                  and papers.user_id = (select auth.uid())
            )
        )
    );

drop policy if exists "read own profile" on public.profiles;
drop policy if exists "insert own profile" on public.profiles;
drop policy if exists "update own profile" on public.profiles;
drop policy if exists profiles_select_own on public.profiles;
drop policy if exists profiles_insert_own on public.profiles;
drop policy if exists profiles_update_own on public.profiles;
create policy profiles_select_own
    on public.profiles
    for select
    to authenticated
    using (id = (select auth.uid()));
create policy profiles_insert_own
    on public.profiles
    for insert
    to authenticated
    with check (id = (select auth.uid()));
create policy profiles_update_own
    on public.profiles
    for update
    to authenticated
    using (id = (select auth.uid()))
    with check (id = (select auth.uid()));

drop policy if exists "read own papers" on public.papers;
drop policy if exists "insert own papers" on public.papers;
drop policy if exists "update own papers" on public.papers;
drop policy if exists "delete own papers" on public.papers;
drop policy if exists papers_select_own on public.papers;
drop policy if exists papers_insert_own on public.papers;
drop policy if exists papers_update_own on public.papers;
drop policy if exists papers_delete_own on public.papers;
create policy papers_select_own
    on public.papers
    for select
    to authenticated
    using (user_id = (select auth.uid()));
create policy papers_insert_own
    on public.papers
    for insert
    to authenticated
    with check (
        user_id = (select auth.uid())
        and (pdf_path is null or split_part(pdf_path, '/', 1) = (select auth.uid())::text)
        and (supporting_path is null or split_part(supporting_path, '/', 1) = (select auth.uid())::text)
    );
create policy papers_update_own
    on public.papers
    for update
    to authenticated
    using (user_id = (select auth.uid()))
    with check (
        user_id = (select auth.uid())
        and (pdf_path is null or split_part(pdf_path, '/', 1) = (select auth.uid())::text)
        and (supporting_path is null or split_part(supporting_path, '/', 1) = (select auth.uid())::text)
    );
create policy papers_delete_own
    on public.papers
    for delete
    to authenticated
    using (user_id = (select auth.uid()));

drop policy if exists "read own paper_tags" on public.paper_tags;
drop policy if exists "insert own paper_tags" on public.paper_tags;
drop policy if exists "delete own paper_tags" on public.paper_tags;
drop policy if exists paper_tags_select_own_papers on public.paper_tags;
drop policy if exists paper_tags_insert_own_papers_and_tags on public.paper_tags;
drop policy if exists paper_tags_update_own_papers_and_tags on public.paper_tags;
drop policy if exists paper_tags_delete_own_papers on public.paper_tags;
create policy paper_tags_select_own_papers
    on public.paper_tags
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.papers
            where papers.id = paper_tags.paper_id
              and papers.user_id = (select auth.uid())
        )
    );
create policy paper_tags_insert_own_papers_and_tags
    on public.paper_tags
    for insert
    to authenticated
    with check (
        exists (
            select 1
            from public.papers
            where papers.id = paper_tags.paper_id
              and papers.user_id = (select auth.uid())
        )
        and exists (
            select 1
            from public.tags
            where tags.id = paper_tags.tag_id
              and tags.user_id = (select auth.uid())
        )
    );
create policy paper_tags_update_own_papers_and_tags
    on public.paper_tags
    for update
    to authenticated
    using (
        exists (
            select 1
            from public.papers
            where papers.id = paper_tags.paper_id
              and papers.user_id = (select auth.uid())
        )
    )
    with check (
        exists (
            select 1
            from public.papers
            where papers.id = paper_tags.paper_id
              and papers.user_id = (select auth.uid())
        )
        and exists (
            select 1
            from public.tags
            where tags.id = paper_tags.tag_id
              and tags.user_id = (select auth.uid())
        )
    );
create policy paper_tags_delete_own_papers
    on public.paper_tags
    for delete
    to authenticated
    using (
        exists (
            select 1
            from public.papers
            where papers.id = paper_tags.paper_id
              and papers.user_id = (select auth.uid())
        )
    );
