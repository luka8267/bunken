import io
import os
import re
import unicodedata
import uuid

from docx import Document

try:
    from postgrest.exceptions import APIError
except ImportError:
    APIError = Exception

BUCKET_NAME = "paper-pdfs"
PAPER_ITEMS_VIEW = "paper_items_view"
SAFE_STORAGE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
SAFE_STORAGE_EXT_RE = re.compile(r"[^A-Za-z0-9]")
MAX_STORAGE_BASENAME_LENGTH = 80
READING_STATUSES = ["未読", "読書中", "読了", "再読したい", "引用予定"]
SORT_OPTIONS = ["追加順", "年（新しい順）", "年（古い順）", "タイトル", "ステータス"]


def is_missing_relation_error(error):
    error_text = str(error).lower()
    return (
        "paper_items_view" in error_text
        or ("relation" in error_text and "does not exist" in error_text)
    )


def normalize_doi(doi):
    return (doi or "").strip()


def normalize_title_for_match(title):
    normalized = unicodedata.normalize("NFKC", title or "").casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def find_duplicate_paper_groups(papers):
    groups_by_key = {}

    for paper in papers or []:
        doi = normalize_doi(paper.get("doi")).lower()
        if doi:
            groups_by_key.setdefault(("DOI", doi), []).append(paper)

        title = normalize_title_for_match(paper.get("title"))
        year = paper.get("year")
        if title and year:
            groups_by_key.setdefault(("タイトル+年", f"{title}:{year}"), []).append(paper)

    duplicate_groups = []
    seen_group_ids = set()
    for (reason, value), group_papers in groups_by_key.items():
        if len(group_papers) < 2:
            continue

        group_ids = tuple(sorted(str(paper.get("id")) for paper in group_papers))
        if group_ids in seen_group_ids:
            continue
        seen_group_ids.add(group_ids)

        duplicate_groups.append(
            {
                "reason": reason,
                "value": value,
                "papers": group_papers,
            }
        )

    return duplicate_groups


def normalize_tag_input(tags_text):
    seen = set()
    normalized = []
    for tag in (tags_text or "").split(","):
        value = tag.strip()
        if value and value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized


def is_storage_path(value):
    return isinstance(value, str) and bool(value.strip())


def make_safe_storage_filename(filename, default_ext=".pdf"):
    name, ext = os.path.splitext(filename or "")
    ext = ext.lower()
    if ext:
        ext = f".{SAFE_STORAGE_EXT_RE.sub('', ext.lstrip('.'))}"
    ext = ext if ext and ext != "." else default_ext

    normalized_name = unicodedata.normalize("NFKD", name)
    ascii_name = normalized_name.encode("ascii", "ignore").decode("ascii")
    safe_name = SAFE_STORAGE_NAME_RE.sub("-", ascii_name).strip(".-_")
    safe_name = safe_name[:MAX_STORAGE_BASENAME_LENGTH].strip(".-_") or "paper"

    return f"{uuid.uuid4().hex}_{safe_name}{ext}"


def fetch_user_papers(supabase, user_id, columns="*"):
    try:
        return (
            supabase.table(PAPER_ITEMS_VIEW)
            .select(columns)
            .eq("user_id", user_id)
            .order("display_order")
            .execute()
        )
    except APIError as error:
        if is_missing_relation_error(error):
            return (
                supabase.table("papers")
                .select(columns)
                .eq("user_id", user_id)
                .order("display_order")
                .execute()
            )
        error_text = str(error).lower()
        if "uuid" in error_text or "user_id" in error_text:
            raise RuntimeError(
                "papers.user_id と認証ユーザーの紐づけ、または RLS 設定を確認してください。"
            ) from error
        raise


def search_user_papers(supabase, user_id, keyword, columns="id, title, authors, year"):
    normalized_keyword = (keyword or "").strip()
    query = (
        supabase.table(PAPER_ITEMS_VIEW)
        .select(columns)
        .eq("user_id", user_id)
        .order("display_order")
    )

    if normalized_keyword:
        escaped_keyword = normalized_keyword.replace("%", "\\%").replace(",", "\\,")
        query = query.or_(
            f"title.ilike.%{escaped_keyword}%,authors.ilike.%{escaped_keyword}%"
        )

    try:
        return query.execute()
    except APIError as error:
        if not is_missing_relation_error(error):
            raise

    query = (
        supabase.table("papers")
        .select(columns)
        .eq("user_id", user_id)
        .order("display_order")
    )

    if normalized_keyword:
        escaped_keyword = normalized_keyword.replace("%", "\\%").replace(",", "\\,")
        query = query.or_(
            f"title.ilike.%{escaped_keyword}%,authors.ilike.%{escaped_keyword}%"
        )

    return query.execute()


def fetch_user_papers_by_ids(supabase, user_id, paper_ids, columns="id, title"):
    if not paper_ids:
        return None

    try:
        return (
            supabase.table(PAPER_ITEMS_VIEW)
            .select(columns)
            .eq("user_id", user_id)
            .in_("id", paper_ids)
            .execute()
        )
    except APIError as error:
        if not is_missing_relation_error(error):
            raise

    return (
        supabase.table("papers")
        .select(columns)
        .eq("user_id", user_id)
        .in_("id", paper_ids)
        .execute()
    )


def fetch_user_documents(supabase, user_id):
    return (
        supabase.table("documents")
        .select("id, word_document_id, title, citation_style, locale, updated_at")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .execute()
    )


def fetch_document_citations(supabase, document_id):
    return (
        supabase.table("document_citations")
        .select(
            "id, citation_key, word_control_id, citation_items, rendered_text, "
            "sort_order, updated_at"
        )
        .eq("document_id", document_id)
        .order("sort_order")
        .execute()
    )


def fetch_user_collections(supabase, user_id):
    return (
        supabase.table("collections")
        .select("id, name, parent_id, sort_order")
        .eq("user_id", user_id)
        .order("sort_order")
        .order("name")
        .execute()
    )


def create_collection(supabase, user_id, name):
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise ValueError("Collection name is required.")

    max_result = (
        supabase.table("collections")
        .select("sort_order")
        .eq("user_id", user_id)
        .order("sort_order", desc=True)
        .limit(1)
        .execute()
    )
    current_max = max_result.data[0]["sort_order"] if max_result.data else 0

    return (
        supabase.table("collections")
        .insert(
            {
                "user_id": user_id,
                "name": normalized_name,
                "sort_order": (current_max or 0) + 1,
            }
        )
        .execute()
    )


def update_collection(supabase, user_id, collection_id, name):
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise ValueError("Collection name is required.")

    return (
        supabase.table("collections")
        .update({"name": normalized_name})
        .eq("id", collection_id)
        .eq("user_id", user_id)
        .execute()
    )


def delete_collection(supabase, user_id, collection_id):
    return (
        supabase.table("collections")
        .delete()
        .eq("id", collection_id)
        .eq("user_id", user_id)
        .execute()
    )


def fetch_collection_paper_ids(supabase, collection_id):
    result = (
        supabase.table("collection_papers")
        .select("paper_id")
        .eq("collection_id", collection_id)
        .execute()
    )
    return [row["paper_id"] for row in (result.data or [])]


def fetch_collection_counts(supabase, collection_ids):
    if not collection_ids:
        return {}

    result = (
        supabase.table("collection_papers")
        .select("collection_id")
        .in_("collection_id", collection_ids)
        .execute()
    )

    counts = {collection_id: 0 for collection_id in collection_ids}
    for row in result.data or []:
        collection_id = row.get("collection_id")
        counts[collection_id] = counts.get(collection_id, 0) + 1
    return counts


def fetch_paper_collection_ids(supabase, paper_id):
    result = (
        supabase.table("collection_papers")
        .select("collection_id")
        .eq("paper_id", paper_id)
        .execute()
    )
    return [row["collection_id"] for row in (result.data or [])]


def fetch_papers_for_collection(supabase, user_id, collection_id, columns="id, title, authors, year"):
    paper_ids = fetch_collection_paper_ids(supabase, collection_id)
    if not paper_ids:
        return []

    result = fetch_user_papers_by_ids(supabase, user_id, paper_ids, columns=columns)
    return result.data or []


def set_paper_collections(supabase, paper_id, selected_collection_ids):
    desired_ids = set(selected_collection_ids or [])
    current_ids = set(fetch_paper_collection_ids(supabase, paper_id))

    for collection_id in sorted(current_ids - desired_ids):
        (
            supabase.table("collection_papers")
            .delete()
            .eq("paper_id", paper_id)
            .eq("collection_id", collection_id)
            .execute()
        )

    for collection_id in sorted(desired_ids - current_ids):
        (
            supabase.table("collection_papers")
            .insert({"paper_id": paper_id, "collection_id": collection_id})
            .execute()
        )


def sort_papers_dataframe(df, sort_option):
    if df.empty:
        return df

    sorted_df = df.copy()

    if sort_option == "年（新しい順）":
        sorted_df = sorted_df.sort_values(by="year", ascending=False)
    elif sort_option == "年（古い順）":
        sorted_df = sorted_df.sort_values(by="year", ascending=True)
    elif sort_option == "タイトル":
        sorted_df = sorted_df.sort_values(by="title", ascending=True)
    elif sort_option == "ステータス":
        sorted_df = sorted_df.sort_values(by="status", ascending=True)

    sorted_df = sorted_df.reset_index(drop=True)
    sorted_df["ref_no"] = sorted_df.index + 1
    return sorted_df


def make_word_citation(row, style="APA"):
    authors = row.get("authors", "")
    year = row.get("year", "")
    title = row.get("title", "")
    journal = row.get("journal", "")
    doi = row.get("doi", "")

    if style == "APA":
        citation = f"{authors} ({year}). {title}. {journal}."
        if doi:
            citation += f" https://doi.org/{doi}"
    elif style == "Vancouver":
        citation = f"{authors}. {title}. {journal}. {year}."
        if doi:
            citation += f" doi:{doi}"
    elif style == "Nature":
        citation = f"{authors} {title}. {journal} ({year})."
        if doi:
            citation += f" https://doi.org/{doi}"
    else:
        citation = f"{authors} ({year}). {title}. {journal}."

    return citation


def export_to_word_bytes(papers):
    doc = Document()
    doc.add_heading("参考文献", 0)

    for index, paper in enumerate(papers, start=1):
        text = (
            f"[{index}] {paper.get('authors', '')} ({paper.get('year', '')}). "
            f"{paper.get('title', '')}. {paper.get('journal', '')}."
        )
        doc.add_paragraph(text)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


def upload_file_to_storage(
    supabase,
    uploaded_file,
    user_id,
    folder,
    default_ext=".bin",
    default_content_type="application/octet-stream",
):
    safe_name = make_safe_storage_filename(
        getattr(uploaded_file, "name", "attachment"),
        default_ext=default_ext,
    )
    storage_path = f"{user_id}/{folder}/{safe_name}"
    content_type = getattr(uploaded_file, "type", None) or default_content_type

    supabase.storage.from_(BUCKET_NAME).upload(
        path=storage_path,
        file=uploaded_file.read(),
        file_options={"content-type": content_type},
    )
    return storage_path


def upload_pdf_to_storage(supabase, pdf_file, user_id):
    return upload_file_to_storage(
        supabase,
        pdf_file,
        user_id,
        "pdfs",
        default_ext=".pdf",
        default_content_type="application/pdf",
    )


def upload_supporting_file_to_storage(supabase, supporting_file, user_id):
    return upload_file_to_storage(supabase, supporting_file, user_id, "supporting")


def create_pdf_signed_url(supabase, storage_path, expires_in=3600):
    if not isinstance(storage_path, str) or not storage_path.strip():
        return None

    response = (
        supabase.storage.from_(BUCKET_NAME).create_signed_url(
            storage_path,
            expires_in,
        )
    )

    if isinstance(response, dict):
        return response.get("signedURL") or response.get("signedUrl")
    return None


def delete_pdf_from_storage(supabase, storage_path):
    if is_storage_path(storage_path):
        supabase.storage.from_(BUCKET_NAME).remove([storage_path])


def get_or_create_tag_id(supabase, user_id, tag_name):
    tag_result = (
        supabase.table("tags")
        .select("id")
        .eq("name", tag_name)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )

    if tag_result.data:
        return tag_result.data[0]["id"]

    new_tag = supabase.table("tags").insert({"name": tag_name, "user_id": user_id}).execute()
    return new_tag.data[0]["id"]


def save_tags_for_paper(supabase, user_id, paper_id, tags_text):
    for tag_name in normalize_tag_input(tags_text):
        tag_id = get_or_create_tag_id(supabase, user_id, tag_name)
        supabase.table("paper_tags").upsert(
            {"paper_id": paper_id, "tag_id": tag_id}
        ).execute()


def get_tag_map_for_papers(supabase, paper_ids):
    if not paper_ids:
        return {}

    paper_tag_result = (
        supabase.table("paper_tags")
        .select("paper_id, tag_id")
        .in_("paper_id", paper_ids)
        .execute()
    )

    paper_tags = paper_tag_result.data or []
    if not paper_tags:
        return {}

    tag_ids = sorted({row["tag_id"] for row in paper_tags})
    tag_result = supabase.table("tags").select("id, name").in_("id", tag_ids).execute()
    tag_name_map = {row["id"]: row["name"] for row in (tag_result.data or [])}

    tag_map = {paper_id: [] for paper_id in paper_ids}
    for row in paper_tags:
        tag_name = tag_name_map.get(row["tag_id"])
        if tag_name:
            tag_map.setdefault(row["paper_id"], []).append(tag_name)

    return tag_map


def move_paper(supabase, user_id, paper_id, display_order, direction):
    operator = "lt" if direction == "up" else "gt"
    descending = direction == "up"

    neighbor_result = (
        getattr(
            supabase.table("papers")
            .select("id, display_order")
            .eq("user_id", user_id),
            operator,
        )("display_order", display_order)
        .order("display_order", desc=descending)
        .limit(1)
        .execute()
    )

    if not neighbor_result.data:
        return

    neighbor = neighbor_result.data[0]

    (
        supabase.table("papers")
        .update({"display_order": neighbor["display_order"]})
        .eq("id", paper_id)
        .eq("user_id", user_id)
        .execute()
    )

    (
        supabase.table("papers")
        .update({"display_order": display_order})
        .eq("id", neighbor["id"])
        .eq("user_id", user_id)
        .execute()
    )


def update_paper_details(supabase, user_id, paper_id, status, notes, url=None):
    fields = {"status": status, "notes": notes}
    if url is not None:
        fields["url"] = url

    (
        supabase.table("papers")
        .update(fields)
        .eq("id", paper_id)
        .eq("user_id", user_id)
        .execute()
    )


def update_paper_files(
    supabase,
    user_id,
    paper_id,
    pdf_path=None,
    supporting_path=None,
):
    fields = {}
    if pdf_path is not None:
        fields["pdf_path"] = pdf_path
    if supporting_path is not None:
        fields["supporting_path"] = supporting_path

    if not fields:
        return

    (
        supabase.table("papers")
        .update(fields)
        .eq("id", paper_id)
        .eq("user_id", user_id)
        .execute()
    )


def delete_paper(supabase, user_id, row):
    pdf_path = row.get("pdf_path")
    if is_storage_path(pdf_path):
        delete_pdf_from_storage(supabase, pdf_path)

    supporting_path = row.get("supporting_path")
    if is_storage_path(supporting_path):
        delete_pdf_from_storage(supabase, supporting_path)

    supabase.table("paper_tags").delete().eq("paper_id", row["id"]).execute()
    (
        supabase.table("papers")
        .delete()
        .eq("id", row["id"])
        .eq("user_id", user_id)
        .execute()
    )
