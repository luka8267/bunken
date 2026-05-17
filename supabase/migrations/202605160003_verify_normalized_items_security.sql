-- Read-only verification for the normalized item-backed library schema.
-- Expected: the final missing_* queries should return zero rows.

select
    schemaname,
    tablename,
    rowsecurity
from pg_tables
where schemaname = 'public'
  and tablename in (
      'items',
      'creators',
      'attachments',
      'item_tags',
      'collection_items'
  )
order by tablename;

select
    schemaname,
    viewname,
    'security_invoker=true' = any(coalesce(pg_class.reloptions, array[]::text[])) as security_invoker
from pg_views
join pg_class
  on pg_class.relname = pg_views.viewname
join pg_namespace
  on pg_namespace.oid = pg_class.relnamespace
 and pg_namespace.nspname = pg_views.schemaname
where schemaname = 'public'
  and viewname = 'paper_items_view';

select
    tablename,
    policyname,
    cmd,
    qual,
    with_check
from pg_policies
where schemaname = 'public'
  and tablename in (
      'items',
      'creators',
      'attachments',
      'item_tags',
      'collection_items'
  )
order by tablename, policyname;

select missing_required_table
from (
    values
        ('public.items'),
        ('public.creators'),
        ('public.attachments'),
        ('public.item_tags'),
        ('public.collection_items')
) as required(missing_required_table)
where to_regclass(required.missing_required_table) is null;

select missing_required_rls
from (
    values
        ('items'),
        ('creators'),
        ('attachments'),
        ('item_tags'),
        ('collection_items')
) as required(missing_required_rls)
where not exists (
    select 1
    from pg_tables
    where schemaname = 'public'
      and tablename = required.missing_required_rls
      and rowsecurity
);

select missing_required_policy
from (
    values
        ('items_own_all'),
        ('creators_own_items_all'),
        ('attachments_own_all'),
        ('item_tags_own_all'),
        ('collection_items_own_all')
) as required(missing_required_policy)
where not exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and policyname = required.missing_required_policy
);

select missing_required_constraint
from (
    values
        ('items_pkey'),
        ('items_user_id_fkey'),
        ('items_legacy_pair_unique'),
        ('creators_item_id_fkey'),
        ('creators_item_position_unique'),
        ('attachments_item_id_fkey'),
        ('attachments_user_id_fkey'),
        ('attachments_storage_owned_by_user'),
        ('attachments_item_storage_path_unique'),
        ('item_tags_pkey'),
        ('item_tags_item_id_fkey'),
        ('collection_items_pkey'),
        ('collection_items_collection_id_fkey'),
        ('collection_items_item_id_fkey')
) as required(missing_required_constraint)
where not exists (
    select 1
    from pg_constraint
    where connamespace = 'public'::regnamespace
      and conname = required.missing_required_constraint
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

select missing_required_grant
from (
    values
        ('public.items:select'),
        ('public.items:insert'),
        ('public.items:update'),
        ('public.items:delete'),
        ('public.creators:select'),
        ('public.creators:insert'),
        ('public.creators:update'),
        ('public.creators:delete'),
        ('public.attachments:select'),
        ('public.attachments:insert'),
        ('public.attachments:update'),
        ('public.attachments:delete'),
        ('public.item_tags:select'),
        ('public.item_tags:insert'),
        ('public.item_tags:update'),
        ('public.item_tags:delete'),
        ('public.collection_items:select'),
        ('public.collection_items:insert'),
        ('public.collection_items:update'),
        ('public.collection_items:delete'),
        ('public.paper_items_view:select')
) as required(missing_required_grant)
where not has_table_privilege(
    'authenticated',
    split_part(required.missing_required_grant, ':', 1),
    split_part(required.missing_required_grant, ':', 2)
);
