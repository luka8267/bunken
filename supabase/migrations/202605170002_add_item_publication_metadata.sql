-- Add Zotero-style publication metadata to normalized items.
-- Non-destructive: only adds nullable columns and replaces the compatibility view.

alter table public.items
    add column if not exists volume text,
    add column if not exists issue text,
    add column if not exists pages text,
    add column if not exists publisher text;

create or replace view public.paper_items_view
with (security_invoker = true)
as
with creator_summary as (
    select
        creators.item_id,
        string_agg(
            coalesce(
                nullif(btrim(creators.literal_name), ''),
                nullif(btrim(concat_ws(' ', creators.first_name, creators.last_name)), '')
            ),
            ', '
            order by creators.position
        ) as authors
    from public.creators
    where creators.creator_type = 'author'
    group by creators.item_id
),
pdf_attachments as (
    select distinct on (attachments.item_id)
        attachments.item_id,
        attachments.storage_path as pdf_path
    from public.attachments
    where attachments.kind = 'pdf'
      and attachments.storage_path is not null
    order by attachments.item_id, attachments.created_at desc
),
supporting_attachments as (
    select distinct on (attachments.item_id)
        attachments.item_id,
        attachments.storage_path as supporting_path
    from public.attachments
    where attachments.kind = 'supporting'
      and attachments.storage_path is not null
    order by attachments.item_id, attachments.created_at desc
)
select
    coalesce(items.legacy_paper_id, items.id::text) as id,
    items.id as item_id,
    items.user_id,
    items.title,
    coalesce(creator_summary.authors, '') as authors,
    items.publication_title as journal,
    items.year,
    null::text as pdf_url,
    nullif(items.extra ->> 'legacy_display_order', '')::integer as display_order,
    pdf_attachments.pdf_path,
    items.doi,
    items.abstract_note as notes,
    items.extra ->> 'legacy_status' as status,
    items.url,
    supporting_attachments.supporting_path,
    items.item_type,
    items.created_at,
    items.updated_at,
    items.volume,
    items.issue,
    items.pages,
    items.publisher
from public.items
left join creator_summary
  on creator_summary.item_id = items.id
left join pdf_attachments
  on pdf_attachments.item_id = items.id
left join supporting_attachments
  on supporting_attachments.item_id = items.id;

grant select on table public.paper_items_view to authenticated;
