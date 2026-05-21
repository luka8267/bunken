create table if not exists public.duplicate_merge_backups (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    merge_group_id uuid not null,
    keeper_paper_id text,
    duplicate_paper_id text,
    keeper_item_id uuid,
    duplicate_item_id uuid,
    keeper_snapshot jsonb not null,
    duplicate_snapshot jsonb not null,
    created_at timestamptz not null default now()
);

create index if not exists duplicate_merge_backups_user_created_idx
    on public.duplicate_merge_backups (user_id, created_at desc);

alter table public.duplicate_merge_backups enable row level security;

drop policy if exists duplicate_merge_backups_own_all
    on public.duplicate_merge_backups;

create policy duplicate_merge_backups_own_all
    on public.duplicate_merge_backups
    for all
    using (user_id = auth.uid())
    with check (user_id = auth.uid());
