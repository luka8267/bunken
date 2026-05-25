-- Optimize legacy collection_papers RLS policies for Supabase advisors.

drop policy if exists collection_papers_select_own on public.collection_papers;
drop policy if exists collection_papers_insert_own on public.collection_papers;
drop policy if exists collection_papers_delete_own on public.collection_papers;

create policy collection_papers_select_own
    on public.collection_papers
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.collections
            where collections.id = collection_papers.collection_id
              and collections.user_id = (select auth.uid())
        )
    );

create policy collection_papers_insert_own
    on public.collection_papers
    for insert
    to authenticated
    with check (
        exists (
            select 1
            from public.collections
            join public.papers on papers.id = collection_papers.paper_id
            where collections.id = collection_papers.collection_id
              and collections.user_id = (select auth.uid())
              and papers.user_id = (select auth.uid())
        )
    );

create policy collection_papers_delete_own
    on public.collection_papers
    for delete
    to authenticated
    using (
        exists (
            select 1
            from public.collections
            where collections.id = collection_papers.collection_id
              and collections.user_id = (select auth.uid())
        )
    );
