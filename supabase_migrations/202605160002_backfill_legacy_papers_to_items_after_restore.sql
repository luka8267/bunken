-- Re-run the legacy papers -> normalized items backfill after restoring the
-- normalized item schema. This is idempotent and does not delete source rows.

do $$
begin
    if to_regclass('public.papers') is null
       or to_regclass('public.items') is null
       or to_regclass('public.creators') is null
       or to_regclass('public.attachments') is null
       or to_regclass('public.item_tags') is null then
        return;
    end if;

    insert into public.items (
        user_id,
        item_type,
        title,
        publication_title,
        date,
        year,
        doi,
        url,
        abstract_note,
        extra,
        legacy_paper_id
    )
    select
        p.user_id,
        'journalArticle',
        coalesce(p.title, ''),
        coalesce(p.journal, ''),
        nullif((to_jsonb(p) ->> 'year'), ''),
        nullif((to_jsonb(p) ->> 'year'), '')::integer,
        nullif(p.doi, ''),
        nullif(to_jsonb(p) ->> 'url', ''),
        nullif(to_jsonb(p) ->> 'notes', ''),
        jsonb_strip_nulls(
            jsonb_build_object(
                'legacy_display_order', to_jsonb(p) ->> 'display_order',
                'legacy_status', to_jsonb(p) ->> 'status'
            )
        ),
        p.id::text
    from public.papers p
    where p.user_id is not null
    on conflict (user_id, legacy_source, legacy_paper_id) do update
    set
        title = excluded.title,
        publication_title = excluded.publication_title,
        date = excluded.date,
        year = excluded.year,
        doi = excluded.doi,
        url = excluded.url,
        abstract_note = excluded.abstract_note,
        extra = public.items.extra || excluded.extra,
        updated_at = now();

    insert into public.creators (
        item_id,
        creator_type,
        literal_name,
        position
    )
    select
        i.id,
        'author',
        btrim(author_part.value),
        author_part.ordinality::integer
    from public.papers p
    join public.items i
      on i.user_id = p.user_id
     and i.legacy_source = 'papers'
     and i.legacy_paper_id = p.id::text
    cross join lateral regexp_split_to_table(coalesce(p.authors, ''), ',') with ordinality
        as author_part(value, ordinality)
    where btrim(author_part.value) <> ''
    on conflict (item_id, creator_type, position) do update
    set literal_name = excluded.literal_name;

    insert into public.attachments (
        item_id,
        user_id,
        kind,
        storage_path,
        filename,
        content_type,
        title
    )
    select
        i.id,
        p.user_id,
        'pdf',
        to_jsonb(p) ->> 'pdf_path',
        split_part(
            to_jsonb(p) ->> 'pdf_path',
            '/',
            array_length(string_to_array(to_jsonb(p) ->> 'pdf_path', '/'), 1)
        ),
        'application/pdf',
        'PDF'
    from public.papers p
    join public.items i
      on i.user_id = p.user_id
     and i.legacy_source = 'papers'
     and i.legacy_paper_id = p.id::text
    where nullif(to_jsonb(p) ->> 'pdf_path', '') is not null
    on conflict (item_id, storage_path) do nothing;

    insert into public.attachments (
        item_id,
        user_id,
        kind,
        storage_path,
        filename,
        content_type,
        title
    )
    select
        i.id,
        p.user_id,
        'supporting',
        to_jsonb(p) ->> 'supporting_path',
        split_part(
            to_jsonb(p) ->> 'supporting_path',
            '/',
            array_length(string_to_array(to_jsonb(p) ->> 'supporting_path', '/'), 1)
        ),
        null,
        'Supporting file'
    from public.papers p
    join public.items i
      on i.user_id = p.user_id
     and i.legacy_source = 'papers'
     and i.legacy_paper_id = p.id::text
    where nullif(to_jsonb(p) ->> 'supporting_path', '') is not null
    on conflict (item_id, storage_path) do nothing;

    insert into public.item_tags (item_id, tag_id)
    select distinct
        i.id,
        pt.tag_id::text
    from public.paper_tags pt
    join public.papers p
      on p.id = pt.paper_id
    join public.items i
      on i.user_id = p.user_id
     and i.legacy_source = 'papers'
     and i.legacy_paper_id = p.id::text
    join public.tags t
      on t.id = pt.tag_id
    where t.user_id = p.user_id
    on conflict do nothing;
end $$;
