-- Backfill legacy collection memberships into the normalized collection_items
-- table. This is non-destructive: existing collection_papers rows are kept so
-- older app versions can still read them, and duplicate memberships are ignored.

do $$
begin
    if to_regclass('public.collection_papers') is null
       or to_regclass('public.collection_items') is null
       or to_regclass('public.collections') is null
       or to_regclass('public.papers') is null
       or to_regclass('public.items') is null then
        return;
    end if;

    insert into public.collection_items (collection_id, item_id)
    select distinct
        cp.collection_id,
        i.id
    from public.collection_papers cp
    join public.collections c
      on c.id = cp.collection_id
    join public.papers p
      on p.id = cp.paper_id
     and p.user_id = c.user_id
    join public.items i
      on i.user_id = p.user_id
     and i.legacy_source = 'papers'
     and i.legacy_paper_id = p.id::text
    on conflict do nothing;
end $$;
