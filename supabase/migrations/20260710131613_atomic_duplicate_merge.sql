-- Make duplicate merges all-or-nothing. The caller remains subject to RLS;
-- no service-role key or SECURITY DEFINER function is introduced here.
--
-- Rollback after pausing merge operations:
--   drop function if exists public.merge_duplicate_papers_atomic(bigint, bigint, uuid, jsonb, jsonb, jsonb);
--   drop function if exists public.merge_duplicate_items_atomic(uuid, uuid, text, text, uuid, jsonb, jsonb, jsonb);

create or replace function public.merge_duplicate_papers_atomic(
    p_keeper_paper_id bigint,
    p_duplicate_paper_id bigint,
    p_merge_group_id uuid,
    p_keeper_snapshot jsonb,
    p_duplicate_snapshot jsonb,
    p_update_fields jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
    v_backup_id uuid;
    v_citation_updates integer := 0;
    v_merge_group_id uuid := coalesce(p_merge_group_id, gen_random_uuid());
begin
    if auth.uid() is null then
        raise exception 'Authentication is required to merge documents.' using errcode = '42501';
    end if;
    if p_keeper_paper_id is null or p_duplicate_paper_id is null
       or p_keeper_paper_id = p_duplicate_paper_id then
        raise exception 'Choose two different documents to merge.' using errcode = '22023';
    end if;

    perform 1
    from public.papers
    where id = p_keeper_paper_id
      and user_id = auth.uid()
    for update;
    if not found then
        raise exception 'The document to keep was not found.' using errcode = '42501';
    end if;

    perform 1
    from public.papers
    where id = p_duplicate_paper_id
      and user_id = auth.uid()
    for update;
    if not found then
        raise exception 'The document to merge was not found.' using errcode = '42501';
    end if;

    insert into public.duplicate_merge_backups (
        user_id,
        merge_group_id,
        keeper_paper_id,
        duplicate_paper_id,
        keeper_snapshot,
        duplicate_snapshot
    )
    values (
        auth.uid(),
        v_merge_group_id,
        p_keeper_paper_id::text,
        p_duplicate_paper_id::text,
        coalesce(p_keeper_snapshot, '{}'::jsonb),
        coalesce(p_duplicate_snapshot, '{}'::jsonb)
    )
    returning id into v_backup_id;

    update public.papers
    set
        title = case when p_update_fields ? 'title' then p_update_fields ->> 'title' else title end,
        authors = case when p_update_fields ? 'authors' then p_update_fields ->> 'authors' else authors end,
        journal = case when p_update_fields ? 'journal' then p_update_fields ->> 'journal' else journal end,
        year = case when p_update_fields ? 'year' then nullif(p_update_fields ->> 'year', '')::integer else year end,
        doi = case when p_update_fields ? 'doi' then nullif(p_update_fields ->> 'doi', '') else doi end,
        url = case when p_update_fields ? 'url' then nullif(p_update_fields ->> 'url', '') else url end,
        status = case when p_update_fields ? 'status' then nullif(p_update_fields ->> 'status', '') else status end,
        notes = case when p_update_fields ? 'notes' then p_update_fields ->> 'notes' else notes end,
        pdf_path = case when p_update_fields ? 'pdf_path' then nullif(p_update_fields ->> 'pdf_path', '') else pdf_path end,
        supporting_path = case when p_update_fields ? 'supporting_path' then nullif(p_update_fields ->> 'supporting_path', '') else supporting_path end
    where id = p_keeper_paper_id;

    insert into public.paper_tags (paper_id, tag_id)
    select p_keeper_paper_id, tag_id
    from public.paper_tags
    where paper_id = p_duplicate_paper_id
    on conflict do nothing;

    insert into public.collection_papers (collection_id, paper_id)
    select collection_id, p_keeper_paper_id
    from public.collection_papers
    where paper_id = p_duplicate_paper_id
    on conflict do nothing;

    with rewritten as (
        select
            citation.id,
            (
                select jsonb_agg(
                    case
                        when element.item ->> 'paperId' = p_duplicate_paper_id::text
                            then jsonb_set(element.item, '{paperId}', to_jsonb(p_keeper_paper_id::text), true)
                        else element.item
                    end
                    order by element.ordinality
                )
                from jsonb_array_elements(citation.citation_items) with ordinality as element(item, ordinality)
            ) as citation_items
        from public.document_citations as citation
        join public.documents as document on document.id = citation.document_id
        where document.user_id = auth.uid()
          and exists (
              select 1
              from jsonb_array_elements(citation.citation_items) as candidate(item)
              where candidate.item ->> 'paperId' = p_duplicate_paper_id::text
          )
    )
    update public.document_citations as citation
    set citation_items = rewritten.citation_items,
        updated_at = now()
    from rewritten
    where citation.id = rewritten.id;
    get diagnostics v_citation_updates = row_count;

    delete from public.papers
    where id = p_duplicate_paper_id;

    return jsonb_build_object(
        'backup_id', v_backup_id,
        'merge_group_id', v_merge_group_id,
        'citation_updates', v_citation_updates
    );
end;
$$;


create or replace function public.merge_duplicate_items_atomic(
    p_keeper_item_id uuid,
    p_duplicate_item_id uuid,
    p_keeper_paper_id text,
    p_duplicate_paper_id text,
    p_merge_group_id uuid,
    p_keeper_snapshot jsonb,
    p_duplicate_snapshot jsonb,
    p_update_fields jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
    v_backup_id uuid;
    v_citation_updates integer := 0;
    v_merge_group_id uuid := coalesce(p_merge_group_id, gen_random_uuid());
begin
    if auth.uid() is null then
        raise exception 'Authentication is required to merge documents.' using errcode = '42501';
    end if;
    if p_keeper_item_id is null or p_duplicate_item_id is null
       or p_keeper_item_id = p_duplicate_item_id then
        raise exception 'Choose two different documents to merge.' using errcode = '22023';
    end if;

    perform 1
    from public.items
    where id = p_keeper_item_id
      and user_id = auth.uid()
    for update;
    if not found then
        raise exception 'The document to keep was not found.' using errcode = '42501';
    end if;

    perform 1
    from public.items
    where id = p_duplicate_item_id
      and user_id = auth.uid()
    for update;
    if not found then
        raise exception 'The document to merge was not found.' using errcode = '42501';
    end if;

    if exists (
        select 1 from public.attachments
        where item_id = p_keeper_item_id and kind = 'pdf'
    ) and exists (
        select 1 from public.attachments
        where item_id = p_duplicate_item_id and kind = 'pdf'
    ) then
        raise exception 'Both documents have a PDF. Choose the file to keep before merging.' using errcode = '22023';
    end if;
    if exists (
        select 1 from public.attachments
        where item_id = p_keeper_item_id and kind = 'supporting'
    ) and exists (
        select 1 from public.attachments
        where item_id = p_duplicate_item_id and kind = 'supporting'
    ) then
        raise exception 'Both documents have a supporting file. Choose the file to keep before merging.' using errcode = '22023';
    end if;

    insert into public.duplicate_merge_backups (
        user_id,
        merge_group_id,
        keeper_paper_id,
        duplicate_paper_id,
        keeper_item_id,
        duplicate_item_id,
        keeper_snapshot,
        duplicate_snapshot
    )
    values (
        auth.uid(),
        v_merge_group_id,
        p_keeper_paper_id,
        p_duplicate_paper_id,
        p_keeper_item_id,
        p_duplicate_item_id,
        coalesce(p_keeper_snapshot, '{}'::jsonb),
        coalesce(p_duplicate_snapshot, '{}'::jsonb)
    )
    returning id into v_backup_id;

    update public.items
    set
        title = case when p_update_fields ? 'title' then p_update_fields ->> 'title' else title end,
        publication_title = case when p_update_fields ? 'publication_title' then p_update_fields ->> 'publication_title' else publication_title end,
        year = case when p_update_fields ? 'year' then nullif(p_update_fields ->> 'year', '')::integer else year end,
        doi = case when p_update_fields ? 'doi' then nullif(p_update_fields ->> 'doi', '') else doi end,
        url = case when p_update_fields ? 'url' then nullif(p_update_fields ->> 'url', '') else url end,
        volume = case when p_update_fields ? 'volume' then nullif(p_update_fields ->> 'volume', '') else volume end,
        issue = case when p_update_fields ? 'issue' then nullif(p_update_fields ->> 'issue', '') else issue end,
        pages = case when p_update_fields ? 'pages' then nullif(p_update_fields ->> 'pages', '') else pages end,
        publisher = case when p_update_fields ? 'publisher' then nullif(p_update_fields ->> 'publisher', '') else publisher end,
        item_type = case when p_update_fields ? 'item_type' then p_update_fields ->> 'item_type' else item_type end,
        abstract_note = case when p_update_fields ? 'abstract_note' then p_update_fields ->> 'abstract_note' else abstract_note end,
        updated_at = now()
    where id = p_keeper_item_id;

    insert into public.item_tags (item_id, tag_id)
    select p_keeper_item_id, tag_id
    from public.item_tags
    where item_id = p_duplicate_item_id
    on conflict do nothing;

    insert into public.collection_items (collection_id, item_id)
    select collection_id, p_keeper_item_id
    from public.collection_items
    where item_id = p_duplicate_item_id
    on conflict do nothing;

    update public.creators as source
    set
        item_id = p_keeper_item_id,
        position = source.position + coalesce(
            (
                select max(keeper.position)
                from public.creators as keeper
                where keeper.item_id = p_keeper_item_id
                  and keeper.creator_type = source.creator_type
            ),
            0
        )
    where source.item_id = p_duplicate_item_id;

    update public.attachments as source
    set item_id = p_keeper_item_id
    where source.item_id = p_duplicate_item_id
      and not exists (
          select 1
          from public.attachments as keeper
          where keeper.item_id = p_keeper_item_id
            and keeper.storage_path is not distinct from source.storage_path
      );

    with rewritten as (
        select
            citation.id,
            (
                select jsonb_agg(
                    case
                        when element.item ->> 'paperId' in (p_duplicate_paper_id, p_duplicate_item_id::text)
                            then jsonb_set(element.item, '{paperId}', to_jsonb(p_keeper_paper_id), true)
                        else element.item
                    end
                    order by element.ordinality
                )
                from jsonb_array_elements(citation.citation_items) with ordinality as element(item, ordinality)
            ) as citation_items
        from public.document_citations as citation
        join public.documents as document on document.id = citation.document_id
        where document.user_id = auth.uid()
          and exists (
              select 1
              from jsonb_array_elements(citation.citation_items) as candidate(item)
              where candidate.item ->> 'paperId' in (p_duplicate_paper_id, p_duplicate_item_id::text)
          )
    )
    update public.document_citations as citation
    set citation_items = rewritten.citation_items,
        updated_at = now()
    from rewritten
    where citation.id = rewritten.id;
    get diagnostics v_citation_updates = row_count;

    delete from public.items
    where id = p_duplicate_item_id;

    return jsonb_build_object(
        'backup_id', v_backup_id,
        'merge_group_id', v_merge_group_id,
        'citation_updates', v_citation_updates
    );
end;
$$;

revoke all on function public.merge_duplicate_papers_atomic(bigint, bigint, uuid, jsonb, jsonb, jsonb) from public, anon;
revoke all on function public.merge_duplicate_items_atomic(uuid, uuid, text, text, uuid, jsonb, jsonb, jsonb) from public, anon;
grant execute on function public.merge_duplicate_papers_atomic(bigint, bigint, uuid, jsonb, jsonb, jsonb) to authenticated;
grant execute on function public.merge_duplicate_items_atomic(uuid, uuid, text, text, uuid, jsonb, jsonb, jsonb) to authenticated;
