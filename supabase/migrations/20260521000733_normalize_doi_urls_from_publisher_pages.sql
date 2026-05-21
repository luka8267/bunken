-- Backup and normalize DOI values that were stored as publisher DOI page URLs
-- such as https://pubs.acs.org/doi/10.1021/....
-- Rollback example:
--   update public.items i
--   set doi = b.doi
--   from bunken_backups.items_before_publisher_doi_url_normalization_20260521 b
--   where i.id = b.id;
--
--   update public.papers p
--   set doi = b.doi
--   from bunken_backups.papers_before_publisher_doi_url_normalization_20260521 b
--   where p.id = b.id;

create schema if not exists bunken_backups;

create table if not exists bunken_backups.items_before_publisher_doi_url_normalization_20260521 as
select *
from public.items
where doi is not null
  and (doi ilike 'http%' or doi ilike 'doi:http%')
  and substring(doi from '(10\.[0-9]{4,9}/[^[:space:]"<>]+)') is not null;

create table if not exists bunken_backups.papers_before_publisher_doi_url_normalization_20260521 as
select *
from public.papers
where doi is not null
  and (doi ilike 'http%' or doi ilike 'doi:http%')
  and substring(doi from '(10\.[0-9]{4,9}/[^[:space:]"<>]+)') is not null;

update public.items
set doi = rtrim(substring(doi from '(10\.[0-9]{4,9}/[^[:space:]"<>]+)'), ').,;]')
where doi is not null
  and (doi ilike 'http%' or doi ilike 'doi:http%')
  and substring(doi from '(10\.[0-9]{4,9}/[^[:space:]"<>]+)') is not null;

update public.papers
set doi = rtrim(substring(doi from '(10\.[0-9]{4,9}/[^[:space:]"<>]+)'), ').,;]')
where doi is not null
  and (doi ilike 'http%' or doi ilike 'doi:http%')
  and substring(doi from '(10\.[0-9]{4,9}/[^[:space:]"<>]+)') is not null;

do $$
declare
    remaining_items integer;
    remaining_papers integer;
begin
    select count(*)
    into remaining_items
    from public.items
    where doi is not null
      and (doi ilike 'http%' or doi ilike 'doi:http%');

    select count(*)
    into remaining_papers
    from public.papers
    where doi is not null
      and (doi ilike 'http%' or doi ilike 'doi:http%');

    if remaining_items > 0 or remaining_papers > 0 then
        raise exception 'HTTP DOI normalization incomplete. items=%, papers=%',
            remaining_items,
            remaining_papers;
    end if;
end $$;
