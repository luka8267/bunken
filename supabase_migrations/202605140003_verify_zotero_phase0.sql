-- Read-only verification for Zotero-like schema objects used by bunken and the Word add-in.

select
    schemaname,
    tablename,
    rowsecurity
from pg_tables
where schemaname = 'public'
  and tablename in (
      'profiles',
      'papers',
      'tags',
      'paper_tags',
      'documents',
      'document_citations'
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
    policyname,
    tablename,
    cmd,
    qual,
    with_check
from pg_policies
where schemaname = 'public'
  and tablename in ('documents', 'document_citations')
order by tablename, policyname;

select missing_required_policy
from (
    values
        ('documents_select_own'),
        ('documents_insert_own'),
        ('documents_update_own'),
        ('documents_delete_own'),
        ('document_citations_select_own_documents'),
        ('document_citations_insert_own_documents'),
        ('document_citations_update_own_documents'),
        ('document_citations_delete_own_documents')
) as required(missing_required_policy)
where not exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and policyname = required.missing_required_policy
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
        ('public.profiles:select'),
        ('public.profiles:insert'),
        ('public.profiles:update'),
        ('public.papers:select'),
        ('public.papers:insert'),
        ('public.papers:update'),
        ('public.papers:delete'),
        ('public.tags:select'),
        ('public.tags:insert'),
        ('public.tags:update'),
        ('public.tags:delete'),
        ('public.paper_tags:select'),
        ('public.paper_tags:insert'),
        ('public.paper_tags:update'),
        ('public.paper_tags:delete'),
        ('public.paper_items_view:select'),
        ('public.documents:select'),
        ('public.documents:insert'),
        ('public.documents:update'),
        ('public.documents:delete'),
        ('public.document_citations:select'),
        ('public.document_citations:insert'),
        ('public.document_citations:update'),
        ('public.document_citations:delete')
) as required(missing_required_grant)
where not has_table_privilege(
    'authenticated',
    split_part(required.missing_required_grant, ':', 1),
    split_part(required.missing_required_grant, ':', 2)
);
