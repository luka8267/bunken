-- Backup before adding item publication metadata.
-- Run this first. It creates restorable snapshots inside the database.

create schema if not exists bunken_backups;

create table if not exists bunken_backups.items_before_metadata_20260517
as table public.items with data;

create table if not exists bunken_backups.paper_items_view_before_metadata_20260517
as select * from public.paper_items_view;

comment on table bunken_backups.items_before_metadata_20260517
is 'Backup of public.items before 202605170002_add_item_publication_metadata.sql';

comment on table bunken_backups.paper_items_view_before_metadata_20260517
is 'Backup of public.paper_items_view rows before 202605170002_add_item_publication_metadata.sql';

select
    (select count(*) from bunken_backups.items_before_metadata_20260517) as backed_up_items,
    (select count(*) from bunken_backups.paper_items_view_before_metadata_20260517) as backed_up_view_rows;
