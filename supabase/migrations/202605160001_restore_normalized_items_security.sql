-- Restore the normalized item-backed library schema and security model.
-- This migration is intentionally non-destructive: it creates missing objects,
-- adds missing columns/constraints/policies, and does not delete user data.

create table if not exists public.items (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    item_type text not null default 'journalArticle',
    title text not null default '',
    publication_title text not null default '',
    date text,
    year integer,
    doi text,
    url text,
    abstract_note text,
    language text,
    extra jsonb not null default '{}'::jsonb,
    legacy_paper_id text,
    legacy_source text not null default 'papers',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint items_item_type_not_blank check (length(btrim(item_type)) > 0),
    constraint items_legacy_pair_unique unique (user_id, legacy_source, legacy_paper_id)
);

alter table public.items
    add column if not exists id uuid default gen_random_uuid(),
    add column if not exists user_id uuid references auth.users(id) on delete cascade,
    add column if not exists item_type text default 'journalArticle',
    add column if not exists title text default '',
    add column if not exists publication_title text default '',
    add column if not exists date text,
    add column if not exists year integer,
    add column if not exists doi text,
    add column if not exists url text,
    add column if not exists abstract_note text,
    add column if not exists language text,
    add column if not exists extra jsonb default '{}'::jsonb,
    add column if not exists legacy_paper_id text,
    add column if not exists legacy_source text default 'papers',
    add column if not exists created_at timestamptz default now(),
    add column if not exists updated_at timestamptz default now();

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'items_item_type_not_blank'
          and conrelid = 'public.items'::regclass
    ) then
        alter table public.items
        add constraint items_item_type_not_blank
        check (length(btrim(item_type)) > 0);
    end if;

    if not exists (
        select 1 from pg_constraint
        where conname = 'items_legacy_pair_unique'
          and conrelid = 'public.items'::regclass
    ) then
        alter table public.items
        add constraint items_legacy_pair_unique
        unique (user_id, legacy_source, legacy_paper_id);
    end if;
end $$;

create index if not exists items_user_id_created_at_idx
on public.items (user_id, created_at desc);

create index if not exists items_user_id_doi_idx
on public.items (user_id, doi)
where doi is not null;

create index if not exists items_user_id_title_idx
on public.items (user_id, title);

create table if not exists public.creators (
    id uuid primary key default gen_random_uuid(),
    item_id uuid not null references public.items(id) on delete cascade,
    creator_type text not null default 'author',
    first_name text,
    last_name text,
    literal_name text,
    position integer not null default 1,
    created_at timestamptz not null default now(),
    constraint creators_name_present check (
        coalesce(btrim(first_name), '') <> ''
        or coalesce(btrim(last_name), '') <> ''
        or coalesce(btrim(literal_name), '') <> ''
    ),
    constraint creators_item_position_unique unique (item_id, creator_type, position)
);

alter table public.creators
    add column if not exists id uuid default gen_random_uuid(),
    add column if not exists item_id uuid references public.items(id) on delete cascade,
    add column if not exists creator_type text default 'author',
    add column if not exists first_name text,
    add column if not exists last_name text,
    add column if not exists literal_name text,
    add column if not exists position integer default 1,
    add column if not exists created_at timestamptz default now();

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'creators_name_present'
          and conrelid = 'public.creators'::regclass
    ) then
        alter table public.creators
        add constraint creators_name_present
        check (
            coalesce(btrim(first_name), '') <> ''
            or coalesce(btrim(last_name), '') <> ''
            or coalesce(btrim(literal_name), '') <> ''
        );
    end if;

    if not exists (
        select 1 from pg_constraint
        where conname = 'creators_item_position_unique'
          and conrelid = 'public.creators'::regclass
    ) then
        alter table public.creators
        add constraint creators_item_position_unique
        unique (item_id, creator_type, position);
    end if;
end $$;

create index if not exists creators_item_id_position_idx
on public.creators (item_id, position);

create table if not exists public.attachments (
    id uuid primary key default gen_random_uuid(),
    item_id uuid not null references public.items(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    kind text not null,
    storage_path text,
    filename text,
    content_type text,
    title text,
    created_at timestamptz not null default now(),
    constraint attachments_kind_check
        check (kind = any (array['pdf', 'supporting', 'snapshot', 'link', 'other'])),
    constraint attachments_storage_owned_by_user
        check (storage_path is null or split_part(storage_path, '/', 1) = user_id::text),
    constraint attachments_item_storage_path_unique unique (item_id, storage_path)
);

alter table public.attachments
    add column if not exists id uuid default gen_random_uuid(),
    add column if not exists item_id uuid references public.items(id) on delete cascade,
    add column if not exists user_id uuid references auth.users(id) on delete cascade,
    add column if not exists kind text,
    add column if not exists storage_path text,
    add column if not exists filename text,
    add column if not exists content_type text,
    add column if not exists title text,
    add column if not exists created_at timestamptz default now();

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'attachments_kind_check'
          and conrelid = 'public.attachments'::regclass
    ) then
        alter table public.attachments
        add constraint attachments_kind_check
        check (kind = any (array['pdf', 'supporting', 'snapshot', 'link', 'other']));
    end if;

    if not exists (
        select 1 from pg_constraint
        where conname = 'attachments_storage_owned_by_user'
          and conrelid = 'public.attachments'::regclass
    ) then
        alter table public.attachments
        add constraint attachments_storage_owned_by_user
        check (storage_path is null or split_part(storage_path, '/', 1) = user_id::text);
    end if;

    if not exists (
        select 1 from pg_constraint
        where conname = 'attachments_item_storage_path_unique'
          and conrelid = 'public.attachments'::regclass
    ) then
        alter table public.attachments
        add constraint attachments_item_storage_path_unique
        unique (item_id, storage_path);
    end if;
end $$;

create index if not exists attachments_item_id_idx
on public.attachments (item_id);

create index if not exists attachments_user_id_idx
on public.attachments (user_id);

create table if not exists public.item_tags (
    item_id uuid not null references public.items(id) on delete cascade,
    tag_id text not null,
    created_at timestamptz not null default now(),
    primary key (item_id, tag_id)
);

alter table public.item_tags
    add column if not exists item_id uuid references public.items(id) on delete cascade,
    add column if not exists tag_id text,
    add column if not exists created_at timestamptz default now();

create index if not exists item_tags_tag_id_idx
on public.item_tags (tag_id);

create table if not exists public.collection_items (
    collection_id uuid not null references public.collections(id) on delete cascade,
    item_id uuid not null references public.items(id) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (collection_id, item_id)
);

alter table public.collection_items
    add column if not exists collection_id uuid references public.collections(id) on delete cascade,
    add column if not exists item_id uuid references public.items(id) on delete cascade,
    add column if not exists created_at timestamptz default now();

create index if not exists collection_items_item_id_idx
on public.collection_items (item_id);

alter table public.items enable row level security;
alter table public.creators enable row level security;
alter table public.attachments enable row level security;
alter table public.item_tags enable row level security;
alter table public.collection_items enable row level security;

drop policy if exists "items_own_all" on public.items;
create policy "items_own_all"
on public.items
for all
to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());

drop policy if exists "creators_own_items_all" on public.creators;
create policy "creators_own_items_all"
on public.creators
for all
to authenticated
using (
    exists (
        select 1 from public.items
        where items.id = creators.item_id
          and items.user_id = auth.uid()
    )
)
with check (
    exists (
        select 1 from public.items
        where items.id = creators.item_id
          and items.user_id = auth.uid()
    )
);

drop policy if exists "attachments_own_all" on public.attachments;
create policy "attachments_own_all"
on public.attachments
for all
to authenticated
using (user_id = auth.uid())
with check (
    user_id = auth.uid()
    and exists (
        select 1 from public.items
        where items.id = attachments.item_id
          and items.user_id = auth.uid()
    )
);

drop policy if exists "item_tags_own_all" on public.item_tags;
create policy "item_tags_own_all"
on public.item_tags
for all
to authenticated
using (
    exists (
        select 1 from public.items
        where items.id = item_tags.item_id
          and items.user_id = auth.uid()
    )
    and exists (
        select 1 from public.tags
        where tags.id::text = item_tags.tag_id
          and tags.user_id = auth.uid()
    )
)
with check (
    exists (
        select 1 from public.items
        where items.id = item_tags.item_id
          and items.user_id = auth.uid()
    )
    and exists (
        select 1 from public.tags
        where tags.id::text = item_tags.tag_id
          and tags.user_id = auth.uid()
    )
);

drop policy if exists "collection_items_own_all" on public.collection_items;
create policy "collection_items_own_all"
on public.collection_items
for all
to authenticated
using (
    exists (
        select 1 from public.collections
        where collections.id = collection_items.collection_id
          and collections.user_id = auth.uid()
    )
    and exists (
        select 1 from public.items
        where items.id = collection_items.item_id
          and items.user_id = auth.uid()
    )
)
with check (
    exists (
        select 1 from public.collections
        where collections.id = collection_items.collection_id
          and collections.user_id = auth.uid()
    )
    and exists (
        select 1 from public.items
        where items.id = collection_items.item_id
          and items.user_id = auth.uid()
    )
);

-- The older fallback view selected directly from public.papers and may have a
-- different column shape. Dropping a view does not delete table data.
drop view if exists public.paper_items_view;

create view public.paper_items_view
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
    items.updated_at
from public.items
left join creator_summary
  on creator_summary.item_id = items.id
left join pdf_attachments
  on pdf_attachments.item_id = items.id
left join supporting_attachments
  on supporting_attachments.item_id = items.id;

grant usage on schema public to authenticated;
grant select, insert, update, delete on table public.items to authenticated;
grant select, insert, update, delete on table public.creators to authenticated;
grant select, insert, update, delete on table public.attachments to authenticated;
grant select, insert, update, delete on table public.item_tags to authenticated;
grant select, insert, update, delete on table public.collection_items to authenticated;
grant select on table public.paper_items_view to authenticated;
