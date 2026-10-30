select p.id, p.item_id, p.user_id, p.title, p.authors, p.journal, p.year,
       p.doi, p.volume, p.issue, p.pages, p.publisher, p.updated_at,
       coalesce((select jsonb_agg(jsonb_build_object(
           'id', c.id, 'creator_type', c.creator_type,
           'first_name', c.first_name, 'last_name', c.last_name,
           'literal_name', c.literal_name, 'position', c.position
       ) order by c.position) from public.creators c
       where c.item_id = p.item_id and c.creator_type = 'author'), '[]'::jsonb) as author_rows
from public.paper_items_view p
order by p.user_id, p.id;
