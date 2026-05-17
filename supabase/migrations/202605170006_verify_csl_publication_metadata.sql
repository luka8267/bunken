-- Read-only verification for CSL JSON publication metadata.
-- Expected: missing_* queries return zero rows.

select 'public.item_csl_json_view:security_invoker' as missing_required_view_option
where not exists (
    select 1
    from pg_class
    join pg_namespace on pg_namespace.oid = pg_class.relnamespace
    where pg_namespace.nspname = 'public'
      and pg_class.relname = 'item_csl_json_view'
      and 'security_invoker=true' = any(coalesce(pg_class.reloptions, array[]::text[]))
);

select missing_required_grant
from (
    values
        ('public.item_csl_json_view:select')
) as required(missing_required_grant)
where not has_table_privilege(
    'authenticated',
    split_part(required.missing_required_grant, ':', 1),
    split_part(required.missing_required_grant, ':', 2)
);

with sample as (
    select
        item_id,
        csl_json,
        public.paper_items_view.volume,
        public.paper_items_view.issue,
        public.paper_items_view.pages,
        public.paper_items_view.publisher
    from public.item_csl_json_view
    join public.paper_items_view using (item_id, user_id)
    where coalesce(volume, issue, pages, publisher) is not null
    limit 20
)
select item_id as missing_csl_metadata
from sample
where (volume is not null and csl_json ->> 'volume' is distinct from volume)
   or (issue is not null and csl_json ->> 'issue' is distinct from issue)
   or (pages is not null and csl_json ->> 'page' is distinct from pages)
   or (publisher is not null and csl_json ->> 'publisher' is distinct from publisher);
