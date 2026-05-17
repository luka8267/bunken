-- Read-only verification for item publication metadata.
-- Expected: missing_* queries return zero rows.

select
    column_name,
    data_type,
    is_nullable
from information_schema.columns
where table_schema = 'public'
  and table_name = 'items'
  and column_name in ('volume', 'issue', 'pages', 'publisher')
order by column_name;

select missing_required_item_column
from (
    values
        ('volume'),
        ('issue'),
        ('pages'),
        ('publisher')
) as required(missing_required_item_column)
where not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'items'
      and column_name = required.missing_required_item_column
);

select missing_required_view_column
from (
    values
        ('item_type'),
        ('volume'),
        ('issue'),
        ('pages'),
        ('publisher')
) as required(missing_required_view_column)
where not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'paper_items_view'
      and column_name = required.missing_required_view_column
);

select 'public.paper_items_view:security_invoker' as missing_required_view_option
where not exists (
    select 1
    from pg_class
    join pg_namespace on pg_namespace.oid = pg_class.relnamespace
    where pg_namespace.nspname = 'public'
      and pg_class.relname = 'paper_items_view'
      and 'security_invoker=true' = any(coalesce(pg_class.reloptions, array[]::text[]))
);
