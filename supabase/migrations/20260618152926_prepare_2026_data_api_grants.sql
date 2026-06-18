-- Prepare for Supabase's 2026 Data API default-grants change.
-- Existing tables keep working for authenticated users, while anon no longer
-- has broad table privileges in public.

-- Future objects in public should not be exposed to Data API roles implicitly.
alter default privileges for role postgres in schema public
  revoke all privileges on tables from anon, authenticated, service_role;

alter default privileges for role postgres in schema public
  revoke all privileges on sequences from anon, authenticated, service_role;

-- Existing public objects: remove unauthenticated Data API access.
revoke all privileges on all tables in schema public from anon;
revoke all privileges on all sequences in schema public from anon;

-- Keep the application API explicit for signed-in users.
grant select, insert, update, delete on table
  public.attachments,
  public.collection_items,
  public.collection_papers,
  public.collections,
  public.creators,
  public.document_citations,
  public.documents,
  public.duplicate_merge_backups,
  public.item_tags,
  public.items,
  public.paper_tags,
  public.papers,
  public.pdf_annotations,
  public.profiles,
  public.tags
to authenticated;

grant select on table
  public.item_csl_json_view,
  public.paper_items_view
to authenticated;

-- service_role is used only server-side and should remain able to administer
-- the exposed objects.
grant all privileges on all tables in schema public to service_role;
grant all privileges on all sequences in schema public to service_role;

-- Signed-in users do not need schema-maintenance privileges through the Data API.
revoke truncate, references, trigger on all tables in schema public from authenticated;

-- Storage upsert support for the private paper-pdfs bucket. SELECT + INSERT +
-- UPDATE are required when a client replaces an existing object.
do $$
begin
  if not exists (
    select 1
    from pg_policies
    where schemaname = 'storage'
      and tablename = 'objects'
      and policyname = 'paper_files_update_own'
  ) then
    create policy "paper_files_update_own"
    on storage.objects
    for update
    to authenticated
    using (
      bucket_id = 'paper-pdfs'
      and (storage.foldername(name))[1] = (auth.uid())::text
    )
    with check (
      bucket_id = 'paper-pdfs'
      and (storage.foldername(name))[1] = (auth.uid())::text
    );
  end if;
end $$;
