do $$
declare
    remaining_items integer;
    remaining_papers integer;
begin
    select count(*)
    into remaining_items
    from public.items
    where doi is not null
      and (
        doi ~* '^https?://(dx\.)?doi\.org/'
        or doi ~* '^doi:\s*https?://(dx\.)?doi\.org/'
      );

    select count(*)
    into remaining_papers
    from public.papers
    where doi is not null
      and (
        doi ~* '^https?://(dx\.)?doi\.org/'
        or doi ~* '^doi:\s*https?://(dx\.)?doi\.org/'
      );

    if remaining_items > 0 or remaining_papers > 0 then
        raise exception 'DOI URL normalization incomplete. items=%, papers=%',
            remaining_items,
            remaining_papers;
    end if;
end $$;
