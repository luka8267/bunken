-- Add Zotero/CSL publication metadata to item_csl_json_view.

create or replace view public.item_csl_json_view
with (security_invoker = true)
as
select
    item_id,
    user_id,
    jsonb_strip_nulls(
        jsonb_build_object(
            'id', item_id::text,
            'type',
                case item_type
                    when 'journalArticle' then 'article-journal'
                    when 'book' then 'book'
                    when 'bookSection' then 'chapter'
                    when 'webpage' then 'webpage'
                    when 'thesis' then 'thesis'
                    when 'report' then 'report'
                    else 'article-journal'
                end,
            'title', title,
            'container-title', nullif(journal, ''),
            'issued',
                case
                    when year is null then null::jsonb
                    else jsonb_build_object(
                        'date-parts',
                        jsonb_build_array(jsonb_build_array(year))
                    )
                end,
            'volume', nullif(volume, ''),
            'issue', nullif(issue, ''),
            'page', nullif(pages, ''),
            'publisher', nullif(publisher, ''),
            'DOI', nullif(doi, ''),
            'URL', nullif(url, ''),
            'abstract', nullif(notes, '')
        )
    ) as csl_json
from public.paper_items_view;

grant select on table public.item_csl_json_view to authenticated;
