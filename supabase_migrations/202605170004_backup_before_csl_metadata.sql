-- Backup before adding publication metadata to CSL JSON output.

create schema if not exists bunken_backups;

create table if not exists bunken_backups.item_csl_json_view_before_metadata_20260517
as select * from public.item_csl_json_view;

comment on table bunken_backups.item_csl_json_view_before_metadata_20260517
is 'Backup of public.item_csl_json_view rows before 202605170005_add_csl_publication_metadata.sql';

select
    (select count(*) from bunken_backups.item_csl_json_view_before_metadata_20260517) as backed_up_csl_rows;
