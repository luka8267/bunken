-- Backup rows before normalizing stored DOI URL values.
-- Rollback example:
--   update public.items i
--   set doi = b.doi
--   from bunken_backups.items_before_doi_url_normalization_20260521 b
--   where i.id = b.id;
--
--   update public.papers p
--   set doi = b.doi
--   from bunken_backups.papers_before_doi_url_normalization_20260521 b
--   where p.id = b.id;

create schema if not exists bunken_backups;

create table if not exists bunken_backups.items_before_doi_url_normalization_20260521 as
select *
from public.items
where doi is not null
  and (
    doi ~* '^https?://(dx\.)?doi\.org/'
    or doi ~* '^doi:\s*https?://(dx\.)?doi\.org/'
  );

create table if not exists bunken_backups.papers_before_doi_url_normalization_20260521 as
select *
from public.papers
where doi is not null
  and (
    doi ~* '^https?://(dx\.)?doi\.org/'
    or doi ~* '^doi:\s*https?://(dx\.)?doi\.org/'
  );
