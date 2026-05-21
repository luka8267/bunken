import io
import math
import os
import re
import unicodedata
import uuid

from docx import Document

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from postgrest.exceptions import APIError
except ImportError:
    APIError = Exception

BUCKET_NAME = "paper-pdfs"
PAPER_ITEMS_VIEW = "paper_items_view"
ITEM_METADATA_COLUMNS = ("volume", "issue", "pages", "publisher", "item_type")
SAFE_STORAGE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
SAFE_STORAGE_EXT_RE = re.compile(r"[^A-Za-z0-9]")
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)
MAX_STORAGE_BASENAME_LENGTH = 80
READING_STATUSES = ["未読", "読書中", "読了", "再読したい", "引用予定"]
SORT_OPTIONS = ["追加順", "年（新しい順）", "年（古い順）", "タイトル", "ステータス"]


def is_missing_relation_error(error):
    error_text = str(error).lower()
    return (
        "paper_items_view" in error_text
        or ("relation" in error_text and "does not exist" in error_text)
        or ("could not find the table" in error_text and "schema cache" in error_text)
        or ("could not find" in error_text and "relation" in error_text)
    )


def is_missing_metadata_column_error(error):
    error_text = str(error).lower()
    if "could not find" not in error_text and "column" not in error_text:
        return False
    return any(column in error_text for column in ITEM_METADATA_COLUMNS)


def strip_metadata_columns(columns):
    if columns == "*":
        return columns

    kept_columns = []
    for column in (columns or "").split(","):
        normalized = column.strip()
        if normalized and normalized not in ITEM_METADATA_COLUMNS:
            kept_columns.append(normalized)
    return ", ".join(kept_columns) or columns


def is_duplicate_key_error(error):
    error_text = str(error).lower()
    return (
        "duplicate" in error_text
        or "23505" in error_text
        or "already exists" in error_text
    )


def is_permission_error(error):
    error_text = str(error).lower()
    return (
        "42501" in error_text
        or "permission denied" in error_text
        or "row-level security" in error_text
        or "violates row-level security" in error_text
    )


def normalize_json_value(value):
    if value is None:
        return None
    if value.__class__.__name__ in {"NAType", "NaTType"}:
        return None
    try:
        if value != value:
            return None
    except Exception:
        pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def normalize_optional_db_value(value):
    value = normalize_json_value(value)
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    return value


def normalize_text_db_value(value):
    value = normalize_json_value(value)
    if value is None:
        return ""
    return str(value)


def normalize_doi(doi):
    text = (doi or "").strip()
    if not text:
        return ""
    text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    if text.lower().startswith(("http://", "https://")):
        match = DOI_RE.search(text)
        if match:
            text = match.group(0)
    text = text.strip().strip("<>").rstrip(").,;]")
    return text


def extract_doi_from_text(text):
    match = DOI_RE.search(text or "")
    if not match:
        return ""
    return match.group(0).rstrip(").,;]")


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


def normalize_optional_id(value):
    if value is None:
        return None
    if value != value:
        return None
    text = str(value).strip()
    return text or None


def normalize_uuid_text(value):
    text = normalize_optional_id(value)
    if not text:
        return None
    try:
        return str(uuid.UUID(text))
    except (TypeError, ValueError):
        return None


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
        if is_missing_metadata_column_error(error):
            fallback_columns = strip_metadata_columns(columns)
            if fallback_columns != columns:
                return fetch_user_papers(supabase, user_id, fallback_columns)
        if is_missing_relation_error(error):
            return (
                supabase.table("papers")
                .select(strip_metadata_columns(columns))
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
        if is_missing_metadata_column_error(error):
            fallback_columns = strip_metadata_columns(columns)
            if fallback_columns != columns:
                return search_user_papers(
                    supabase,
                    user_id,
                    keyword,
                    fallback_columns,
                )
        if not is_missing_relation_error(error):
            raise

    query = (
        supabase.table("papers")
        .select(strip_metadata_columns(columns))
        .eq("user_id", user_id)
        .order("display_order")
    )

    if normalized_keyword:
        escaped_keyword = normalized_keyword.replace("%", "\\%").replace(",", "\\,")
        query = query.or_(
            f"title.ilike.%{escaped_keyword}%,authors.ilike.%{escaped_keyword}%"
        )

    return query.execute()


def filter_papers(
    papers,
    keyword="",
    year_from=None,
    year_to=None,
    status="",
    attachment_filter="",
):
    normalized_keyword = (keyword or "").casefold().strip()
    filtered = []

    for paper in papers or []:
        if normalized_keyword:
            haystack = " ".join(
                str(paper.get(field) or "")
                for field in ("title", "authors", "journal", "doi", "notes")
            ).casefold()
            if normalized_keyword not in haystack:
                continue

        year = paper.get("year")
        if year_from is not None and year and int(year) < year_from:
            continue
        if year_to is not None and year and int(year) > year_to:
            continue

        if status and paper.get("status") != status:
            continue

        has_pdf = bool(paper.get("pdf_path"))
        has_supporting = bool(paper.get("supporting_path"))
        if attachment_filter == "PDFあり" and not has_pdf:
            continue
        if attachment_filter == "補足資料あり" and not has_supporting:
            continue
        if attachment_filter == "添付あり" and not (has_pdf or has_supporting):
            continue
        if attachment_filter == "添付なし" and (has_pdf or has_supporting):
            continue

        filtered.append(paper)

    return filtered


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
        if is_missing_metadata_column_error(error):
            fallback_columns = strip_metadata_columns(columns)
            if fallback_columns != columns:
                return fetch_user_papers_by_ids(
                    supabase,
                    user_id,
                    paper_ids,
                    fallback_columns,
                )
        if not is_missing_relation_error(error):
            raise

    return (
        supabase.table("papers")
        .select(strip_metadata_columns(columns))
        .eq("user_id", user_id)
        .in_("id", paper_ids)
        .execute()
    )


def find_existing_user_paper_by_doi(supabase, user_id, doi, columns="id, title"):
    normalized_doi = normalize_doi(doi)
    if not normalized_doi:
        return None

    try:
        result = (
            supabase.table(PAPER_ITEMS_VIEW)
            .select(columns)
            .eq("user_id", user_id)
            .eq("doi", normalized_doi)
            .limit(1)
            .execute()
        )
    except APIError as error:
        if is_missing_metadata_column_error(error):
            fallback_columns = strip_metadata_columns(columns)
            if fallback_columns != columns:
                return find_existing_user_paper_by_doi(
                    supabase,
                    user_id,
                    doi,
                    fallback_columns,
                )
        if not is_missing_relation_error(error):
            raise
        result = (
            supabase.table("papers")
            .select(strip_metadata_columns(columns))
            .eq("user_id", user_id)
            .eq("doi", normalized_doi)
            .limit(1)
            .execute()
        )

    return (result.data or [None])[0]


def get_next_display_order(supabase, user_id):
    try:
        result = fetch_user_papers(
            supabase,
            user_id,
            columns="display_order",
        )
        values = [
            int(row["display_order"])
            for row in (result.data or [])
            if row.get("display_order") is not None
        ]
        return (max(values) if values else 0) + 1
    except Exception:
        result = (
            supabase.table("papers")
            .select("display_order")
            .eq("user_id", user_id)
            .order("display_order", desc=True)
            .limit(1)
            .execute()
        )
        current_max = result.data[0]["display_order"] if result.data else 0
        return (current_max or 0) + 1


def create_attachment_row(supabase, user_id, item_id, kind, storage_path):
    if not is_storage_path(storage_path):
        return

    (
        supabase.table("attachments")
        .insert(
            {
                "item_id": item_id,
                "user_id": user_id,
                "kind": kind,
                "storage_path": storage_path,
            }
        )
        .execute()
    )


def create_item_creator_rows(supabase, item_id, authors):
    names = [name.strip() for name in (authors or "").split(",") if name.strip()]
    for position, name in enumerate(names, start=1):
        (
            supabase.table("creators")
            .insert(
                {
                    "item_id": item_id,
                    "creator_type": "author",
                    "literal_name": name,
                    "position": position,
                }
            )
            .execute()
        )


def create_item_backed_paper(
    supabase,
    user_id,
    title,
    authors,
    journal,
    year,
    doi,
    url,
    pdf_path,
    supporting_path,
    status,
    notes,
    display_order,
    volume="",
    issue="",
    pages="",
    publisher="",
    item_type="journalArticle",
):
    item_payload = {
        "user_id": user_id,
        "item_type": item_type or "journalArticle",
        "title": title,
        "publication_title": journal,
        "year": int(year),
        "doi": doi or None,
        "url": url or None,
        "abstract_note": notes,
        "extra": {
            "legacy_status": status,
            "legacy_display_order": str(display_order),
        },
    }
    for field, value in (
        ("volume", volume),
        ("issue", issue),
        ("pages", pages),
        ("publisher", publisher),
    ):
        if value:
            item_payload[field] = value

    item_result = (
        supabase.table("items")
        .insert(item_payload)
        .execute()
    )
    item_id = item_result.data[0]["id"]
    create_item_creator_rows(supabase, item_id, authors)
    create_attachment_row(supabase, user_id, item_id, "pdf", pdf_path)
    create_attachment_row(supabase, user_id, item_id, "supporting", supporting_path)
    return {"id": str(item_id), "item_id": item_id}


def create_legacy_paper(
    supabase,
    user_id,
    title,
    authors,
    journal,
    year,
    doi,
    url,
    pdf_path,
    supporting_path,
    status,
    notes,
    display_order,
    volume="",
    issue="",
    pages="",
    publisher="",
    item_type="journalArticle",
):
    insert_result = (
        supabase.table("papers")
        .insert(
            {
                "title": title,
                "authors": authors,
                "journal": journal,
                "year": int(year),
                "doi": doi or None,
                "url": url or None,
                "pdf_path": pdf_path,
                "supporting_path": supporting_path,
                "user_id": user_id,
                "display_order": display_order,
                "status": status,
                "notes": notes,
            }
        )
        .execute()
    )
    return {"id": insert_result.data[0]["id"], "item_id": None}


def create_user_paper(
    supabase,
    user_id,
    title,
    authors,
    journal,
    year,
    doi,
    url,
    pdf_path,
    supporting_path,
    status,
    notes,
    display_order,
    volume="",
    issue="",
    pages="",
    publisher="",
    item_type="journalArticle",
):
    try:
        try:
            return create_item_backed_paper(
                supabase,
                user_id,
                title,
                authors,
                journal,
                year,
                doi,
                url,
                pdf_path,
                supporting_path,
                status,
                notes,
                display_order,
                volume,
                issue,
                pages,
                publisher,
                item_type,
            )
        except APIError as error:
            if not is_missing_metadata_column_error(error):
                raise
            return create_item_backed_paper(
                supabase,
                user_id,
                title,
                authors,
                journal,
                year,
                doi,
                url,
                pdf_path,
                supporting_path,
                status,
                notes,
                display_order,
            )
    except APIError as error:
        if not is_missing_relation_error(error) and "items" not in str(error).lower():
            raise

    return create_legacy_paper(
        supabase,
        user_id,
        title,
        authors,
        journal,
        year,
        doi,
        url,
        pdf_path,
        supporting_path,
        status,
        notes,
        display_order,
        volume,
        issue,
        pages,
        publisher,
        item_type,
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
            "context_text, sort_order, updated_at"
        )
        .eq("document_id", document_id)
        .order("sort_order")
        .execute()
    )


def delete_user_document(supabase, user_id, document_id):
    (
        supabase.table("document_citations")
        .delete()
        .eq("document_id", document_id)
        .execute()
    )
    return (
        supabase.table("documents")
        .delete()
        .eq("id", document_id)
        .eq("user_id", user_id)
        .execute()
    )


def citation_search_text(citation, paper_map):
    parts = [
        citation.get("rendered_text"),
        citation.get("context_text"),
        citation.get("updated_at"),
    ]
    for item in citation.get("citation_items") or []:
        if not isinstance(item, dict):
            continue
        parts.extend(
            [
                item.get("locator"),
                item.get("referenceNumber"),
            ]
        )
        paper = paper_map.get(str(item.get("paperId") or ""))
        if paper:
            parts.extend(
                [
                    paper.get("title"),
                    paper.get("authors"),
                    paper.get("journal"),
                    paper.get("year"),
                    paper.get("doi"),
                ]
            )
    return " ".join(str(part) for part in parts if part not in (None, ""))


def filter_document_citations(citations, paper_map, keyword):
    normalized_keyword = (keyword or "").strip().lower()
    if not normalized_keyword:
        return list(citations)
    return [
        citation
        for citation in citations
        if normalized_keyword in citation_search_text(citation, paper_map).lower()
    ]


def build_document_citation_export_rows(citations, paper_map):
    rows = []
    for citation in citations:
        base = {
            "順序": citation.get("sort_order") or "",
            "引用表示": citation.get("rendered_text") or "",
            "引用に使った文": citation.get("context_text") or "",
            "更新日時": citation.get("updated_at") or "",
        }
        items = [
            item
            for item in (citation.get("citation_items") or [])
            if isinstance(item, dict)
        ]
        if not items:
            rows.append(
                {
                    **base,
                    "文献タイトル": "",
                    "著者": "",
                    "年": "",
                    "掲載誌": "",
                    "DOI": "",
                    "参考文献番号": "",
                    "位置": "",
                }
            )
            continue

        for item in items:
            paper = paper_map.get(str(item.get("paperId") or "")) or {}
            rows.append(
                {
                    **base,
                    "文献タイトル": paper.get("title") or "",
                    "著者": paper.get("authors") or "",
                    "年": paper.get("year") or "",
                    "掲載誌": paper.get("journal") or "",
                    "DOI": paper.get("doi") or "",
                    "参考文献番号": item.get("referenceNumber") or "",
                    "位置": item.get("locator") or "",
                }
            )
    return rows


def get_document_citation_usage_map(supabase, user_id, papers):
    paper_refs = {
        str(reference_id)
        for paper in papers
        for reference_id in get_paper_reference_ids(paper)
    }
    usage_map = {reference_id: [] for reference_id in paper_refs}
    if not paper_refs:
        return usage_map

    documents_result = fetch_user_documents(supabase, user_id)
    for document in documents_result.data or []:
        citations_result = fetch_document_citations(supabase, document["id"])
        for citation in citations_result.data or []:
            for item in citation.get("citation_items") or []:
                if not isinstance(item, dict):
                    continue
                paper_id = str(item.get("paperId") or "")
                if paper_id not in paper_refs:
                    continue
                usage_map.setdefault(paper_id, []).append(
                    {
                        "document_title": document.get("title") or "無題",
                        "citation_text": citation.get("rendered_text") or "",
                        "context_text": citation.get("context_text") or "",
                        "reference_number": item.get("referenceNumber"),
                        "locator": item.get("locator"),
                        "updated_at": citation.get("updated_at") or "",
                    }
                )

    return usage_map


def replace_paper_id_in_document_citations(supabase, user_id, source_paper_id, target_paper_id):
    source_ids = source_paper_id if isinstance(source_paper_id, (list, tuple, set)) else [source_paper_id]
    source_texts = {str(source_id) for source_id in source_ids if source_id is not None}
    updated_count = 0

    documents_result = fetch_user_documents(supabase, user_id)
    for document in documents_result.data or []:
        citations_result = fetch_document_citations(supabase, document["id"])
        for citation in citations_result.data or []:
            citation_items = citation.get("citation_items") or []
            changed = False
            for item in citation_items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("paperId")) in source_texts:
                    item["paperId"] = target_paper_id
                    changed = True

            if changed:
                (
                    supabase.table("document_citations")
                    .update({"citation_items": citation_items})
                    .eq("id", citation["id"])
                    .execute()
                )
                updated_count += 1

    return updated_count


def paper_has_document_citation_refs(supabase, user_id, paper_id):
    paper_ids = paper_id if isinstance(paper_id, (list, tuple, set)) else [paper_id]
    paper_texts = {str(value) for value in paper_ids if value is not None}
    documents_result = fetch_user_documents(supabase, user_id)
    for document in documents_result.data or []:
        citations_result = fetch_document_citations(supabase, document["id"])
        for citation in citations_result.data or []:
            for item in citation.get("citation_items") or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("paperId")) in paper_texts:
                    return True
    return False


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
    return [str(row["paper_id"]) for row in (result.data or [])]


def fetch_collection_item_ids(supabase, collection_id):
    try:
        result = (
            supabase.table("collection_items")
            .select("item_id")
            .eq("collection_id", collection_id)
            .execute()
        )
    except APIError as error:
        if is_missing_relation_error(error):
            return []
        raise
    return [str(row["item_id"]) for row in (result.data or [])]


def fetch_collection_counts(supabase, collection_ids):
    if not collection_ids:
        return {}

    references_by_collection = {collection_id: set() for collection_id in collection_ids}

    paper_result = (
        supabase.table("collection_papers")
        .select("collection_id, paper_id")
        .in_("collection_id", collection_ids)
        .execute()
    )
    for row in paper_result.data or []:
        collection_id = row.get("collection_id")
        paper_id = normalize_optional_id(row.get("paper_id"))
        if collection_id in references_by_collection and paper_id:
            references_by_collection[collection_id].add(("paper", paper_id))

    try:
        item_result = (
            supabase.table("collection_items")
            .select("collection_id, item_id")
            .in_("collection_id", collection_ids)
            .execute()
        )
    except APIError as error:
        if is_missing_relation_error(error):
            return {
                collection_id: len(references)
                for collection_id, references in references_by_collection.items()
            }
        raise

    item_rows = item_result.data or []
    item_ids = [
        item_id
        for item_id in (normalize_optional_id(row.get("item_id")) for row in item_rows)
        if item_id
    ]
    legacy_key_by_item_id = {}
    if item_ids:
        item_metadata = (
            supabase.table("items")
            .select("id, legacy_source, legacy_paper_id")
            .in_("id", item_ids)
            .execute()
        )
        for row in item_metadata.data or []:
            item_id = normalize_optional_id(row.get("id"))
            legacy_paper_id = normalize_optional_id(row.get("legacy_paper_id"))
            if (
                item_id
                and row.get("legacy_source") == "papers"
                and legacy_paper_id
            ):
                legacy_key_by_item_id[item_id] = ("paper", legacy_paper_id)

    for row in item_rows:
        collection_id = row.get("collection_id")
        item_id = normalize_optional_id(row.get("item_id"))
        if collection_id in references_by_collection and item_id:
            references_by_collection[collection_id].add(
                legacy_key_by_item_id.get(item_id, ("item", item_id))
            )

    return {
        collection_id: len(references)
        for collection_id, references in references_by_collection.items()
    }


def fetch_paper_collection_ids(supabase, paper_id, item_id=None):
    collection_ids = set()
    if paper_id and not normalize_uuid_text(paper_id):
        paper_result = (
            supabase.table("collection_papers")
            .select("collection_id")
            .eq("paper_id", paper_id)
            .execute()
        )
        collection_ids.update(row["collection_id"] for row in (paper_result.data or []))

    if item_id:
        try:
            item_result = (
                supabase.table("collection_items")
                .select("collection_id")
                .eq("item_id", item_id)
                .execute()
            )
            collection_ids.update(row["collection_id"] for row in (item_result.data or []))
        except APIError as error:
            if not is_missing_relation_error(error):
                raise

    return sorted(collection_ids)


def add_column_if_missing(columns, column):
    if columns == "*":
        return columns
    selected_columns = [value.strip() for value in columns.split(",")]
    if column in selected_columns:
        return columns
    return f"{columns}, {column}"


def fetch_papers_for_collection(supabase, user_id, collection_id, columns="id, title, authors, year"):
    paper_ids = fetch_collection_paper_ids(supabase, collection_id)
    item_ids = fetch_collection_item_ids(supabase, collection_id)
    reference_ids = set(paper_ids + item_ids)
    if not reference_ids:
        return []

    fetch_columns = add_column_if_missing(columns, "item_id") if item_ids else columns
    try:
        result = fetch_user_papers(supabase, user_id, columns=fetch_columns)
    except APIError:
        result = fetch_user_papers(supabase, user_id, columns=columns)
    return [
        paper
        for paper in (result.data or [])
        if str(paper.get("id")) in reference_ids
        or str(paper.get("item_id")) in reference_ids
    ]


def set_paper_collections(supabase, paper_id, selected_collection_ids, item_id=None):
    desired_ids = set(selected_collection_ids or [])
    current_ids = set(fetch_paper_collection_ids(supabase, paper_id, item_id))
    table_name = "collection_items" if item_id else "collection_papers"
    id_column = "item_id" if item_id else "paper_id"
    record_id = item_id or paper_id
    item_collection_table_missing = False
    legacy_paper_id = paper_id if paper_id and not normalize_uuid_text(paper_id) else None

    for collection_id in sorted(current_ids - desired_ids):
        if item_id and legacy_paper_id:
            (
                supabase.table("collection_papers")
                .delete()
                .eq("paper_id", legacy_paper_id)
                .eq("collection_id", collection_id)
                .execute()
            )
        try:
            (
                supabase.table(table_name)
                .delete()
                .eq(id_column, record_id)
                .eq("collection_id", collection_id)
                .execute()
            )
        except APIError as error:
            if not (
                item_id
                and (is_missing_relation_error(error) or is_permission_error(error))
            ):
                raise
            item_collection_table_missing = True

    for collection_id in sorted(desired_ids - current_ids):
        try:
            (
                supabase.table(table_name)
                .insert({id_column: record_id, "collection_id": collection_id})
                .execute()
            )
        except APIError as error:
            if item_id and (is_missing_relation_error(error) or is_permission_error(error)):
                item_collection_table_missing = True
                if not legacy_paper_id:
                    raise
                try:
                    (
                        supabase.table("collection_papers")
                        .insert(
                            {
                                "paper_id": legacy_paper_id,
                                "collection_id": collection_id,
                            }
                        )
                        .execute()
                    )
                except APIError as fallback_error:
                    if not is_duplicate_key_error(fallback_error):
                        raise RuntimeError(
                            "collection_items migration is not applied, and the "
                            "legacy collection_papers fallback could not save this "
                            "membership. Apply the normalized collection migration."
                        ) from fallback_error
            elif not is_duplicate_key_error(error):
                raise

    if item_collection_table_missing:
        return


def copy_paper_tags(supabase, source_paper_id, target_paper_id):
    tag_result = (
        supabase.table("paper_tags")
        .select("tag_id")
        .eq("paper_id", source_paper_id)
        .execute()
    )

    for row in tag_result.data or []:
        try:
            (
                supabase.table("paper_tags")
                .insert({"paper_id": target_paper_id, "tag_id": row["tag_id"]})
                .execute()
            )
        except APIError as error:
            if not is_duplicate_key_error(error):
                raise


def copy_paper_collections(supabase, source_paper_id, target_paper_id):
    collection_result = (
        supabase.table("collection_papers")
        .select("collection_id")
        .eq("paper_id", source_paper_id)
        .execute()
    )

    for row in collection_result.data or []:
        try:
            (
                supabase.table("collection_papers")
                .insert(
                    {
                        "paper_id": target_paper_id,
                        "collection_id": row["collection_id"],
                    }
                )
                .execute()
            )
        except APIError as error:
            if not is_duplicate_key_error(error):
                raise


def copy_item_tags(supabase, source_item_id, target_item_id):
    tag_result = (
        supabase.table("item_tags")
        .select("tag_id")
        .eq("item_id", source_item_id)
        .execute()
    )

    for row in tag_result.data or []:
        try:
            (
                supabase.table("item_tags")
                .insert({"item_id": target_item_id, "tag_id": row["tag_id"]})
                .execute()
            )
        except APIError as error:
            if not is_duplicate_key_error(error):
                raise


def copy_item_collections(supabase, source_item_id, target_item_id):
    collection_result = (
        supabase.table("collection_items")
        .select("collection_id")
        .eq("item_id", source_item_id)
        .execute()
    )

    for row in collection_result.data or []:
        try:
            (
                supabase.table("collection_items")
                .insert(
                    {
                        "item_id": target_item_id,
                        "collection_id": row["collection_id"],
                    }
                )
                .execute()
            )
        except APIError as error:
            if not is_duplicate_key_error(error):
                raise


def ensure_user_owns_item(supabase, user_id, item_id):
    result = (
        supabase.table("items")
        .select("id")
        .eq("id", item_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise RuntimeError("Item ownership could not be confirmed.")


def fetch_item_storage_paths(supabase, user_id, item_id):
    result = (
        supabase.table("attachments")
        .select("storage_path")
        .eq("item_id", item_id)
        .eq("user_id", user_id)
        .execute()
    )
    return [
        row["storage_path"]
        for row in (result.data or [])
        if is_storage_path(row.get("storage_path"))
    ]


def transfer_item_attachments(
    supabase,
    user_id,
    source_item_id,
    target_item_id,
    keeper,
    duplicate,
):
    conflicts = []
    transferred_fields = {}

    for _, field, label in (
        ("pdf", "pdf_path", "PDF"),
        ("supporting", "supporting_path", "補足資料"),
    ):
        keeper_value = keeper.get(field)
        duplicate_value = duplicate.get(field)
        if keeper_value and duplicate_value and keeper_value != duplicate_value:
            conflicts.append(label)

    if conflicts:
        return transferred_fields, conflicts

    for kind, field, label in (
        ("pdf", "pdf_path", "PDF"),
        ("supporting", "supporting_path", "補足資料"),
    ):
        keeper_value = keeper.get(field)
        duplicate_value = duplicate.get(field)
        if not keeper_value and duplicate_value:
            (
                supabase.table("attachments")
                .update({"item_id": target_item_id})
                .eq("item_id", source_item_id)
                .eq("user_id", user_id)
                .eq("kind", kind)
                .execute()
            )
            transferred_fields[field] = duplicate_value

    return transferred_fields, conflicts


def build_paper_merge_update(keeper, duplicate):
    update_fields = {}
    conflicts = []

    for field in ("title", "authors", "journal", "year", "doi", "url", "status"):
        if not keeper.get(field) and duplicate.get(field):
            update_fields[field] = duplicate[field]

    for field, label in (("pdf_path", "PDF"), ("supporting_path", "補足資料")):
        keeper_value = keeper.get(field)
        duplicate_value = duplicate.get(field)
        if keeper_value and duplicate_value and keeper_value != duplicate_value:
            conflicts.append(label)
        elif not keeper_value and duplicate_value:
            update_fields[field] = duplicate_value

    keeper_notes = (keeper.get("notes") or "").strip()
    duplicate_notes = (duplicate.get("notes") or "").strip()
    if duplicate_notes and duplicate_notes not in keeper_notes:
        if keeper_notes:
            update_fields["notes"] = f"{keeper_notes}\n\n--- 統合元メモ ---\n{duplicate_notes}"
        else:
            update_fields["notes"] = duplicate_notes

    return update_fields, conflicts


def build_item_merge_update(keeper, duplicate):
    update_fields = {}

    field_map = {
        "title": "title",
        "journal": "publication_title",
        "year": "year",
        "doi": "doi",
        "url": "url",
        "volume": "volume",
        "issue": "issue",
        "pages": "pages",
        "publisher": "publisher",
        "item_type": "item_type",
        "notes": "abstract_note",
    }

    for view_field, item_field in field_map.items():
        if view_field == "notes":
            continue
        if not keeper.get(view_field) and duplicate.get(view_field):
            update_fields[item_field] = duplicate[view_field]

    keeper_notes = (keeper.get("notes") or "").strip()
    duplicate_notes = (duplicate.get("notes") or "").strip()
    if duplicate_notes and duplicate_notes not in keeper_notes:
        if keeper_notes:
            update_fields["abstract_note"] = (
                f"{keeper_notes}\n\n--- 統合元メモ ---\n{duplicate_notes}"
            )
        else:
            update_fields["abstract_note"] = duplicate_notes

    return update_fields


def item_update_to_view_fields(update_fields):
    field_map = {
        "publication_title": "journal",
        "abstract_note": "notes",
    }
    return {
        field_map.get(field, field): value
        for field, value in update_fields.items()
    }


def is_item_backed_paper(row):
    return bool(row.get("item_id"))


def get_paper_reference_ids(row):
    values = [row.get("id"), row.get("item_id")]
    return [value for value in values if value is not None]


def merge_duplicate_paper(supabase, user_id, keeper, duplicate):
    if is_item_backed_paper(keeper) or is_item_backed_paper(duplicate):
        if not is_item_backed_paper(keeper) or not is_item_backed_paper(duplicate):
            raise ValueError("items由来とpapers由来の文献は自動統合できません。")
        return merge_duplicate_item(supabase, user_id, keeper, duplicate)

    update_fields, conflicts = build_paper_merge_update(keeper, duplicate)
    if conflicts:
        raise ValueError(
            " / ".join(conflicts)
            + " が両方の文献にあります。先に残す添付を手動で決めてください。"
        )

    if update_fields:
        (
            supabase.table("papers")
            .update(update_fields)
            .eq("id", keeper["id"])
            .eq("user_id", user_id)
            .execute()
        )

    copy_paper_tags(supabase, duplicate["id"], keeper["id"])
    copy_paper_collections(supabase, duplicate["id"], keeper["id"])
    citation_updates = replace_paper_id_in_document_citations(
        supabase,
        user_id,
        duplicate["id"],
        keeper["id"],
    )

    supabase.table("paper_tags").delete().eq("paper_id", duplicate["id"]).execute()
    supabase.table("collection_papers").delete().eq("paper_id", duplicate["id"]).execute()
    (
        supabase.table("papers")
        .delete()
        .eq("id", duplicate["id"])
        .eq("user_id", user_id)
        .execute()
    )
    remaining = (
        supabase.table("papers")
        .select("id")
        .eq("id", duplicate["id"])
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if remaining.data:
        raise RuntimeError("統合元の文献が削除されませんでした。権限またはRLSを確認してください。")

    return {"citation_updates": citation_updates, "updated_fields": update_fields}


def merge_duplicate_item(supabase, user_id, keeper, duplicate):
    ensure_user_owns_item(supabase, user_id, keeper["item_id"])
    ensure_user_owns_item(supabase, user_id, duplicate["item_id"])

    update_fields = build_item_merge_update(keeper, duplicate)
    transferred_fields, attachment_conflicts = transfer_item_attachments(
        supabase,
        user_id,
        duplicate["item_id"],
        keeper["item_id"],
        keeper,
        duplicate,
    )
    if attachment_conflicts:
        raise ValueError(
            " / ".join(attachment_conflicts)
            + " が両方の文献にあります。先に残す添付を手動で決めてください。"
        )

    if update_fields:
        (
            supabase.table("items")
            .update(update_fields)
            .eq("id", keeper["item_id"])
            .eq("user_id", user_id)
            .execute()
        )

    copy_item_tags(supabase, duplicate["item_id"], keeper["item_id"])
    copy_item_collections(supabase, duplicate["item_id"], keeper["item_id"])
    citation_updates = replace_paper_id_in_document_citations(
        supabase,
        user_id,
        get_paper_reference_ids(duplicate),
        keeper["id"],
    )

    supabase.table("item_tags").delete().eq("item_id", duplicate["item_id"]).execute()
    supabase.table("collection_items").delete().eq("item_id", duplicate["item_id"]).execute()
    (
        supabase.table("items")
        .delete()
        .eq("id", duplicate["item_id"])
        .eq("user_id", user_id)
        .execute()
    )
    remaining = (
        supabase.table("items")
        .select("id")
        .eq("id", duplicate["item_id"])
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if remaining.data:
        raise RuntimeError("統合元の文献が削除されませんでした。権限またはRLSを確認してください。")

    updated_fields = item_update_to_view_fields(update_fields)
    updated_fields.update(transferred_fields)
    return {"citation_updates": citation_updates, "updated_fields": updated_fields}


def sort_papers_dataframe(df, sort_option, added_oldest_first=False):
    if df.empty:
        return df

    sorted_df = df.copy()

    if sort_option == "追加順" and "display_order" in sorted_df.columns:
        sorted_df = sorted_df.sort_values(
            by="display_order",
            ascending=added_oldest_first,
        )
    elif sort_option == "年（新しい順）":
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
    authors = normalize_author_text(row.get("authors", ""))
    year = row.get("year", "")
    title = row.get("title", "")
    journal = row.get("journal", "")
    doi = normalize_doi(row.get("doi", ""))
    volume = row.get("volume", "")
    issue = row.get("issue", "")
    pages = row.get("pages", "")
    publication = journal
    if volume:
        publication += f", {volume}"
        if issue:
            publication += f"({issue})"
    if pages:
        publication += f", {pages}"

    if style == "APA":
        citation = f"{authors} ({year}). {title}. {publication}."
        if doi:
            citation += f" https://doi.org/{doi}"
    elif style == "Vancouver":
        citation = f"{authors}. {title}. {publication}. {year}."
        if doi:
            citation += f" doi:{doi}"
    elif style == "Nature":
        citation = f"{authors} {title}. {publication} ({year})."
        if doi:
            citation += f" https://doi.org/{doi}"
    else:
        citation = f"{authors} ({year}). {title}. {publication}."

    return citation


def make_bibtex_key(row):
    authors = row.get("authors") or "unknown"
    first_author = re.split(r",| and ", authors, maxsplit=1)[0].strip()
    author_key = re.sub(r"[^A-Za-z0-9]+", "", first_author) or "unknown"
    year_key = re.sub(r"[^0-9]+", "", str(row.get("year") or "")) or "nodate"
    title_words = re.findall(r"[A-Za-z0-9]+", row.get("title") or "")
    title_key = title_words[0] if title_words else "untitled"
    return f"{author_key}{year_key}{title_key}"


def normalize_bibtex_authors(authors):
    names = [name.strip() for name in re.split(r"\s+and\s+|;", authors or "") if name.strip()]
    if len(names) == 1:
        names = [name.strip() for name in (authors or "").split(",") if name.strip()]
    return names


def normalize_author_text(authors):
    return ", ".join(normalize_bibtex_authors(authors))


def normalize_bibtex_doi(doi):
    return normalize_doi(doi)


def escape_bibtex_value(value):
    text = str(value or "")
    return text.replace("\\", "\\textbackslash{}").replace("{", "\\{").replace("}", "\\}")


def make_bibtex_entry(row):
    entry_type = "article" if row.get("journal") else "misc"
    fields = [
        ("title", row.get("title")),
        ("author", " and ".join(normalize_bibtex_authors(row.get("authors")))),
        ("journal", row.get("journal")),
        ("year", row.get("year")),
        ("volume", row.get("volume")),
        ("number", row.get("issue")),
        ("pages", row.get("pages")),
        ("publisher", row.get("publisher")),
        ("doi", normalize_bibtex_doi(row.get("doi"))),
        ("url", row.get("url")),
    ]
    lines = [f"@{entry_type}{{{make_bibtex_key(row)},"]
    for field, value in fields:
        if value not in (None, ""):
            lines.append(f"  {field} = {{{escape_bibtex_value(value)}}},")
    if len(lines) > 1:
        lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines)


def make_ris_entry(row):
    ris_type = "JOUR" if row.get("journal") else "GEN"
    lines = [f"TY  - {ris_type}"]
    for author in normalize_bibtex_authors(row.get("authors")):
        lines.append(f"AU  - {author}")
    field_map = [
        ("TI", row.get("title")),
        ("T2", row.get("journal")),
        ("PY", row.get("year")),
        ("VL", row.get("volume")),
        ("IS", row.get("issue")),
        ("SP", row.get("pages")),
        ("PB", row.get("publisher")),
        ("DO", normalize_bibtex_doi(row.get("doi"))),
        ("UR", row.get("url")),
    ]
    for tag, value in field_map:
        if value not in (None, ""):
            lines.append(f"{tag}  - {value}")
    lines.append("ER  -")
    return "\n".join(lines)


def export_to_bibtex_text(papers):
    return "\n\n".join(make_bibtex_entry(paper) for paper in papers or [])


def export_to_ris_text(papers):
    return "\n\n".join(make_ris_entry(paper) for paper in papers or [])


def parse_bibtex_entries(text):
    entries = []
    for match in re.finditer(r"@\w+\s*\{\s*[^,]+,(.*?)(?=\n\s*@|\Z)", text or "", re.DOTALL):
        body = match.group(1)
        fields = {}
        for field_match in re.finditer(
            r"(\w+)\s*=\s*(?:\{(.*?)\}|\"(.*?)\")\s*,?",
            body,
            re.DOTALL,
        ):
            name = field_match.group(1).lower()
            value = field_match.group(2) if field_match.group(2) is not None else field_match.group(3)
            fields[name] = re.sub(r"\s+", " ", value or "").strip()
        if fields:
            entries.append(
                {
                    "title": fields.get("title", ""),
                    "authors": ", ".join(normalize_bibtex_authors(fields.get("author", ""))),
                    "journal": fields.get("journal") or fields.get("booktitle", ""),
                    "year": fields.get("year") or 0,
                    "doi": normalize_bibtex_doi(fields.get("doi", "")),
                    "url": fields.get("url", ""),
                    "volume": fields.get("volume", ""),
                    "issue": fields.get("number", ""),
                    "pages": fields.get("pages", ""),
                    "publisher": fields.get("publisher", ""),
                }
            )
    return entries


def parse_ris_entries(text):
    entries = []
    current = {}
    authors = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        line_match = re.match(r"^([A-Z0-9]{2})\s+-\s*(.*)$", line, flags=re.IGNORECASE)
        if not line_match:
            continue
        tag = line_match.group(1).strip().upper()
        value = line_match.group(2).strip()
        if tag == "TY":
            current = {}
            authors = []
        elif tag == "AU":
            authors.append(value)
        elif tag in {"TI", "T1"}:
            current["title"] = value
        elif tag in {"T2", "JO", "JF"}:
            current["journal"] = value
        elif tag in {"PY", "Y1"}:
            year_match = re.search(r"\d{4}", value)
            current["year"] = year_match.group(0) if year_match else value
        elif tag == "VL":
            current["volume"] = value
        elif tag == "IS":
            current["issue"] = value
        elif tag in {"SP", "EP"}:
            current["pages"] = (
                f"{current.get('pages', '')}-{value}".strip("-")
                if tag == "EP"
                else value
            )
        elif tag == "PB":
            current["publisher"] = value
        elif tag == "DO":
            current["doi"] = normalize_bibtex_doi(value)
        elif tag == "UR":
            current["url"] = value
        elif tag == "ER":
            current["authors"] = ", ".join(authors)
            entries.append(
                {
                    "title": current.get("title", ""),
                    "authors": current.get("authors", ""),
                    "journal": current.get("journal", ""),
                    "year": current.get("year") or 0,
                    "doi": current.get("doi", ""),
                    "url": current.get("url", ""),
                    "volume": current.get("volume", ""),
                    "issue": current.get("issue", ""),
                    "pages": current.get("pages", ""),
                    "publisher": current.get("publisher", ""),
                }
            )
            current = {}
            authors = []
    return [entry for entry in entries if entry.get("title") or entry.get("doi")]


def extract_doi_from_pdf_bytes(pdf_bytes):
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text_parts = []
        for page in reader.pages[:3]:
            text_parts.append(page.extract_text() or "")
        return extract_doi_from_text(" ".join(text_parts))
    except Exception:
        return ""


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


def save_tags_for_item(supabase, user_id, item_id, tags_text):
    if not item_id:
        return
    for tag_name in normalize_tag_input(tags_text):
        tag_id = get_or_create_tag_id(supabase, user_id, tag_name)
        supabase.table("item_tags").upsert(
            {"item_id": item_id, "tag_id": str(tag_id)}
        ).execute()


def replace_tags_for_paper(supabase, user_id, paper_id, item_id, tags_text):
    legacy_paper_id = paper_id if paper_id and not normalize_uuid_text(paper_id) else None
    if legacy_paper_id:
        supabase.table("paper_tags").delete().eq("paper_id", legacy_paper_id).execute()

    if item_id:
        try:
            supabase.table("item_tags").delete().eq("item_id", item_id).execute()
        except APIError as error:
            if not is_missing_relation_error(error):
                raise
        save_tags_for_item(supabase, user_id, item_id, tags_text)
    elif paper_id:
        save_tags_for_paper(supabase, user_id, paper_id, tags_text)


def get_tag_map_for_papers(supabase, papers_or_ids):
    if not papers_or_ids:
        return {}

    if isinstance(papers_or_ids[0], dict):
        papers = papers_or_ids
        paper_ids = [
            normalized_id
            for normalized_id in (normalize_optional_id(row.get("id")) for row in papers)
            if normalized_id
        ]
        item_ids = [
            normalized_id
            for normalized_id in (
                normalize_optional_id(row.get("item_id")) for row in papers
            )
            if normalized_id
        ]
    else:
        paper_ids = [
            normalized_id
            for normalized_id in (normalize_optional_id(paper_id) for paper_id in papers_or_ids)
            if normalized_id
        ]
        item_ids = []

    paper_tag_result = None
    if paper_ids:
        try:
            paper_tag_result = (
                supabase.table("paper_tags")
                .select("paper_id, tag_id")
                .in_("paper_id", paper_ids)
                .execute()
            )
        except APIError:
            return {}
    item_tag_result = None
    if item_ids:
        try:
            item_tag_result = (
                supabase.table("item_tags")
                .select("item_id, tag_id")
                .in_("item_id", item_ids)
                .execute()
            )
        except APIError:
            return {}

    paper_tags = paper_tag_result.data if paper_tag_result else []
    item_tags = item_tag_result.data if item_tag_result else []
    if not paper_tags and not item_tags:
        return {}

    tag_ids = sorted(
        {
            tag_id
            for tag_id in (
                normalize_uuid_text(row.get("tag_id"))
                for row in paper_tags + item_tags
            )
            if tag_id
        }
    )
    if not tag_ids:
        return {}

    try:
        tag_result = supabase.table("tags").select("id, name").in_("id", tag_ids).execute()
    except APIError:
        return {}
    tag_name_map = {str(row["id"]): row["name"] for row in (tag_result.data or [])}

    tag_map = {paper_id: [] for paper_id in paper_ids}
    for row in paper_tags:
        tag_name = tag_name_map.get(str(row["tag_id"]))
        if tag_name:
            tag_map.setdefault(str(row["paper_id"]), []).append(tag_name)
    for row in item_tags:
        tag_name = tag_name_map.get(str(row["tag_id"]))
        if tag_name:
            tag_map.setdefault(str(row["item_id"]), []).append(tag_name)

    return tag_map


def update_item_display_order(supabase, user_id, item_id, display_order):
    item_result = (
        supabase.table("items")
        .select("extra")
        .eq("id", item_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    extra = (item_result.data or [{}])[0].get("extra") or {}
    extra["legacy_display_order"] = str(display_order)
    (
        supabase.table("items")
        .update({"extra": extra})
        .eq("id", item_id)
        .eq("user_id", user_id)
        .execute()
    )


def move_paper(supabase, user_id, paper_id, display_order, direction, item_id=None):
    if item_id:
        result = fetch_user_papers(
            supabase,
            user_id,
            columns="id, item_id, display_order",
        )
        papers = [
            row
            for row in (result.data or [])
            if row.get("display_order") is not None
        ]
        papers.sort(key=lambda row: int(row["display_order"]))
        index = next(
            (
                position
                for position, row in enumerate(papers)
                if str(row.get("item_id")) == str(item_id)
            ),
            None,
        )
        if index is None:
            return
        neighbor_index = index - 1 if direction == "up" else index + 1
        if neighbor_index < 0 or neighbor_index >= len(papers):
            return

        current = papers[index]
        neighbor = papers[neighbor_index]
        update_item_display_order(
            supabase,
            user_id,
            current["item_id"],
            neighbor["display_order"],
        )
        update_item_display_order(
            supabase,
            user_id,
            neighbor["item_id"],
            current["display_order"],
        )
        return

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


def update_paper_details(
    supabase,
    user_id,
    paper_id,
    status,
    notes,
    url=None,
    item_id=None,
    doi=None,
    volume=None,
    issue=None,
    pages=None,
    publisher=None,
):
    doi_provided = doi is not None
    url_provided = url is not None
    status = normalize_text_db_value(status)
    notes = normalize_text_db_value(notes)
    doi = normalize_optional_db_value(doi) if doi_provided else None
    url = normalize_optional_db_value(url) if url_provided else None

    if item_id:
        item_result = (
            supabase.table("items")
            .select("extra")
            .eq("id", item_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        extra = (item_result.data or [{}])[0].get("extra") or {}
        extra["legacy_status"] = status
        fields = {"abstract_note": notes, "extra": extra}
        if doi_provided:
            fields["doi"] = doi
        if url_provided:
            fields["url"] = url
        metadata_fields = {
            "volume": volume,
            "issue": issue,
            "pages": pages,
            "publisher": publisher,
        }
        for field, value in metadata_fields.items():
            if value is not None:
                fields[field] = normalize_optional_db_value(value)
        try:
            (
                supabase.table("items")
                .update(fields)
                .eq("id", item_id)
                .eq("user_id", user_id)
                .execute()
            )
        except APIError as error:
            if not is_missing_metadata_column_error(error):
                raise
            for field in ITEM_METADATA_COLUMNS:
                fields.pop(field, None)
            (
                supabase.table("items")
                .update(fields)
                .eq("id", item_id)
                .eq("user_id", user_id)
                .execute()
            )
        return

    fields = {"status": status, "notes": notes}
    if doi_provided:
        fields["doi"] = doi
    if url_provided:
        fields["url"] = url

    (
        supabase.table("papers")
        .update(fields)
        .eq("id", paper_id)
        .eq("user_id", user_id)
        .execute()
    )


def replace_item_attachment(supabase, user_id, item_id, kind, storage_path):
    if not item_id or storage_path is None:
        return

    ensure_user_owns_item(supabase, user_id, item_id)

    if not is_storage_path(storage_path):
        (
            supabase.table("attachments")
            .delete()
            .eq("item_id", item_id)
            .eq("user_id", user_id)
            .eq("kind", kind)
            .execute()
        )
        return

    existing = (
        supabase.table("attachments")
        .select("id")
        .eq("item_id", item_id)
        .eq("user_id", user_id)
        .eq("kind", kind)
        .limit(1)
        .execute()
    )
    if existing.data:
        (
            supabase.table("attachments")
            .update({"storage_path": storage_path})
            .eq("id", existing.data[0]["id"])
            .eq("user_id", user_id)
            .execute()
        )
    else:
        (
            supabase.table("attachments")
            .insert(
                {
                    "item_id": item_id,
                    "user_id": user_id,
                    "kind": kind,
                    "storage_path": storage_path,
                }
            )
            .execute()
        )


def update_paper_files(
    supabase,
    user_id,
    paper_id,
    pdf_path=None,
    supporting_path=None,
    item_id=None,
):
    if item_id:
        if pdf_path is not None:
            replace_item_attachment(supabase, user_id, item_id, "pdf", pdf_path)
        if supporting_path is not None:
            replace_item_attachment(
                supabase,
                user_id,
                item_id,
                "supporting",
                supporting_path,
            )
        return

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


def delete_paper(supabase, user_id, row, delete_files=True):
    if is_item_backed_paper(row):
        return delete_item_backed_paper(supabase, user_id, row, delete_files=delete_files)

    storage_errors = []
    pdf_path = row.get("pdf_path")
    supporting_path = row.get("supporting_path")

    supabase.table("paper_tags").delete().eq("paper_id", row["id"]).execute()
    supabase.table("collection_papers").delete().eq("paper_id", row["id"]).execute()
    (
        supabase.table("papers")
        .delete()
        .eq("id", row["id"])
        .eq("user_id", user_id)
        .execute()
    )
    remaining = (
        supabase.table("papers")
        .select("id")
        .eq("id", row["id"])
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if remaining.data:
        raise RuntimeError("文献が削除されませんでした。権限またはRLSを確認してください。")

    if delete_files:
        for label, storage_path in (("PDF", pdf_path), ("補足資料", supporting_path)):
            if not is_storage_path(storage_path):
                continue
            try:
                delete_pdf_from_storage(supabase, storage_path)
            except Exception as error:
                storage_errors.append(f"{label}: {error}")

    return {"storage_errors": storage_errors}


def delete_item_backed_paper(supabase, user_id, row, delete_files=True):
    storage_errors = []
    ensure_user_owns_item(supabase, user_id, row["item_id"])
    storage_paths = fetch_item_storage_paths(supabase, user_id, row["item_id"])

    supabase.table("item_tags").delete().eq("item_id", row["item_id"]).execute()
    supabase.table("collection_items").delete().eq("item_id", row["item_id"]).execute()
    (
        supabase.table("items")
        .delete()
        .eq("id", row["item_id"])
        .eq("user_id", user_id)
        .execute()
    )
    remaining = (
        supabase.table("items")
        .select("id")
        .eq("id", row["item_id"])
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if remaining.data:
        raise RuntimeError("文献が削除されませんでした。権限またはRLSを確認してください。")

    if delete_files:
        for storage_path in storage_paths:
            try:
                delete_pdf_from_storage(supabase, storage_path)
            except Exception as error:
                storage_errors.append(f"{storage_path}: {error}")

    return {"storage_errors": storage_errors}
