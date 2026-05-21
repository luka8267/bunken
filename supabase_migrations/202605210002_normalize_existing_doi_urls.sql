-- Normalize previously stored DOI URL values to bare DOI strings.
-- This intentionally targets only doi.org URL forms, leaving other DOI text untouched.

update public.items
set doi = regexp_replace(
    regexp_replace(trim(doi), '^doi:\s*', '', 'i'),
    '^https?://(dx\.)?doi\.org/',
    '',
    'i'
)
where doi is not null
  and (
    doi ~* '^https?://(dx\.)?doi\.org/'
    or doi ~* '^doi:\s*https?://(dx\.)?doi\.org/'
  );

update public.papers
set doi = regexp_replace(
    regexp_replace(trim(doi), '^doi:\s*', '', 'i'),
    '^https?://(dx\.)?doi\.org/',
    '',
    'i'
)
where doi is not null
  and (
    doi ~* '^https?://(dx\.)?doi\.org/'
    or doi ~* '^doi:\s*https?://(dx\.)?doi\.org/'
  );
