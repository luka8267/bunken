-- Views used by the Data API are read-only surfaces for authenticated users.
revoke all privileges on table
  public.item_csl_json_view,
  public.paper_items_view
from authenticated;

grant select on table
  public.item_csl_json_view,
  public.paper_items_view
to authenticated;
