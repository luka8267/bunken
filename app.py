import ipaddress
import logging
import re
import socket
import uuid
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from supabase import Client

from auth_utils import (
    build_supabase_client,
    get_current_user_id,
    login_user,
    normalize_email,
    normalize_username,
    register_user,
    request_password_reset,
    set_authenticated_user,
    sign_out_user,
    store_auth_session,
    update_password,
    verify_password_reset_token,
)
from paper_utils import (
    READING_STATUSES,
    SORT_OPTIONS,
    build_document_citation_export_rows,
    create_collection,
    create_user_paper,
    create_pdf_signed_url,
    delete_collection,
    delete_paper,
    delete_pdf_from_storage,
    delete_user_document,
    export_to_bibtex_text,
    export_to_ris_text,
    export_to_word_bytes,
    extract_doi_from_pdf_bytes,
    extract_title_from_pdf_bytes,
    fetch_collection_counts,
    fetch_document_citations,
    fetch_paper_collection_ids,
    fetch_papers_for_collection,
    find_existing_user_paper_by_doi,
    fetch_user_papers,
    fetch_user_papers_by_ids,
    fetch_user_collections,
    fetch_user_documents,
    fetch_duplicate_merge_backups,
    filter_document_citations,
    filter_papers,
    find_duplicate_paper_groups,
    get_document_citation_usage_map,
    get_next_display_order,
    get_tag_map_for_papers,
    make_bibtex_entry,
    make_ris_entry,
    make_word_citation,
    merge_duplicate_paper,
    move_paper,
    normalize_doi,
    normalize_title_for_match,
    paper_has_document_citation_refs,
    parse_bibtex_entries,
    parse_ris_entries,
    replace_tags_for_paper,
    restore_keeper_from_merge_backup,
    save_tags_for_paper,
    save_tags_for_item,
    search_user_papers,
    set_paper_collections,
    sort_papers_dataframe,
    update_collection,
    update_paper_details,
    update_paper_files,
    upload_pdf_to_storage,
    upload_supporting_file_to_storage,
)
import paper_utils as paper_utils_module

DOI_FORM_FIELDS = (
    "title",
    "authors",
    "journal",
    "year",
    "volume",
    "issue",
    "pages",
    "publisher",
)
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)
URL_FORM_FIELDS = (*DOI_FORM_FIELDS, "doi")
SUPPORTING_FILE_TYPES = [
    "pdf",
    "zip",
    "docx",
    "xlsx",
    "xls",
    "csv",
    "txt",
    "png",
    "jpg",
    "jpeg",
]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
MAX_METADATA_REDIRECTS = 3
METADATA_FETCH_BYTES = 300000
READING_NOTE_MARKER = "--- 読書メモ ---"
CITATION_NOTE_MARKER = "--- 引用予定メモ ---"
IMPORT_REQUIRED_FIELDS = (
    ("title", "タイトル"),
    ("authors", "著者"),
    ("year", "年"),
    ("doi", "DOI"),
)

supabase: Client = build_supabase_client(SUPABASE_URL, SUPABASE_KEY)
logger = logging.getLogger(__name__)


def normalize_author_list_compat(authors):
    helper = getattr(paper_utils_module, "normalize_author_list", None)
    if helper:
        return helper(authors)
    names = []
    for raw_name in re.split(r"\s+and\s+|;|\|", authors or ""):
        text = re.sub(r"\s+", " ", raw_name or "").strip()
        if not text:
            continue
        if "," in text:
            family, given = [part.strip() for part in text.split(",", maxsplit=1)]
            names.append(f"{family}, {given}" if given else family)
        else:
            parts = text.split()
            names.append(f"{parts[-1]}, {' '.join(parts[:-1])}" if len(parts) >= 2 else text)
    return ", ".join(names)


def normalize_journal_title_compat(journal):
    helper = getattr(paper_utils_module, "normalize_journal_title", None)
    if helper:
        return helper(journal)
    return re.sub(r"\s+", " ", journal or "").strip()


def update_document_citation_compat(
    supabase_client,
    user_id,
    citation_id,
    rendered_text=None,
    context_text=None,
    sort_order=None,
):
    helper = getattr(paper_utils_module, "update_document_citation", None)
    if helper:
        return helper(
            supabase_client,
            user_id,
            citation_id,
            rendered_text=rendered_text,
            context_text=context_text,
            sort_order=sort_order,
        )
    fields = {}
    if rendered_text is not None:
        fields["rendered_text"] = rendered_text
    if context_text is not None:
        fields["context_text"] = context_text
    if sort_order is not None:
        fields["sort_order"] = int(sort_order)
    if not fields:
        return None
    return supabase_client.table("document_citations").update(fields).eq("id", citation_id).execute()


def delete_document_citation_compat(supabase_client, citation_id):
    helper = getattr(paper_utils_module, "delete_document_citation", None)
    if helper:
        return helper(supabase_client, citation_id)
    return supabase_client.table("document_citations").delete().eq("id", citation_id).execute()


def restore_duplicate_from_merge_backup_compat(supabase_client, user_id, backup):
    helper = getattr(paper_utils_module, "restore_duplicate_from_merge_backup", None)
    if helper:
        return helper(supabase_client, user_id, backup)
    snapshot = backup.get("duplicate_snapshot") or {}
    if not snapshot:
        raise ValueError("復元できる統合元スナップショットがありません。")
    created = create_user_paper(
        supabase_client,
        user_id,
        snapshot.get("title") or "",
        snapshot.get("authors") or "",
        snapshot.get("journal") or "",
        snapshot.get("year") or 0,
        normalize_doi(snapshot.get("doi")) or None,
        snapshot.get("url") or None,
        snapshot.get("pdf_path") or None,
        snapshot.get("supporting_path") or None,
        snapshot.get("status") or "未読",
        snapshot.get("notes") or "",
        get_next_display_order(supabase_client, user_id),
        snapshot.get("volume") or "",
        snapshot.get("issue") or "",
        snapshot.get("pages") or "",
        snapshot.get("publisher") or "",
        snapshot.get("item_type") or "journalArticle",
    )
    return {
        "restored_table": "items" if created.get("item_id") else "papers",
        "restored_id": created["id"],
    }


def promote_url_fragment_to_query_params():
    components.html(
        """
        <script>
        const hash = window.parent.location.hash;
        if (hash && hash.includes("access_token")) {
            const params = new URLSearchParams(hash.substring(1));
            const url = new URL(window.parent.location.href);
            params.forEach((value, key) => url.searchParams.set(key, value));
            url.hash = "";
            window.parent.location.replace(url.toString());
        }
        </script>
        """,
        height=0,
    )


def get_query_param(name):
    value = st.query_params.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def get_password_reset_redirect_url():
    return st.secrets.get("PASSWORD_RESET_REDIRECT_URL")


def show_password_reset_request_form():
    st.title("パスワード再設定")
    st.write("登録済みのメールアドレスに、パスワード再設定リンクを送信します。")

    with st.form("password_reset_request_form"):
        email = st.text_input("メールアドレス")
        submitted = st.form_submit_button("再設定メールを送信")

    if submitted:
        normalized_email = normalize_email(email)
        if not normalized_email:
            st.error("メールアドレスを入力してください。")
            return

        try:
            request_password_reset(
                supabase,
                normalized_email,
                redirect_to=get_password_reset_redirect_url(),
            )
            st.success("再設定メールを送信しました。メール内のリンクから新しいパスワードを設定してください。")
        except Exception as error:
            logger.exception("Failed to request password reset")
            st.error(f"再設定メールの送信に失敗しました: {error}")


def show_password_update_form():
    st.title("新しいパスワード")

    token_hash = get_query_param("token_hash")
    reset_type = get_query_param("type")
    access_token = get_query_param("access_token")
    refresh_token = get_query_param("refresh_token")

    if token_hash and reset_type == "recovery" and not st.session_state.get("password_reset_verified"):
        try:
            response = verify_password_reset_token(supabase, token_hash)
            if getattr(response, "session", None):
                store_auth_session(response.session)
            st.session_state["password_reset_verified"] = True
        except Exception as error:
            logger.exception("Failed to verify password reset token")
            st.error(f"再設定リンクを確認できませんでした: {error}")
            return

    if access_token and refresh_token and not st.session_state.get("password_reset_verified"):
        try:
            response = supabase.auth.set_session(access_token, refresh_token)
            if getattr(response, "session", None):
                store_auth_session(response.session)
            st.session_state["password_reset_verified"] = True
        except Exception as error:
            logger.exception("Failed to restore password reset session")
            st.error(f"再設定セッションを確認できませんでした: {error}")
            return

    with st.form("password_update_form"):
        password = st.text_input("新しいパスワード", type="password")
        password_confirm = st.text_input("新しいパスワード（確認）", type="password")
        submitted = st.form_submit_button("パスワードを更新")

    if submitted:
        if not password or len(password) < 6:
            st.error("パスワードは6文字以上で入力してください。")
            return
        if password != password_confirm:
            st.error("確認用パスワードが一致しません。")
            return

        try:
            update_password(supabase, password)
            st.session_state.pop("password_reset_verified", None)
            st.query_params.clear()
            sign_out_user(supabase)
            st.success("パスワードを更新しました。新しいパスワードでログインしてください。")
        except Exception as error:
            logger.exception("Failed to update password")
            st.error(f"パスワード更新に失敗しました: {error}")


class MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}
        self.in_title = False
        self.title_parts = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = {key.lower(): value for key, value in attrs if value is not None}
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() != "meta":
            return

        key = (
            attrs_dict.get("name")
            or attrs_dict.get("property")
            or attrs_dict.get("itemprop")
        )
        content = attrs_dict.get("content")
        if key and content:
            self.meta.setdefault(key.lower(), []).append(content.strip())

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data.strip())

    @property
    def page_title(self):
        return " ".join(part for part in self.title_parts if part).strip()


def normalize_url(url):
    if not isinstance(url, str):
        return ""

    normalized_url = url.strip()
    if normalized_url and not re.match(r"^https?://", normalized_url, re.IGNORECASE):
        normalized_url = f"https://{normalized_url}"
    return normalized_url


def get_paper_tag_list(tag_map, paper):
    tags = tag_map.get(str(paper.get("id")), [])
    item_id = clean_optional_id(paper.get("item_id"))
    if item_id:
        tags = tags + tag_map.get(str(item_id), [])
    return list(dict.fromkeys(tags))


def get_paper_usage_entries(citation_usage_map, paper):
    if not citation_usage_map:
        return []
    entries = []
    seen = set()
    for reference_id in (paper.get("id"), clean_optional_id(paper.get("item_id"))):
        if reference_id is None:
            continue
        for entry in citation_usage_map.get(str(reference_id), []):
            key = (
                entry.get("document_title"),
                entry.get("citation_text"),
                entry.get("context_text"),
                entry.get("reference_number"),
                entry.get("locator"),
            )
            if key in seen:
                continue
            seen.add(key)
            entries.append(entry)
    return entries


def get_citation_usage_map_for_display(user_id, papers):
    try:
        return get_document_citation_usage_map(supabase, user_id, papers)
    except Exception:
        logger.exception("Failed to fetch document citation usage")
        st.warning("Word引用情報の取得に失敗しました。文献一覧は表示します。")
        return {}


@st.cache_data(ttl=45, show_spinner=False)
def fetch_list_records_cached(user_id):
    return fetch_user_papers(supabase, user_id).data or []


@st.cache_data(ttl=120, show_spinner=False)
def fetch_collections_cached(user_id):
    return fetch_user_collections(supabase, user_id).data or []


@st.cache_data(ttl=45, show_spinner=False)
def fetch_collection_papers_cached(user_id, collection_id):
    return fetch_papers_for_collection(
        supabase,
        user_id,
        collection_id,
        columns="*",
    )


@st.cache_data(ttl=45, show_spinner=False)
def fetch_collection_counts_cached(collection_ids):
    return fetch_collection_counts(supabase, list(collection_ids))


@st.cache_data(ttl=45, show_spinner=False)
def get_citation_usage_map_for_refs_cached(user_id, reference_ids):
    reference_texts = {str(reference_id) for reference_id in reference_ids if reference_id}
    usage_map = {reference_id: [] for reference_id in reference_texts}
    if not reference_texts:
        return usage_map

    documents_result = fetch_user_documents(supabase, user_id)
    for document in documents_result.data or []:
        citations_result = fetch_document_citations(supabase, document["id"])
        for citation in citations_result.data or []:
            for item in citation.get("citation_items") or []:
                if not isinstance(item, dict):
                    continue
                paper_id = str(item.get("paperId") or "")
                if paper_id not in reference_texts:
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


def clear_library_caches():
    fetch_list_records_cached.clear()
    fetch_collections_cached.clear()
    fetch_collection_papers_cached.clear()
    fetch_collection_counts_cached.clear()
    get_citation_usage_map_for_refs_cached.clear()


def set_list_filters(collection_label=None, tag_label=None, smart_filter=None):
    if collection_label is not None:
        st.session_state["list_collection_filter"] = collection_label
    if tag_label is not None:
        st.session_state["list_tag_filter"] = tag_label
    if smart_filter is not None:
        st.session_state["list_smart_filter"] = smart_filter


def clean_optional_id(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    text = str(value).strip()
    return text or None


def split_structured_notes(notes):
    text = notes or ""
    reading = ""
    citation = ""
    base = text
    if READING_NOTE_MARKER in base:
        base, reading_part = base.split(READING_NOTE_MARKER, 1)
        if CITATION_NOTE_MARKER in reading_part:
            reading, citation = reading_part.split(CITATION_NOTE_MARKER, 1)
        else:
            reading = reading_part
    elif CITATION_NOTE_MARKER in base:
        base, citation = base.split(CITATION_NOTE_MARKER, 1)
    return {
        "base": base.strip(),
        "reading": reading.strip(),
        "citation": citation.strip(),
    }


def combine_structured_notes(base_note, reading_note="", citation_note=""):
    parts = []
    if (base_note or "").strip():
        parts.append(base_note.strip())
    if (reading_note or "").strip():
        parts.append(f"{READING_NOTE_MARKER}\n{reading_note.strip()}")
    if (citation_note or "").strip():
        parts.append(f"{CITATION_NOTE_MARKER}\n{citation_note.strip()}")
    return "\n\n".join(parts)


def get_citation_planned_note(paper):
    return split_structured_notes(paper.get("notes")).get("citation", "")


def render_paper_summary(paper, tag_map=None, show_id=False, citation_usage_map=None):
    paper_url = normalize_url(paper.get("url"))
    signed_url = create_pdf_signed_url(supabase, paper.get("pdf_path"), 3600)
    supporting_url = create_pdf_signed_url(supabase, paper.get("supporting_path"), 3600)

    ref_no = paper.get("ref_no")
    heading_prefix = f"[{ref_no}] " if ref_no else ""
    st.markdown(f"### {heading_prefix}{paper.get('title') or '無題'}")
    if show_id:
        st.caption(f"ID: {paper.get('id')}")
    if paper.get("authors"):
        st.write(f"著者: {paper.get('authors')}")
    if paper.get("journal") or paper.get("year"):
        st.write(f"雑誌: {paper.get('journal') or ''} ({paper.get('year') or '-'})")
    publication_parts = []
    if paper.get("volume"):
        issue = f"({paper.get('issue')})" if paper.get("issue") else ""
        publication_parts.append(f"{paper.get('volume')}{issue}")
    if paper.get("pages"):
        publication_parts.append(f"pp. {paper.get('pages')}")
    if paper.get("publisher"):
        publication_parts.append(paper.get("publisher"))
    if publication_parts:
        st.caption(" / ".join(publication_parts))
    missing_metadata_text = format_missing_publication_metadata(paper)
    if missing_metadata_text:
        st.caption(f"不足メタデータ: {missing_metadata_text}")
    if paper.get("doi"):
        st.write(f"DOI: {paper.get('doi')}")
    if paper.get("status"):
        st.write(f"ステータス: {paper.get('status')}")
    if paper.get("notes"):
        notes_parts = split_structured_notes(paper.get("notes"))
        if notes_parts["base"]:
            st.write("メモ:")
            st.write(notes_parts["base"])
        if notes_parts["reading"]:
            st.write("読書メモ:")
            st.write(notes_parts["reading"])
        if notes_parts["citation"]:
            st.write("引用予定メモ:")
            st.write(notes_parts["citation"])

    attachments = []
    if signed_url:
        attachments.append("PDF")
    if supporting_url:
        attachments.append("資料")
    if attachments:
        st.caption("添付: " + " / ".join(attachments))

    if tag_map:
        tags_list = get_paper_tag_list(tag_map, paper)
        if tags_list:
            st.write("タグ:", ", ".join(tags_list))

    usage_entries = get_paper_usage_entries(citation_usage_map, paper)
    if usage_entries:
        with st.expander(f"Word引用 ({len(usage_entries)}件)"):
            for entry in usage_entries:
                heading = entry.get("document_title") or "無題"
                citation_text = entry.get("citation_text")
                if citation_text:
                    heading += f" / {citation_text}"
                st.markdown(f"**{heading}**")
                if entry.get("context_text"):
                    st.write(entry["context_text"])
                details = []
                if entry.get("reference_number"):
                    details.append(f"参考文献番号: {entry['reference_number']}")
                if entry.get("locator"):
                    details.append(f"位置: {entry['locator']}")
                if entry.get("updated_at"):
                    details.append(f"更新: {entry['updated_at']}")
                if details:
                    st.caption(" / ".join(details))

    actions = st.columns(3)
    with actions[0]:
        if signed_url:
            st.link_button("📄 PDF", signed_url)
    with actions[1]:
        if supporting_url:
            st.link_button("資料", supporting_url)
    with actions[2]:
        if paper_url:
            st.link_button("Webページ", paper_url)


def build_collection_label_maps(collections):
    collection_label_by_id = {
        collection["id"]: f"{collection.get('name') or '無題'} [{collection['id'][:8]}]"
        for collection in collections
    }
    collection_id_by_label = {
        collection_label_by_id[collection["id"]]: collection["id"]
        for collection in collections
    }
    return collection_label_by_id, collection_id_by_label


def render_paper_edit_form(
    paper,
    user_id,
    collections=None,
    collection_label_by_id=None,
    collection_id_by_label=None,
    key_prefix="paper",
):
    row_dict = dict(paper)
    item_id = clean_optional_id(row_dict.get("item_id"))
    pdf_path = row_dict.get("pdf_path")
    supporting_path = row_dict.get("supporting_path")
    paper_url = normalize_url(row_dict.get("url"))
    collections = collections or []
    collection_label_by_id = collection_label_by_id or {}
    collection_id_by_label = collection_id_by_label or {}

    current_status = row_dict.get("status")
    status_index = (
        READING_STATUSES.index(current_status)
        if current_status in READING_STATUSES
        else 0
    )
    edit_status = st.selectbox(
        "読書ステータス",
        READING_STATUSES,
        index=status_index,
        key=f"{key_prefix}_status_{row_dict['id']}",
    )
    edit_notes = st.text_area(
        "抄録メモ",
        value=row_dict.get("notes") or "",
        height=180,
        key=f"{key_prefix}_notes_{row_dict['id']}",
    )
    edit_url = st.text_input(
        "URL",
        value=paper_url,
        key=f"{key_prefix}_url_{row_dict['id']}",
    )
    edit_doi = st.text_input(
        "DOI",
        value=row_dict.get("doi") or "",
        key=f"{key_prefix}_doi_{row_dict['id']}",
    )
    edit_meta_col1, edit_meta_col2 = st.columns(2)
    with edit_meta_col1:
        edit_volume = st.text_input(
            "巻",
            value=row_dict.get("volume") or "",
            key=f"{key_prefix}_volume_{row_dict['id']}",
        )
        edit_pages = st.text_input(
            "ページ",
            value=row_dict.get("pages") or "",
            key=f"{key_prefix}_pages_{row_dict['id']}",
        )
    with edit_meta_col2:
        edit_issue = st.text_input(
            "号",
            value=row_dict.get("issue") or "",
            key=f"{key_prefix}_issue_{row_dict['id']}",
        )
        edit_publisher = st.text_input(
            "出版社",
            value=row_dict.get("publisher") or "",
            key=f"{key_prefix}_publisher_{row_dict['id']}",
        )

    selected_collection_labels = []
    if collections:
        try:
            current_collection_ids = fetch_paper_collection_ids(
                supabase,
                row_dict["id"],
                item_id,
            )
        except Exception:
            logger.exception("Failed to fetch paper collections")
            current_collection_ids = []
        selected_collection_labels = st.multiselect(
            "コレクション",
            options=list(collection_id_by_label.keys()),
            default=[
                collection_label_by_id[collection_id]
                for collection_id in current_collection_ids
                if collection_id in collection_label_by_id
            ],
            key=f"{key_prefix}_collections_{row_dict['id']}",
        )

    new_pdf_file = st.file_uploader(
        "PDFを追加・差し替え",
        type=["pdf"],
        key=f"{key_prefix}_pdf_upload_{row_dict['id']}",
    )
    new_supporting_file = st.file_uploader(
        "サポーティング資料を追加・差し替え",
        type=SUPPORTING_FILE_TYPES,
        key=f"{key_prefix}_supporting_upload_{row_dict['id']}",
    )

    if st.button("💾 保存", key=f"{key_prefix}_save_{row_dict['id']}"):
        try:
            new_pdf_path = (
                upload_pdf_to_storage(supabase, new_pdf_file, user_id)
                if new_pdf_file
                else None
            )
            new_supporting_path = (
                upload_supporting_file_to_storage(
                    supabase,
                    new_supporting_file,
                    user_id,
                )
                if new_supporting_file
                else None
            )
            normalized_edit_url = normalize_url(edit_url) or None
            current_url = normalize_url(row_dict.get("url")) or None
            normalized_edit_doi = normalize_doi(edit_doi)
            current_doi = normalize_doi(row_dict.get("doi"))
            if (
                edit_status != (row_dict.get("status") or "")
                or edit_notes != (row_dict.get("notes") or "")
                or normalized_edit_url != current_url
                or normalized_edit_doi != current_doi
                or edit_volume != (row_dict.get("volume") or "")
                or edit_issue != (row_dict.get("issue") or "")
                or edit_pages != (row_dict.get("pages") or "")
                or edit_publisher != (row_dict.get("publisher") or "")
            ):
                update_paper_details(
                    supabase,
                    user_id,
                    row_dict["id"],
                    edit_status,
                    edit_notes,
                    normalized_edit_url,
                    item_id=item_id,
                    doi=normalized_edit_doi,
                    volume=edit_volume,
                    issue=edit_issue,
                    pages=edit_pages,
                    publisher=edit_publisher,
                )
            if new_pdf_path or new_supporting_path:
                update_paper_files(
                    supabase,
                    user_id,
                    row_dict["id"],
                    pdf_path=new_pdf_path,
                    supporting_path=new_supporting_path,
                    item_id=item_id,
                )
            if collections:
                set_paper_collections(
                    supabase,
                    row_dict["id"],
                    [
                        collection_id_by_label[label]
                        for label in selected_collection_labels
                    ],
                    item_id=item_id,
                )
            if new_pdf_path and isinstance(pdf_path, str) and pdf_path.strip():
                delete_pdf_from_storage(supabase, pdf_path)
            if (
                new_supporting_path
                and isinstance(supporting_path, str)
                and supporting_path.strip()
            ):
                delete_pdf_from_storage(supabase, supporting_path)
            clear_library_caches()
            st.success("更新しました")
            st.rerun()
        except Exception:
            logger.exception("Failed to update paper")
            st.error("更新に失敗しました。入力内容とログを確認してください。")


def render_paper_tag_editor(paper, user_id, tag_map, key_prefix="paper"):
    row_dict = dict(paper)
    current_tags = ", ".join(get_paper_tag_list(tag_map, row_dict))
    tags_text = st.text_input(
        "タグ（カンマ区切り）",
        value=current_tags,
        key=f"{key_prefix}_tags_{row_dict['id']}",
    )
    if st.button("タグを保存", key=f"{key_prefix}_save_tags_{row_dict['id']}"):
        try:
            replace_tags_for_paper(
                supabase,
                user_id,
                row_dict["id"],
                clean_optional_id(row_dict.get("item_id")),
                tags_text,
            )
            clear_library_caches()
            st.success("タグを更新しました")
            st.rerun()
        except Exception:
            logger.exception("Failed to update paper tags")
            st.error("タグの更新に失敗しました。入力内容とログを確認してください。")


def render_paper_pdf_preview(paper, key_prefix="paper"):
    signed_url = create_pdf_signed_url(supabase, paper.get("pdf_path"), 3600)
    if not signed_url:
        st.caption("PDFは添付されていません。")
        st.caption("編集タブからPDFを追加できます。")
        return

    page_key = f"{key_prefix}_pdf_page_{paper['id']}"
    zoom_key = f"{key_prefix}_pdf_zoom_{paper['id']}"
    height_key = f"{key_prefix}_pdf_height_{paper['id']}"
    show_key = f"{key_prefix}_pdf_embed_{paper['id']}"
    if page_key not in st.session_state:
        st.session_state[page_key] = 1
    if zoom_key not in st.session_state:
        st.session_state[zoom_key] = 110
    if height_key not in st.session_state:
        st.session_state[height_key] = 760

    control_col1, control_col2, control_col3, control_col4 = st.columns([1, 1, 1, 1.2])
    with control_col1:
        st.number_input("ページ", min_value=1, step=1, key=page_key)
    with control_col2:
        st.slider("拡大率", 60, 200, key=zoom_key)
    with control_col3:
        st.slider("高さ", 420, 1100, key=height_key)
    with control_col4:
        show_embed = st.toggle("アプリ内表示", value=True, key=show_key)

    col1, col2 = st.columns([1, 1])
    with col1:
        st.link_button("PDFを開く", signed_url, use_container_width=True)
    with col2:
        try:
            response = requests.get(signed_url, timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            logger.exception("Failed to fetch PDF for download")
            st.caption("ダウンロード準備に失敗しました。PDFを開くボタンを使ってください。")
        else:
            safe_title = re.sub(r"[^A-Za-z0-9._-]+", "-", paper.get("title") or "paper").strip("-")
            st.download_button(
                "PDFをダウンロード",
                data=response.content,
                file_name=f"{safe_title or 'paper'}.pdf",
                mime="application/pdf",
                key=f"{key_prefix}_pdf_download_{paper['id']}",
                use_container_width=True,
            )

    if show_embed:
        viewer_url = f"{signed_url}#page={st.session_state[page_key]}&zoom={st.session_state[zoom_key]}"
        components.html(
            f"""
            <iframe
                src="{viewer_url}"
                style="width: 100%; height: {st.session_state[height_key]}px; border: 1px solid #d0d7de; border-radius: 8px;"
                title="PDF viewer">
            </iframe>
            """,
            height=int(st.session_state[height_key]) + 20,
        )
        st.caption("環境によってPDFが埋め込み表示できない場合は「PDFを開く」を使ってください。")


def render_reading_workflow(paper, user_id, key_prefix="reading"):
    row_dict = dict(paper)
    notes_parts = split_structured_notes(row_dict.get("notes"))
    current_status = row_dict.get("status")
    status_index = (
        READING_STATUSES.index(current_status)
        if current_status in READING_STATUSES
        else 0
    )
    status_col1, status_col2, status_col3 = st.columns(3)
    for index, next_status in enumerate(("読書中", "読了", "引用予定")):
        with (status_col1, status_col2, status_col3)[index]:
            if st.button(
                next_status,
                key=f"{key_prefix}_quick_{row_dict['id']}_{next_status}",
                disabled=current_status == next_status,
                use_container_width=True,
            ):
                update_paper_details(
                    supabase,
                    user_id,
                    row_dict["id"],
                    next_status,
                    row_dict.get("notes") or "",
                    normalize_url(row_dict.get("url")) or None,
                    item_id=clean_optional_id(row_dict.get("item_id")),
                    doi=normalize_doi(row_dict.get("doi")),
                    volume=row_dict.get("volume") or "",
                    issue=row_dict.get("issue") or "",
                    pages=row_dict.get("pages") or "",
                    publisher=row_dict.get("publisher") or "",
                )
                clear_library_caches()
                st.success(f"ステータスを{next_status}にしました。")
                st.rerun()

    edit_status = st.selectbox(
        "読書ステータス",
        READING_STATUSES,
        index=status_index,
        key=f"{key_prefix}_status_{row_dict['id']}",
    )
    base_note = st.text_area(
        "基本メモ",
        value=notes_parts["base"],
        height=100,
        key=f"{key_prefix}_base_note_{row_dict['id']}",
    )
    reading_note = st.text_area(
        "PDF読書メモ",
        value=notes_parts["reading"],
        height=170,
        key=f"{key_prefix}_reading_note_{row_dict['id']}",
    )
    citation_note = st.text_area(
        "引用予定メモ",
        value=notes_parts["citation"],
        height=120,
        key=f"{key_prefix}_citation_note_{row_dict['id']}",
    )
    if st.button(
        "読書メモを保存",
        key=f"{key_prefix}_save_{row_dict['id']}",
        use_container_width=True,
    ):
        update_paper_details(
            supabase,
            user_id,
            row_dict["id"],
            edit_status,
            combine_structured_notes(base_note, reading_note, citation_note),
            normalize_url(row_dict.get("url")) or None,
            item_id=clean_optional_id(row_dict.get("item_id")),
            doi=normalize_doi(row_dict.get("doi")),
            volume=row_dict.get("volume") or "",
            issue=row_dict.get("issue") or "",
            pages=row_dict.get("pages") or "",
            publisher=row_dict.get("publisher") or "",
        )
        clear_library_caches()
        st.success("読書メモを保存しました。")
        st.rerun()


def format_duplicate_option_label(paper):
    memo = (paper.get("notes") or "").strip().replace("\n", " ")
    memo_part = f" / メモ: {memo[:60]}" if memo else " / メモなし"
    return (
        f"{paper.get('title') or '無題'}"
        f" ({paper.get('year') or '-'})"
        f"{memo_part}"
        f" [{paper.get('id')}]"
    )


def is_public_http_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False

    hostname = parsed.hostname.strip().lower()
    if hostname in {"localhost", "localhost.localdomain"}:
        return False

    try:
        addresses = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False

    for address in {item[4][0] for item in addresses}:
        try:
            ip_address = ipaddress.ip_address(address)
        except ValueError:
            return False

        if not ip_address.is_global:
            return False

    return True


def fetch_public_url(url):
    current_url = normalize_url(url)
    if not is_public_http_url(current_url):
        return None

    session = requests.Session()
    for _ in range(MAX_METADATA_REDIRECTS + 1):
        response = session.get(
            current_url,
            headers={"User-Agent": "bunken/1.0"},
            timeout=15,
            allow_redirects=False,
        )

        if response.is_redirect:
            next_url = response.headers.get("Location")
            if not next_url:
                return None
            current_url = urljoin(current_url, next_url)
            if not is_public_http_url(current_url):
                return None
            continue

        response.raise_for_status()
        return response

    return None


def extract_doi(text):
    match = DOI_RE.search(unquote(text or ""))
    if not match:
        return ""
    return match.group(0).rstrip(").,;]")


def crossref_message_to_metadata(data):
    title = data["title"][0] if data.get("title") else ""
    authors = ", ".join(author.get("family", "") for author in data.get("author", []))
    journal = data["container-title"][0] if data.get("container-title") else ""
    volume = str(data.get("volume") or "")
    issue = str(data.get("issue") or "")
    pages = str(data.get("page") or "")
    publisher = str(data.get("publisher") or "")

    issued = data.get("issued", {}).get("date-parts", [])
    year = issued[0][0] if issued and issued[0] else 0

    return title, authors, journal, year, volume, issue, pages, publisher


def fetch_doi(doi):
    normalized_doi = normalize_doi(doi)
    if not normalized_doi:
        return None

    try:
        response = requests.get(
            f"https://api.crossref.org/works/{normalized_doi}",
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None

    return crossref_message_to_metadata(response.json().get("message", {}))


def fetch_crossref_candidate_by_title(title, year=None):
    normalized_title = (title or "").strip()
    if not normalized_title:
        return None

    try:
        response = requests.get(
            "https://api.crossref.org/works",
            params={"query.title": normalized_title, "rows": 5},
            headers={"User-Agent": "bunken/1.0"},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None

    requested_title = normalize_title_for_match(normalized_title)
    requested_year = int(year or 0) if str(year or "").isdigit() else 0
    best = None
    best_score = 0
    for item in response.json().get("message", {}).get("items", []):
        candidate_title = item["title"][0] if item.get("title") else ""
        candidate_year = 0
        issued = item.get("issued", {}).get("date-parts", [])
        if issued and issued[0]:
            candidate_year = int(issued[0][0] or 0)

        score = 0
        if normalize_title_for_match(candidate_title) == requested_title:
            score += 80
        elif requested_title and requested_title in normalize_title_for_match(candidate_title):
            score += 45
        if requested_year and candidate_year == requested_year:
            score += 20
        doi = normalize_doi(item.get("DOI"))
        if doi:
            score += 10

        if score > best_score:
            metadata = crossref_message_to_metadata(item)
            best = {
                "doi": doi,
                "title": metadata[0],
                "authors": metadata[1],
                "journal": metadata[2],
                "year": metadata[3],
                "volume": metadata[4],
                "issue": metadata[5],
                "pages": metadata[6],
                "publisher": metadata[7],
                "score": score,
            }
            best_score = score

    if not best or best["score"] < 80:
        return None
    return best


def build_missing_doi_candidates(papers):
    candidates = []
    for paper in papers:
        if normalize_doi(paper.get("doi")):
            continue
        candidate = fetch_crossref_candidate_by_title(
            paper.get("title"),
            paper.get("year"),
        )
        if not candidate or not candidate.get("doi"):
            continue
        candidates.append({"paper": paper, "candidate": candidate})
    return candidates


PUBLICATION_METADATA_FIELDS = (
    ("volume", "巻"),
    ("issue", "号"),
    ("pages", "ページ"),
    ("publisher", "出版社"),
)


def get_missing_publication_metadata_fields(paper):
    return [
        (field, label)
        for field, label in PUBLICATION_METADATA_FIELDS
        if not paper.get(field)
    ]


def format_missing_publication_metadata(paper):
    return " / ".join(label for _, label in get_missing_publication_metadata_fields(paper))


def build_metadata_gap_rows(papers):
    return [
        {
            "タイトル": paper.get("title") or "無題",
            "DOI": normalize_doi(paper.get("doi")) or "",
            "不足項目": format_missing_publication_metadata(paper),
        }
        for paper in papers
        if has_missing_publication_metadata(paper)
    ]


def has_missing_publication_metadata(paper):
    return bool(get_missing_publication_metadata_fields(paper))


def build_existing_doi_metadata_candidates(papers):
    candidates = []
    for paper in papers:
        doi = normalize_doi(paper.get("doi"))
        if not doi or not clean_optional_id(paper.get("item_id")):
            continue
        if not has_missing_publication_metadata(paper):
            continue
        metadata = fetch_doi(doi)
        if not metadata:
            continue
        candidate = {
            "doi": doi,
            "title": metadata[0],
            "authors": metadata[1],
            "journal": metadata[2],
            "year": metadata[3],
            "volume": metadata[4],
            "issue": metadata[5],
            "pages": metadata[6],
            "publisher": metadata[7],
        }
        if any(candidate.get(field) and not paper.get(field) for field in ("volume", "issue", "pages", "publisher")):
            candidates.append({"paper": paper, "candidate": candidate})
    return candidates


def normalize_import_year(value):
    text = str(value or "").strip()
    match = re.search(r"\d{4}", text)
    return int(match.group(0)) if match else 0


def normalize_import_candidate(candidate):
    return {
        "title": candidate.get("title") or "",
        "authors": candidate.get("authors") or "",
        "journal": candidate.get("journal") or "",
        "year": normalize_import_year(candidate.get("year")),
        "doi": normalize_doi(candidate.get("doi")),
        "url": normalize_url(candidate.get("url")) or "",
        "volume": candidate.get("volume") or "",
        "issue": candidate.get("issue") or "",
        "pages": candidate.get("pages") or "",
        "publisher": candidate.get("publisher") or "",
        "import_error": candidate.get("import_error") or "",
    }


def format_import_missing_fields(candidate):
    missing = []
    for field, label in IMPORT_REQUIRED_FIELDS:
        if field == "doi":
            if not normalize_doi(candidate.get(field)):
                missing.append(label)
        elif not candidate.get(field):
            missing.append(label)
    return " / ".join(missing)


def find_import_duplicate(candidate, existing_records):
    duplicate = find_import_duplicate_details(candidate, existing_records)
    return duplicate.get("label", "") if duplicate else ""


def find_import_duplicate_details(candidate, existing_records):
    candidate_doi = normalize_doi(candidate.get("doi")).casefold()
    candidate_title = normalize_title_for_match(candidate.get("title"))
    candidate_year = normalize_import_year(candidate.get("year"))
    for record in existing_records:
        record_doi = normalize_doi(record.get("doi")).casefold()
        if candidate_doi and record_doi == candidate_doi:
            title = record.get("title") or "無題"
            return {
                "label": f"登録済みの可能性が高い: DOI一致: {title}",
                "match_type": "DOI",
                "confidence": "高",
                "existing_id": str(record.get("id") or ""),
                "existing_title": title,
                "existing_year": record.get("year") or "",
            }
        if (
            candidate_title
            and candidate_title == normalize_title_for_match(record.get("title"))
            and candidate_year
            and candidate_year == normalize_import_year(record.get("year"))
        ):
            title = record.get("title") or "無題"
            return {
                "label": f"登録済みかも: タイトル+年一致: {title}",
                "match_type": "タイトル+年",
                "confidence": "中",
                "existing_id": str(record.get("id") or ""),
                "existing_title": title,
                "existing_year": record.get("year") or "",
            }
    return {}


def create_imported_paper(candidate, user_id, tags_text="", pdf_file=None):
    normalized = normalize_import_candidate(candidate)
    pdf_path = upload_pdf_to_storage(supabase, pdf_file, user_id) if pdf_file else None
    next_order = get_next_display_order(supabase, user_id)
    created_paper = create_user_paper(
        supabase,
        user_id,
        normalized["title"],
        normalized["authors"],
        normalized["journal"],
        normalized["year"],
        normalized["doi"],
        normalized["url"],
        pdf_path,
        None,
        "未読",
        "",
        next_order,
        normalized["volume"],
        normalized["issue"],
        normalized["pages"],
        normalized["publisher"],
    )
    if tags_text:
        if created_paper.get("item_id"):
            save_tags_for_item(supabase, user_id, created_paper["item_id"], tags_text)
        else:
            save_tags_for_paper(supabase, user_id, created_paper["id"], tags_text)
    return created_paper


def update_existing_paper_from_import(existing_record, candidate, user_id, pdf_file=None):
    normalized = normalize_import_candidate(candidate)
    item_id = clean_optional_id(existing_record.get("item_id"))
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
        extra["legacy_status"] = existing_record.get("status") or "未読"
        item_fields = {
            "title": normalized["title"] or existing_record.get("title") or "",
            "publication_title": normalized["journal"] or existing_record.get("journal") or "",
            "year": normalize_import_year(normalized["year"] or existing_record.get("year")),
            "doi": normalized["doi"] or normalize_doi(existing_record.get("doi")) or None,
            "url": normalized["url"] or normalize_url(existing_record.get("url")) or None,
            "abstract_note": existing_record.get("notes") or "",
            "extra": extra,
            "volume": normalized["volume"] or existing_record.get("volume") or None,
            "issue": normalized["issue"] or existing_record.get("issue") or None,
            "pages": normalized["pages"] or existing_record.get("pages") or None,
            "publisher": normalized["publisher"] or existing_record.get("publisher") or None,
        }
        (
            supabase.table("items")
            .update(item_fields)
            .eq("id", item_id)
            .eq("user_id", user_id)
            .execute()
        )
        if normalized["authors"]:
            (
                supabase.table("creators")
                .delete()
                .eq("item_id", item_id)
                .execute()
            )
            for position, name in enumerate(
                [name.strip() for name in normalized["authors"].split(",") if name.strip()],
                start=1,
            ):
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
    else:
        (
            supabase.table("papers")
            .update(
                {
                    "title": normalized["title"] or existing_record.get("title") or "",
                    "authors": normalized["authors"] or existing_record.get("authors") or "",
                    "journal": normalized["journal"] or existing_record.get("journal") or "",
                    "year": normalize_import_year(normalized["year"] or existing_record.get("year")),
                    "doi": normalized["doi"] or normalize_doi(existing_record.get("doi")) or None,
                    "url": normalized["url"] or normalize_url(existing_record.get("url")) or None,
                    "status": existing_record.get("status") or "未読",
                    "notes": existing_record.get("notes") or "",
                }
            )
            .eq("id", existing_record["id"])
            .eq("user_id", user_id)
            .execute()
        )
    if pdf_file and not existing_record.get("pdf_path"):
        pdf_path = upload_pdf_to_storage(supabase, pdf_file, user_id)
        update_paper_files(
            supabase,
            user_id,
            existing_record["id"],
            pdf_path=pdf_path,
            supporting_path=None,
            item_id=item_id,
        )


def render_import_candidates(candidates, existing_records, key_prefix, pdf_files=None):
    normalized_candidates = [normalize_import_candidate(candidate) for candidate in candidates]
    if not normalized_candidates:
        st.write("インポート候補はありません。")
        return

    duplicate_details = [
        find_import_duplicate_details(candidate, existing_records)
        for candidate in normalized_candidates
    ]
    preview_rows = []
    for index, candidate in enumerate(normalized_candidates, start=1):
        duplicate = duplicate_details[index - 1]
        preview_rows.append(
            {
                "番号": index,
                "タイトル": candidate["title"],
                "著者": candidate["authors"],
                "雑誌": candidate["journal"],
                "年": candidate["year"],
                "DOI": candidate["doi"],
                "URL": candidate["url"],
                "巻": candidate["volume"],
                "号": candidate["issue"],
                "ページ": candidate["pages"],
                "出版社": candidate["publisher"],
                "不足項目": format_import_missing_fields(candidate),
                "取得状況": candidate.get("import_error") or "OK",
                "判定": duplicate.get("label", ""),
                "信頼度": duplicate.get("confidence", ""),
                "既存ID": duplicate.get("existing_id", ""),
                "重複時の処理": "スキップ" if duplicate else "追加",
            }
        )
    edited_rows = st.data_editor(
        pd.DataFrame(preview_rows),
        hide_index=True,
        use_container_width=True,
        disabled=["番号", "不足項目", "取得状況", "判定", "信頼度", "既存ID"],
        column_config={
            "重複時の処理": st.column_config.SelectboxColumn(
                "重複時の処理",
                options=["スキップ", "既存を更新", "別文献として追加", "追加"],
            )
        },
        key=f"{key_prefix}_editor",
    )
    duplicate_count = sum(1 for duplicate in duplicate_details if duplicate)
    if duplicate_count:
        st.warning(
            f"{duplicate_count}件に重複候補があります。スキップ、既存を更新、別文献として追加を選べます。"
        )
        compare_rows = []
        existing_by_id = {str(record.get("id")): record for record in existing_records}
        for row in preview_rows:
            existing = existing_by_id.get(str(row.get("既存ID") or ""))
            if not existing:
                continue
            compare_rows.append(
                {
                    "番号": row["番号"],
                    "既存タイトル": existing.get("title") or "",
                    "取込タイトル": row["タイトル"],
                    "既存DOI": normalize_doi(existing.get("doi")),
                    "取込DOI": row["DOI"],
                    "既存年": existing.get("year") or "",
                    "取込年": row["年"],
                }
            )
        if compare_rows:
            with st.expander("既存文献との差分を確認"):
                st.dataframe(pd.DataFrame(compare_rows), hide_index=True, use_container_width=True)

    import_tags = st.text_input(
        "インポート時に追加するタグ（任意・カンマ区切り）",
        key=f"{key_prefix}_tags",
    )
    if st.button("候補をインポート", key=f"{key_prefix}_apply"):
        imported_count = 0
        skipped_count = 0
        updated_count = 0
        failed_count = 0
        existing_by_id = {str(record.get("id")): record for record in existing_records}
        edited_records = edited_rows.to_dict(orient="records")
        for index, row in enumerate(edited_records):
            action = row.get("重複時の処理") or "追加"
            duplicate = duplicate_details[index]
            if row.get("取得状況") and row.get("取得状況") != "OK" and not row.get("タイトル"):
                failed_count += 1
                continue
            if duplicate and action == "スキップ":
                skipped_count += 1
                continue
            candidate = {
                "title": row.get("タイトル") or "",
                "authors": row.get("著者") or "",
                "journal": row.get("雑誌") or "",
                "year": row.get("年") or 0,
                "doi": row.get("DOI") or "",
                "url": row.get("URL") or "",
                "volume": row.get("巻") or "",
                "issue": row.get("号") or "",
                "pages": row.get("ページ") or "",
                "publisher": row.get("出版社") or "",
            }
            if not candidate["title"] and not candidate["doi"]:
                skipped_count += 1
                continue
            pdf_file = pdf_files[index] if pdf_files and index < len(pdf_files) else None
            if duplicate and action == "既存を更新":
                existing = existing_by_id.get(str(duplicate.get("existing_id") or ""))
                if not existing:
                    failed_count += 1
                    continue
                update_existing_paper_from_import(existing, candidate, get_current_user_id(), pdf_file=pdf_file)
                updated_count += 1
            else:
                create_imported_paper(
                    candidate,
                    get_current_user_id(),
                    tags_text=import_tags,
                    pdf_file=pdf_file,
                )
                imported_count += 1
        clear_library_caches()
        st.success(
            f"インポートしました: 追加 {imported_count}件 / 更新 {updated_count}件 / "
            f"スキップ {skipped_count}件 / 失敗 {failed_count}件"
        )
        st.rerun()


def fetch_url_metadata(url):
    normalized_url = normalize_url(url)
    if not normalized_url or not is_public_http_url(normalized_url):
        return None

    doi_from_url = extract_doi(normalized_url)
    if doi_from_url:
        doi_result = fetch_doi(doi_from_url)
        if doi_result:
            return (*doi_result, doi_from_url)

    try:
        response = fetch_public_url(normalized_url)
    except requests.RequestException:
        return None

    if response is None:
        return None

    parser = MetadataParser()
    html_text = response.text[:METADATA_FETCH_BYTES]
    parser.feed(html_text)
    meta = parser.meta

    doi_from_page = extract_doi(response.url) or extract_doi(html_text)
    if doi_from_page:
        doi_result = fetch_doi(doi_from_page)
        if doi_result:
            return (*doi_result, doi_from_page)

    def first(*keys):
        for key in keys:
            values = meta.get(key.lower())
            if values:
                return values[0]
        return ""

    title = first("citation_title", "dc.title", "og:title") or parser.page_title
    authors = ", ".join(meta.get("citation_author", [])) or first("author", "dc.creator")
    journal = first(
        "citation_journal_title",
        "citation_conference_title",
        "dc.source",
        "og:site_name",
    )
    year_text = first(
        "citation_publication_date",
        "citation_online_date",
        "citation_date",
        "dc.date",
        "article:published_time",
    )
    year_match = re.search(r"\d{4}", year_text or "")
    year = int(year_match.group(0)) if year_match else 0
    doi = first("citation_doi", "dc.identifier")
    doi = extract_doi(doi) or doi
    volume = first("citation_volume")
    issue = first("citation_issue")
    pages = first("citation_firstpage")
    last_page = first("citation_lastpage")
    if pages and last_page:
        pages = f"{pages}-{last_page}"
    publisher = first("citation_publisher", "dc.publisher")

    if not any([title, authors, journal, year, doi, volume, issue, pages, publisher]):
        return None

    return title, authors, journal, year, volume, issue, pages, publisher, doi


if "user_id" not in st.session_state:
    promote_url_fragment_to_query_params()

    reset_type = get_query_param("type")
    if reset_type == "recovery" or get_query_param("access_token"):
        show_password_update_form()
        st.stop()

    st.title("ログイン")

    auth_mode = st.radio("選択", ["ログイン", "新規登録", "パスワード再設定"])

    if auth_mode == "パスワード再設定":
        show_password_reset_request_form()
        st.stop()

    with st.form("auth_form"):
        email = st.text_input("メールアドレス")
        username = ""
        if auth_mode == "新規登録":
            username = st.text_input("ユーザー名")
        password = st.text_input("パスワード", type="password")
        submit_label = "登録" if auth_mode == "新規登録" else "ログイン"
        submitted = st.form_submit_button(submit_label)

    if auth_mode == "新規登録":
        if submitted:
            normalized_email = normalize_email(email)
            normalized_username = normalize_username(username)
            if not normalized_email or not normalized_username or not password:
                st.error("メールアドレス、ユーザー名、パスワードを入力してください。")
            else:
                try:
                    response = register_user(
                        supabase,
                        normalized_email,
                        password,
                        normalized_username,
                    )
                    if getattr(response, "session", None) and getattr(response, "user", None):
                        store_auth_session(response.session)
                        set_authenticated_user(supabase, response.user, normalized_username)
                        st.success("登録完了")
                        st.rerun()
                    else:
                        st.success("登録しました。メール確認後にログインしてください。")
                except Exception as error:
                    st.error(f"登録失敗: {error}")
    else:
        if submitted:
            normalized_email = normalize_email(email)
            if not normalized_email or not password:
                st.error("メールアドレスとパスワードを入力してください。")
            else:
                try:
                    response = login_user(supabase, normalized_email, password)
                    if getattr(response, "session", None) and getattr(response, "user", None):
                        store_auth_session(response.session)
                        set_authenticated_user(supabase, response.user)
                        st.success("ログイン成功")
                        st.rerun()
                    else:
                        st.error("ログイン情報を確認してください。")
                except Exception as error:
                    error_text = str(error)
                    if "Email not confirmed" in error_text:
                        st.error("メール確認がまだ完了していません。確認メールをご確認ください。")
                    else:
                        st.error(f"ログイン失敗: {error}")

    st.stop()


if st.sidebar.button("ログアウト"):
    sign_out_user(supabase)
    st.rerun()

st.sidebar.write(f"ログイン中: {st.session_state.get('username', '')}")
if st.session_state.get("email"):
    st.sidebar.caption(st.session_state["email"])

st.title("📚 文献管理アプリ")
post_action_warning = st.session_state.pop("post_action_warning", None)
if post_action_warning:
    st.warning(post_action_warning)
MENU_OPTIONS = [
    "追加",
    "検索",
    "一覧",
    "詳細",
    "PDF読書",
    "インポート",
    "タグ検索",
    "コレクション",
    "重複確認",
    "文書引用",
]
if st.session_state.get("active_menu") not in MENU_OPTIONS:
    st.session_state["active_menu"] = "追加"
menu = st.sidebar.selectbox(
    "メニュー",
    MENU_OPTIONS,
    index=MENU_OPTIONS.index(st.session_state["active_menu"]),
)
st.session_state["active_menu"] = menu


if menu == "追加":
    user_id = get_current_user_id()
    st.header("文献追加")

    title = st.text_input("タイトル", value=st.session_state.get("title", ""))
    authors = st.text_input("著者", value=st.session_state.get("authors", ""))
    journal = st.text_input("雑誌", value=st.session_state.get("journal", ""))
    year = st.number_input("年", value=int(st.session_state.get("year", 2024)), step=1)
    meta_col1, meta_col2 = st.columns(2)
    with meta_col1:
        volume = st.text_input("巻", value=st.session_state.get("volume", ""))
        pages = st.text_input("ページ", value=st.session_state.get("pages", ""))
    with meta_col2:
        issue = st.text_input("号", value=st.session_state.get("issue", ""))
        publisher = st.text_input("出版社", value=st.session_state.get("publisher", ""))
    pdf_file = st.file_uploader("PDFアップロード", type=["pdf"])
    supporting_file = st.file_uploader(
        "サポーティング資料アップロード",
        type=SUPPORTING_FILE_TYPES,
    )
    doi = st.text_input("DOI", value=st.session_state.get("doi", ""))
    url = st.text_input("URL", value=st.session_state.get("url", ""))

    if st.button("DOIから自動入力"):
        result = fetch_doi(doi)
        if result:
            for field_name, value in zip(DOI_FORM_FIELDS, result):
                st.session_state[field_name] = value
            st.rerun()
        st.error("取得失敗")

    if st.button("URLから自動入力"):
        result = fetch_url_metadata(url)
        if result:
            for field_name, value in zip(URL_FORM_FIELDS, result):
                st.session_state[field_name] = value
            st.session_state["url"] = normalize_url(url)
            st.rerun()
        st.error("取得失敗")

    tags = st.text_input("タグ（カンマ区切り）")
    status = st.selectbox("読書ステータス", READING_STATUSES)
    notes = st.text_area("抄録メモ", height=150)

    if st.button("追加"):
        normalized_doi = normalize_doi(doi)
        normalized_url = normalize_url(url)

        if normalized_doi:
            existing = find_existing_user_paper_by_doi(
                supabase,
                user_id,
                normalized_doi,
                columns="id, title",
            )

            if existing:
                st.warning("このDOIの文献はすでに登録されています。")
                st.stop()

        try:
            pdf_path = upload_pdf_to_storage(supabase, pdf_file, user_id) if pdf_file else None
            supporting_path = (
                upload_supporting_file_to_storage(supabase, supporting_file, user_id)
                if supporting_file
                else None
            )

            next_order = get_next_display_order(supabase, user_id)
            created_paper = create_user_paper(
                supabase,
                user_id,
                title,
                authors,
                journal,
                year,
                normalized_doi,
                normalized_url,
                pdf_path,
                supporting_path,
                status,
                notes,
                next_order,
                volume,
                issue,
                pages,
                publisher,
            )
            if created_paper.get("item_id"):
                save_tags_for_item(supabase, user_id, created_paper["item_id"], tags)
            else:
                save_tags_for_paper(supabase, user_id, created_paper["id"], tags)
            clear_library_caches()
            st.success("追加しました！")
        except Exception:
            logger.exception("Failed to add paper")
            st.error("保存に失敗しました。入力内容とログを確認してください。")


elif menu == "検索":
    user_id = get_current_user_id()
    keyword = st.text_input("キーワード").strip()
    col1, col2 = st.columns(2)
    with col1:
        year_from = st.number_input("開始年", min_value=0, value=0, step=1)
    with col2:
        year_to = st.number_input("終了年", min_value=0, value=0, step=1)

    status_filter = st.selectbox("ステータス", [""] + READING_STATUSES)
    attachment_filter = st.selectbox(
        "添付",
        ["", "PDFあり", "補足資料あり", "添付あり", "添付なし"],
    )

    if st.button("検索"):
        result = fetch_user_papers(
            supabase,
            user_id,
            columns=(
                "id, item_id, title, authors, journal, year, doi, url, volume, issue, "
                "pages, publisher, item_type, status, notes, pdf_path, "
                "supporting_path, display_order"
            ),
        )
        papers = filter_papers(
            result.data or [],
            keyword=keyword,
            year_from=int(year_from) if year_from else None,
            year_to=int(year_to) if year_to else None,
            status=status_filter,
            attachment_filter=attachment_filter,
        )

        if not papers:
            st.write("見つかりません")
        else:
            st.write(f"{len(papers)}件見つかりました")
            tag_map = get_tag_map_for_papers(supabase, papers)
            citation_usage_map = get_citation_usage_map_for_display(user_id, papers)
            for paper in papers:
                with st.container():
                    render_paper_summary(
                        paper,
                        tag_map=tag_map,
                        citation_usage_map=citation_usage_map,
                    )
                    st.divider()


elif menu == "一覧":
    user_id = get_current_user_id()
    all_records = fetch_list_records_cached(user_id)
    try:
        collections = fetch_collections_cached(user_id)
    except Exception:
        logger.exception("Failed to fetch collections")
        collections = []
    collection_label_by_id, collection_id_by_label = build_collection_label_maps(collections)

    st.header("📚 論文一覧")

    with st.expander("絞り込み", expanded=True):
        keyword = st.text_input("タイトル・著者・DOI・メモで絞り込み", key="list_keyword").strip()
        filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
        with filter_col1:
            status_filter = st.selectbox(
                "ステータス",
                [""] + READING_STATUSES,
                key="list_status_filter",
            )
        with filter_col2:
            attachment_filter = st.selectbox(
                "添付",
                ["", "PDFあり", "補足資料あり", "添付あり", "添付なし"],
                key="list_attachment_filter",
            )
        with filter_col3:
            selected_collection_label = st.selectbox(
                "コレクション",
                ["すべて"] + list(collection_id_by_label.keys()),
                key="list_collection_filter",
            )
        with filter_col4:
            smart_filter = st.selectbox(
                "スマート",
                ["", "DOIなし", "PDFなし", "PDFあり", "未読", "引用予定", "メタデータ不足"],
                key="list_smart_filter",
            )

        scoped_records = all_records
        if selected_collection_label != "すべて":
            selected_collection_id = collection_id_by_label[selected_collection_label]
            try:
                scoped_records = fetch_collection_papers_cached(user_id, selected_collection_id)
            except Exception:
                logger.exception("Failed to fetch papers for selected collection")
                st.warning("コレクション内の文献取得に失敗しました。全件から絞り込みます。")
                scoped_records = all_records

        scoped_tag_map = get_tag_map_for_papers(supabase, scoped_records)
        tag_options = sorted(
            {
                tag
                for record in scoped_records
                for tag in get_paper_tag_list(scoped_tag_map, record)
            },
            key=str.casefold,
        )
        selected_tag = st.selectbox(
            "タグ",
            ["すべて"] + tag_options,
            key="list_tag_filter",
        )

    filtered_records = filter_papers(
        scoped_records,
        keyword=keyword,
        status=status_filter,
        attachment_filter=attachment_filter,
    )
    if selected_tag != "すべて":
        filtered_records = [
            record
            for record in filtered_records
            if selected_tag in get_paper_tag_list(scoped_tag_map, record)
        ]
    if smart_filter == "DOIなし":
        filtered_records = [
            record for record in filtered_records if not normalize_doi(record.get("doi"))
        ]
    elif smart_filter == "PDFなし":
        filtered_records = [
            record for record in filtered_records if not record.get("pdf_path")
        ]
    elif smart_filter == "PDFあり":
        filtered_records = [
            record for record in filtered_records if record.get("pdf_path")
        ]
    elif smart_filter == "未読":
        filtered_records = [
            record for record in filtered_records if (record.get("status") or "") == "未読"
        ]
    elif smart_filter == "引用予定":
        filtered_records = [
            record for record in filtered_records if (record.get("status") or "") == "引用予定"
        ]
    elif smart_filter == "メタデータ不足":
        filtered_records = [
            record
            for record in filtered_records
            if normalize_doi(record.get("doi")) and has_missing_publication_metadata(record)
        ]
    df = pd.DataFrame(filtered_records)

    if all_records:
        st.caption(f"{len(filtered_records)} / {len(all_records)} 件を表示")

    sort_option = st.selectbox("並び替え", SORT_OPTIONS)
    added_oldest_first = st.session_state.get("list_added_oldest_first", False)
    if sort_option == "追加順":
        current_order_label = "古い順" if added_oldest_first else "新しい順"
        if st.button(
            f"追加順を切替（現在: {current_order_label}）",
            key="toggle_list_added_order",
        ):
            st.session_state["list_added_oldest_first"] = not added_oldest_first
            st.rerun()
    df = sort_papers_dataframe(df, sort_option, added_oldest_first=added_oldest_first)

    if not all_records:
        st.write("データがありません")
    elif df.empty:
        st.write("絞り込み条件に一致する文献はありません。")
    else:
        records = df.to_dict(orient="records")
        tag_map = get_tag_map_for_papers(supabase, records)
        list_view_mode = st.segmented_control(
            "表示形式",
            ["カード", "3ペイン"],
            default="カード",
            key="list_view_mode",
        )
        citation_usage_map = {}
        if list_view_mode != "3ペイン":
            citation_usage_map = get_citation_usage_map_for_display(user_id, records)
        missing_doi_records = [
            record for record in records if not normalize_doi(record.get("doi"))
        ]
        doi_metadata_records = [
            record
            for record in records
            if normalize_doi(record.get("doi"))
            and clean_optional_id(record.get("item_id"))
            and has_missing_publication_metadata(record)
        ]
        tool_col1, tool_col2, tool_col3, tool_spacer = st.columns([1, 1, 1, 3])
        with tool_col1:
            with st.popover("エクスポート", use_container_width=True):
                export_col1, export_col2, export_col3 = st.columns(3)
                with export_col1:
                    word_bytes = export_to_word_bytes(records)
                    st.download_button(
                        "Word",
                        data=word_bytes,
                        file_name="references.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True,
                    )
                with export_col2:
                    st.download_button(
                        "BibTeX",
                        data=export_to_bibtex_text(records).encode("utf-8"),
                        file_name="references.bib",
                        mime="application/x-bibtex",
                        use_container_width=True,
                    )
                with export_col3:
                    st.download_button(
                        "RIS",
                        data=export_to_ris_text(records).encode("utf-8"),
                        file_name="references.ris",
                        mime="application/x-research-info-systems",
                        use_container_width=True,
                    )
        bulk_options = {
            f"[{record.get('ref_no')}] {record.get('title') or '無題'} ({record.get('year') or '-'})": record
            for record in records
        }
        with st.expander("一括操作"):
            selected_bulk_labels = st.multiselect(
                "対象文献",
                list(bulk_options.keys()),
                key="list_bulk_selection",
            )
            selected_bulk_records = [bulk_options[label] for label in selected_bulk_labels]
            st.caption(f"{len(selected_bulk_records)}件を選択中")

            bulk_tab1, bulk_tab2, bulk_tab3, bulk_tab4 = st.tabs(
                ["タグ", "コレクション", "ステータス", "エクスポート"]
            )
            with bulk_tab1:
                bulk_tags = st.text_input(
                    "追加するタグ（カンマ区切り）",
                    key="list_bulk_tags",
                )
                if st.button("選択文献にタグ追加", key="apply_bulk_tags"):
                    if not selected_bulk_records:
                        st.error("対象文献を選択してください。")
                    else:
                        for record in selected_bulk_records:
                            item_id = clean_optional_id(record.get("item_id"))
                            if item_id:
                                save_tags_for_item(supabase, user_id, item_id, bulk_tags)
                            else:
                                save_tags_for_paper(supabase, user_id, record["id"], bulk_tags)
                        clear_library_caches()
                        st.success(f"{len(selected_bulk_records)}件にタグを追加しました。")
                        st.rerun()

            with bulk_tab2:
                bulk_collection_labels = st.multiselect(
                    "追加先コレクション",
                    list(collection_id_by_label.keys()),
                    key="list_bulk_collections",
                )
                if st.button("選択文献をコレクションに追加", key="apply_bulk_collections"):
                    if not selected_bulk_records:
                        st.error("対象文献を選択してください。")
                    elif not bulk_collection_labels:
                        st.error("追加先コレクションを選択してください。")
                    else:
                        collection_ids_to_add = {
                            collection_id_by_label[label]
                            for label in bulk_collection_labels
                        }
                        for record in selected_bulk_records:
                            item_id = clean_optional_id(record.get("item_id"))
                            current_ids = set(
                                fetch_paper_collection_ids(
                                    supabase,
                                    record["id"],
                                    item_id,
                                )
                            )
                            set_paper_collections(
                                supabase,
                                record["id"],
                                sorted(current_ids | collection_ids_to_add),
                                item_id=item_id,
                            )
                        clear_library_caches()
                        st.success(f"{len(selected_bulk_records)}件をコレクションに追加しました。")
                        st.rerun()

            with bulk_tab3:
                bulk_status = st.selectbox(
                    "変更後ステータス",
                    READING_STATUSES,
                    key="list_bulk_status",
                )
                if st.button("選択文献のステータス変更", key="apply_bulk_status"):
                    if not selected_bulk_records:
                        st.error("対象文献を選択してください。")
                    else:
                        for record in selected_bulk_records:
                            update_paper_details(
                                supabase,
                                user_id,
                                record["id"],
                                bulk_status,
                                record.get("notes") or "",
                                normalize_url(record.get("url")) or None,
                                item_id=clean_optional_id(record.get("item_id")),
                                doi=normalize_doi(record.get("doi")),
                                volume=record.get("volume") or "",
                                issue=record.get("issue") or "",
                                pages=record.get("pages") or "",
                                publisher=record.get("publisher") or "",
                            )
                        clear_library_caches()
                        st.success(f"{len(selected_bulk_records)}件のステータスを変更しました。")
                        st.rerun()

            with bulk_tab4:
                if selected_bulk_records:
                    export_targets = selected_bulk_records
                    export_suffix = "selected"
                else:
                    export_targets = records
                    export_suffix = "filtered"
                    st.caption("未選択の場合は、現在表示中の全件を出力します。")
                export_col1, export_col2, export_col3 = st.columns(3)
                with export_col1:
                    st.download_button(
                        "Word",
                        data=export_to_word_bytes(export_targets),
                        file_name=f"references-{export_suffix}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key="bulk_export_word",
                        use_container_width=True,
                    )
                with export_col2:
                    st.download_button(
                        "BibTeX",
                        data=export_to_bibtex_text(export_targets).encode("utf-8"),
                        file_name=f"references-{export_suffix}.bib",
                        mime="application/x-bibtex",
                        key="bulk_export_bibtex",
                        use_container_width=True,
                    )
                with export_col3:
                    st.download_button(
                        "RIS",
                        data=export_to_ris_text(export_targets).encode("utf-8"),
                        file_name=f"references-{export_suffix}.ris",
                        mime="application/x-research-info-systems",
                        key="bulk_export_ris",
                        use_container_width=True,
                    )
        with tool_col2:
            doi_popover_label = f"DOI取得 ({len(missing_doi_records)})"
            doi_popover = st.popover(doi_popover_label, use_container_width=True)
        with doi_popover:
            st.caption(
                "Crossrefでタイトル検索し、タイトル一致または年一致の強い候補だけを表示します。"
                "適用時も空のDOIだけを埋め、既存のDOIは上書きしません。"
            )
            if st.button("候補を検索", key="preview_missing_doi_candidates"):
                with st.spinner("Crossrefで候補を検索しています..."):
                    st.session_state["missing_doi_candidates"] = build_missing_doi_candidates(
                        missing_doi_records
                    )

            candidates = st.session_state.get("missing_doi_candidates", [])
            missing_doi_searched = "missing_doi_candidates" in st.session_state
            if candidates:
                st.write(f"{len(candidates)}件の候補が見つかりました。")
                for item in candidates:
                    paper = item["paper"]
                    candidate = item["candidate"]
                    st.write(
                        f"- {paper.get('title') or '無題'} "
                        f"→ DOI: {candidate.get('doi')} "
                        f"({candidate.get('journal') or '-'}, {candidate.get('year') or '-'})"
                    )

                apply_confirm = st.checkbox(
                    "候補を確認しました。空欄のDOIと不足している巻・号・ページ・出版社を更新します。",
                    key="apply_missing_doi_confirm",
                )
                if st.button("候補を適用", key="apply_missing_doi_candidates"):
                    if not apply_confirm:
                        st.error("適用するには確認チェックを入れてください。")
                    else:
                        updated_count = 0
                        skipped_count = 0
                        for item in candidates:
                            paper = item["paper"]
                            candidate = item["candidate"]
                            if normalize_doi(paper.get("doi")):
                                skipped_count += 1
                                continue
                            existing = find_existing_user_paper_by_doi(
                                supabase,
                                user_id,
                                candidate["doi"],
                                columns="id, item_id, title",
                            )
                            existing_ids = {
                                str(existing.get("id")),
                                str(existing.get("item_id")),
                            } if existing else set()
                            paper_ids = {
                                str(paper.get("id")),
                                str(paper.get("item_id")),
                            }
                            if existing and not (existing_ids & paper_ids):
                                skipped_count += 1
                                continue

                            update_paper_details(
                                supabase,
                                user_id,
                                paper["id"],
                                paper.get("status") or "",
                                paper.get("notes") or "",
                                normalize_url(paper.get("url")) or None,
                                item_id=clean_optional_id(paper.get("item_id")),
                                doi=candidate["doi"],
                                volume=paper.get("volume") or candidate.get("volume") or "",
                                issue=paper.get("issue") or candidate.get("issue") or "",
                                pages=paper.get("pages") or candidate.get("pages") or "",
                                publisher=paper.get("publisher")
                                or candidate.get("publisher")
                                or "",
                            )
                            updated_count += 1
                        st.session_state.pop("missing_doi_candidates", None)
                        clear_library_caches()
                        st.success(
                            f"DOI候補を適用しました: 更新 {updated_count}件 / スキップ {skipped_count}件"
                        )
                        st.rerun()
            elif missing_doi_searched and missing_doi_records:
                st.info(
                    "Crossrefで適用できるDOI候補は見つかりませんでした。"
                    "タイトルや年を確認してから再検索してください。"
                )
            elif missing_doi_records:
                st.write("候補検索を実行してください。")
            else:
                st.write("DOI未入力の文献はありません。")
        with tool_col3:
            metadata_popover = st.popover(
                f"メタデータ補完 ({len(doi_metadata_records)})",
                use_container_width=True,
            )
        with metadata_popover:
            st.caption(
                "既にDOIがある文献について、Crossrefから巻・号・ページ・出版社を取得します。"
                "既に入力済みの値は上書きしません。"
            )
            metadata_gap_rows = build_metadata_gap_rows(doi_metadata_records)
            if metadata_gap_rows:
                st.dataframe(metadata_gap_rows, hide_index=True, use_container_width=True)
                st.download_button(
                    "不足リストCSV",
                    data=pd.DataFrame(metadata_gap_rows).to_csv(index=False).encode("utf-8-sig"),
                    file_name="metadata-gaps.csv",
                    mime="text/csv",
                    key="download_metadata_gaps",
                    use_container_width=True,
                )
            if st.button("不足メタデータ候補を検索", key="preview_doi_metadata_candidates"):
                with st.spinner("CrossrefでDOIメタデータを取得しています..."):
                    st.session_state["doi_metadata_candidates"] = build_existing_doi_metadata_candidates(
                        doi_metadata_records
                    )

            metadata_candidates = st.session_state.get("doi_metadata_candidates", [])
            metadata_searched = "doi_metadata_candidates" in st.session_state
            if metadata_candidates:
                st.write(f"{len(metadata_candidates)}件の補完候補が見つかりました。")
                for item in metadata_candidates:
                    paper = item["paper"]
                    candidate = item["candidate"]
                    values = [
                        f"{label}: {candidate.get(field)}"
                        for label, field in (
                            ("巻", "volume"),
                            ("号", "issue"),
                            ("ページ", "pages"),
                            ("出版社", "publisher"),
                        )
                        if candidate.get(field) and not paper.get(field)
                    ]
                    st.write(f"- {paper.get('title') or '無題'} → " + " / ".join(values))

                metadata_confirm = st.checkbox(
                    "候補を確認しました。空欄の巻・号・ページ・出版社だけを補完します。",
                    key="apply_doi_metadata_confirm",
                )
                if st.button("メタデータ候補を適用", key="apply_doi_metadata_candidates"):
                    if not metadata_confirm:
                        st.error("適用するには確認チェックを入れてください。")
                    else:
                        updated_count = 0
                        for item in metadata_candidates:
                            paper = item["paper"]
                            candidate = item["candidate"]
                            update_paper_details(
                                supabase,
                                user_id,
                                paper["id"],
                                paper.get("status") or "",
                                paper.get("notes") or "",
                                normalize_url(paper.get("url")) or None,
                                item_id=clean_optional_id(paper.get("item_id")),
                                doi=normalize_doi(paper.get("doi")),
                                volume=paper.get("volume") or candidate.get("volume") or "",
                                issue=paper.get("issue") or candidate.get("issue") or "",
                                pages=paper.get("pages") or candidate.get("pages") or "",
                                publisher=paper.get("publisher")
                                or candidate.get("publisher")
                                or "",
                            )
                            updated_count += 1
                        st.session_state.pop("doi_metadata_candidates", None)
                        clear_library_caches()
                        st.success(f"DOIメタデータを補完しました: {updated_count}件")
                        st.rerun()
            elif metadata_searched and doi_metadata_records:
                st.info(
                    "Crossrefで補完できる巻・号・ページ・出版社は見つかりませんでした。"
                    "この場合、件数は不足メタデータとして残ります。右ペインの編集タブ、または詳細画面から手入力できます。"
                )
            elif doi_metadata_records:
                st.write("候補検索を実行してください。")
            else:
                st.write("DOIメタデータが不足している正規化文献はありません。")

        if list_view_mode == "3ペイン":
            pane_col1, pane_col2, pane_col3 = st.columns([1.1, 1.6, 2.3])
            with pane_col1:
                st.subheader("コレクション")
                st.write(f"表示中: {len(records)}件")
                if st.button(
                    f"全ライブラリ ({len(all_records)})",
                    key="list_pane_all_library",
                    use_container_width=True,
                    on_click=set_list_filters,
                    kwargs={
                        "collection_label": "すべて",
                        "tag_label": "すべて",
                        "smart_filter": "",
                    },
                ):
                    st.rerun()

                try:
                    pane_collection_counts = fetch_collection_counts_cached(
                        tuple(collection["id"] for collection in collections)
                    )
                except Exception:
                    logger.exception("Failed to fetch collection counts for list pane")
                    pane_collection_counts = {}

                for collection in collections:
                    collection_label = collection_label_by_id.get(collection["id"])
                    if not collection_label:
                        continue
                    count = pane_collection_counts.get(collection["id"], 0)
                    selected_prefix = "● " if selected_collection_label == collection_label else ""
                    if st.button(
                        f"{selected_prefix}{collection.get('name') or '無題'} ({count})",
                        key=f"list_pane_collection_{collection['id']}",
                        use_container_width=True,
                        on_click=set_list_filters,
                        kwargs={
                            "collection_label": collection_label,
                            "tag_label": "すべて",
                        },
                    ):
                        st.rerun()

                st.divider()
                st.subheader("スマート")
                smart_filter_options = [
                    ("", "すべて", len(scoped_records)),
                    (
                        "DOIなし",
                        "DOIなし",
                        sum(1 for record in scoped_records if not normalize_doi(record.get("doi"))),
                    ),
                    (
                        "PDFなし",
                        "PDFなし",
                        sum(1 for record in scoped_records if not record.get("pdf_path")),
                    ),
                    (
                        "PDFあり",
                        "PDFあり",
                        sum(1 for record in scoped_records if record.get("pdf_path")),
                    ),
                    (
                        "未読",
                        "未読",
                        sum(1 for record in scoped_records if (record.get("status") or "") == "未読"),
                    ),
                    (
                        "引用予定",
                        "引用予定",
                        sum(
                            1
                            for record in scoped_records
                            if (record.get("status") or "") == "引用予定"
                        ),
                    ),
                    (
                        "メタデータ不足",
                        "メタデータ不足",
                        sum(
                            1
                            for record in scoped_records
                            if normalize_doi(record.get("doi"))
                            and has_missing_publication_metadata(record)
                        ),
                    ),
                ]
                for filter_value, filter_label, count in smart_filter_options:
                    selected_prefix = "● " if smart_filter == filter_value else ""
                    if st.button(
                        f"{selected_prefix}{filter_label} ({count})",
                        key=f"list_pane_smart_{filter_value or 'all'}",
                        use_container_width=True,
                        on_click=set_list_filters,
                        kwargs={"smart_filter": filter_value},
                    ):
                        st.rerun()

                if tag_options:
                    st.divider()
                    st.subheader("タグ")
                    if st.button(
                        "タグなし指定を解除",
                        key="list_pane_tag_all",
                        use_container_width=True,
                        on_click=set_list_filters,
                        kwargs={"tag_label": "すべて"},
                    ):
                        st.rerun()
                    for tag in tag_options[:20]:
                        tag_count = sum(
                            1
                            for record in scoped_records
                            if tag in get_paper_tag_list(scoped_tag_map, record)
                        )
                        selected_prefix = "● " if selected_tag == tag else ""
                        if st.button(
                            f"{selected_prefix}{tag} ({tag_count})",
                            key=f"list_pane_tag_{tag}",
                            use_container_width=True,
                            on_click=set_list_filters,
                            kwargs={"tag_label": tag},
                        ):
                            st.rerun()
                if selected_tag != "すべて":
                    st.caption(f"タグ: {selected_tag}")
                if smart_filter:
                    st.caption(f"スマート: {smart_filter}")

            paper_by_id = {str(record["id"]): record for record in records}
            paper_ids = list(paper_by_id.keys())
            selected_list_paper_id = st.session_state.get("list_selected_paper_id")
            if selected_list_paper_id not in paper_by_id:
                selected_list_paper_id = str(records[0]["id"])
            selected_list_index = paper_ids.index(selected_list_paper_id)

            with pane_col2:
                st.subheader("文献")
                st.caption(f"{len(records)}件")
                nav_col1, nav_col2, nav_col3 = st.columns([1, 1, 1])
                with nav_col1:
                    if st.button(
                        "前へ",
                        key="list_pane_prev_paper",
                        disabled=selected_list_index <= 0,
                        use_container_width=True,
                    ):
                        st.session_state["list_selected_paper_id"] = paper_ids[
                            selected_list_index - 1
                        ]
                        st.rerun()
                with nav_col2:
                    st.caption(f"{selected_list_index + 1} / {len(paper_ids)}")
                with nav_col3:
                    if st.button(
                        "次へ",
                        key="list_pane_next_paper",
                        disabled=selected_list_index >= len(paper_ids) - 1,
                        use_container_width=True,
                    ):
                        st.session_state["list_selected_paper_id"] = paper_ids[
                            selected_list_index + 1
                        ]
                        st.rerun()
                for record_index, record in enumerate(records, start=1):
                    record_id = str(record["id"])
                    is_selected = record_id == selected_list_paper_id
                    title = record.get("title") or "無題"
                    authors = record.get("authors") or "著者不明"
                    year = record.get("year") or "-"
                    journal = record.get("journal") or "雑誌未設定"
                    status = record.get("status") or "未設定"
                    markers = []
                    if record.get("pdf_path"):
                        markers.append("PDF")
                    if normalize_doi(record.get("doi")):
                        markers.append("DOI")
                    missing_metadata_text = format_missing_publication_metadata(record)
                    if missing_metadata_text:
                        markers.append(f"メタ不足: {missing_metadata_text}")
                    marker_text = " / ".join(markers) if markers else "添付なし"

                    with st.container(border=is_selected):
                        st.markdown(f"**{title}**")
                        st.caption(f"{authors} / {journal} / {year}")
                        meta_col1, meta_col2 = st.columns([1.2, 1])
                        with meta_col1:
                            st.caption(f"{status} / {marker_text}")
                        with meta_col2:
                            button_label = "選択中" if is_selected else "選択"
                            if st.button(
                                button_label,
                                key=f"list_pane_select_{record_id}",
                                disabled=is_selected,
                                use_container_width=True,
                            ):
                                st.session_state["list_selected_paper_id"] = record_id
                                st.rerun()
                        if is_selected:
                            status_cols = st.columns(3)
                            for status_index, next_status in enumerate(
                                ("未読", "読書中", "読了")
                            ):
                                with status_cols[status_index]:
                                    if st.button(
                                        next_status,
                                        key=f"list_pane_quick_status_{record_id}_{next_status}",
                                        disabled=status == next_status,
                                        use_container_width=True,
                                    ):
                                        update_paper_details(
                                            supabase,
                                            user_id,
                                            record["id"],
                                            next_status,
                                            record.get("notes") or "",
                                            normalize_url(record.get("url")) or None,
                                            item_id=clean_optional_id(record.get("item_id")),
                                            doi=normalize_doi(record.get("doi")),
                                            volume=record.get("volume") or "",
                                            issue=record.get("issue") or "",
                                            pages=record.get("pages") or "",
                                            publisher=record.get("publisher") or "",
                                        )
                                        clear_library_caches()
                                        st.success(f"ステータスを{next_status}にしました。")
                                        st.rerun()
                    if record_index >= 80:
                        st.caption("表示件数が多いため、中央ペインは先頭80件まで表示しています。")
                        break

            selected_list_paper = paper_by_id[selected_list_paper_id]
            selected_reference_ids = tuple(
                str(reference_id)
                for reference_id in (
                    selected_list_paper.get("id"),
                    clean_optional_id(selected_list_paper.get("item_id")),
                )
                if reference_id is not None
            )
            selected_citation_usage_map = get_citation_usage_map_for_refs_cached(
                user_id,
                selected_reference_ids,
            )
            with pane_col3:
                st.subheader("詳細")
                quick_tabs = st.tabs(
                    ["概要", "PDF", "読書", "タグ", "引用", "Word引用", "編集"]
                )
                with quick_tabs[0]:
                    render_paper_summary(
                        selected_list_paper,
                        tag_map=tag_map,
                        citation_usage_map=selected_citation_usage_map,
                    )
                    detail_col1, detail_col2 = st.columns(2)
                    with detail_col1:
                        if st.button(
                            "詳細画面で開く",
                            key=f"list_pane_open_detail_{selected_list_paper['id']}",
                            use_container_width=True,
                        ):
                            st.session_state["detail_selected_paper_id"] = str(
                                selected_list_paper["id"]
                            )
                            st.session_state["active_menu"] = "詳細"
                            st.rerun()
                    with detail_col2:
                        paper_url = normalize_url(selected_list_paper.get("url"))
                        if paper_url:
                            st.link_button("Web", paper_url, use_container_width=True)
                with quick_tabs[1]:
                    render_paper_pdf_preview(selected_list_paper, key_prefix="list_pane")
                with quick_tabs[2]:
                    render_reading_workflow(
                        selected_list_paper,
                        user_id,
                        key_prefix="list_pane_reading",
                    )
                with quick_tabs[3]:
                    render_paper_tag_editor(
                        selected_list_paper,
                        user_id,
                        tag_map,
                        key_prefix="list_pane",
                    )
                with quick_tabs[4]:
                    citation_style = st.segmented_control(
                        "引用スタイル",
                        ["APA", "Vancouver", "Nature"],
                        default="APA",
                        key=f"list_pane_citation_style_{selected_list_paper['id']}",
                    )
                    citation_text = make_word_citation(
                        selected_list_paper,
                        style=citation_style,
                    )
                    st.code(citation_text)
                    citation_file_name = re.sub(
                        r"[^A-Za-z0-9._-]+",
                        "-",
                        selected_list_paper.get("title") or "citation",
                    ).strip("-")
                    export_col1, export_col2 = st.columns(2)
                    with export_col1:
                        st.download_button(
                            "BibTeX",
                            data=make_bibtex_entry(selected_list_paper).encode("utf-8"),
                            file_name=f"{citation_file_name or 'citation'}.bib",
                            mime="application/x-bibtex",
                            key=f"list_pane_bibtex_{selected_list_paper['id']}",
                            use_container_width=True,
                        )
                    with export_col2:
                        st.download_button(
                            "RIS",
                            data=make_ris_entry(selected_list_paper).encode("utf-8"),
                            file_name=f"{citation_file_name or 'citation'}.ris",
                            mime="application/x-research-info-systems",
                            key=f"list_pane_ris_{selected_list_paper['id']}",
                            use_container_width=True,
                        )
                with quick_tabs[5]:
                    usage_entries = get_paper_usage_entries(
                        selected_citation_usage_map,
                        selected_list_paper,
                    )
                    if not usage_entries:
                        st.write("この文献は同期済みWord文書ではまだ使われていません。")
                    else:
                        for entry in usage_entries:
                            st.markdown(f"**{entry.get('document_title') or '無題'}**")
                            if entry.get("citation_text"):
                                st.write(entry["citation_text"])
                            if entry.get("context_text"):
                                st.info(entry["context_text"])
                            if entry.get("updated_at"):
                                st.caption(f"更新: {entry['updated_at']}")
                with quick_tabs[6]:
                    render_paper_edit_form(
                        selected_list_paper,
                        user_id,
                        collections=collections,
                        collection_label_by_id=collection_label_by_id,
                        collection_id_by_label=collection_id_by_label,
                        key_prefix="list_pane_edit",
                    )
            st.stop()

        for _, row in df.iterrows():
            row_dict = row.to_dict()
            item_id = clean_optional_id(row_dict.get("item_id"))
            pdf_path = row_dict.get("pdf_path")
            signed_url = create_pdf_signed_url(supabase, pdf_path, 3600)
            supporting_path = row_dict.get("supporting_path")
            supporting_url = create_pdf_signed_url(supabase, supporting_path, 3600)
            paper_url = normalize_url(row_dict.get("url"))

            with st.container():
                st.markdown(f"### [{row_dict['ref_no']}] {row_dict['title']}")
                st.write(f"著者: {row_dict['authors']}")
                st.write(f"雑誌: {row_dict['journal']} ({row_dict['year']})")
                display_doi = normalize_doi(row_dict.get("doi"))
                if display_doi:
                    st.write(f"DOI: {display_doi}")
                missing_metadata_text = format_missing_publication_metadata(row_dict)
                if missing_metadata_text:
                    st.caption(f"不足メタデータ: {missing_metadata_text}")

                if row_dict.get("status"):
                    st.write(f"ステータス: {row_dict['status']}")

                if row_dict.get("notes"):
                    notes_parts = split_structured_notes(row_dict.get("notes"))
                    if notes_parts["base"]:
                        st.write("メモ:")
                        st.write(notes_parts["base"])
                    if notes_parts["reading"]:
                        st.write("読書メモ:")
                        st.write(notes_parts["reading"])
                    if notes_parts["citation"]:
                        st.write("引用予定メモ:")
                        st.write(notes_parts["citation"])

                attachments = []
                if signed_url:
                    attachments.append("PDF")
                if supporting_url:
                    attachments.append("資料")
                if attachments:
                    st.caption("添付: " + " / ".join(attachments))

                tags_list = get_paper_tag_list(tag_map, row_dict)
                if tags_list:
                    st.write("タグ:", ", ".join(tags_list))

                usage_entries = get_paper_usage_entries(citation_usage_map, row_dict)
                if usage_entries:
                    with st.expander(f"Word引用 ({len(usage_entries)}件)"):
                        for entry in usage_entries:
                            heading = entry.get("document_title") or "無題"
                            if entry.get("citation_text"):
                                heading += f" / {entry['citation_text']}"
                            st.markdown(f"**{heading}**")
                            if entry.get("context_text"):
                                st.write(entry["context_text"])
                            details = []
                            if entry.get("reference_number"):
                                details.append(f"参考文献番号: {entry['reference_number']}")
                            if entry.get("locator"):
                                details.append(f"位置: {entry['locator']}")
                            if entry.get("updated_at"):
                                details.append(f"更新: {entry['updated_at']}")
                            if details:
                                st.caption(" / ".join(details))

                action_col1, action_col2, action_col3, action_col4, action_col5 = st.columns(5)

                with action_col1:
                    if st.button("詳細", key=f"detail_{row_dict['id']}", use_container_width=True):
                        st.session_state["detail_selected_paper_id"] = str(row_dict["id"])
                        st.session_state["active_menu"] = "詳細"
                        st.rerun()

                with action_col2:
                    if st.button("引用", key=f"cite_{row_dict['id']}", use_container_width=True):
                        st.code(make_word_citation(row_dict, style="APA"))

                with action_col3:
                    if signed_url:
                        st.link_button("PDF", signed_url, use_container_width=True)

                with action_col4:
                    if supporting_url:
                        st.link_button("資料", supporting_url, use_container_width=True)

                with action_col5:
                    if paper_url:
                        st.link_button("Web", paper_url, use_container_width=True)

                with st.expander("並び順・削除"):
                    order_col1, order_col2, delete_col = st.columns([1, 1, 2])
                    with order_col1:
                        if st.button("上へ", key=f"up_{row_dict['id']}", use_container_width=True):
                            move_paper(
                                supabase,
                                user_id,
                                row_dict["id"],
                                row_dict["display_order"],
                                "up",
                                item_id=item_id,
                            )
                            clear_library_caches()
                            st.rerun()
                    with order_col2:
                        if st.button("下へ", key=f"down_{row_dict['id']}", use_container_width=True):
                            move_paper(
                                supabase,
                                user_id,
                                row_dict["id"],
                                row_dict["display_order"],
                                "down",
                                item_id=item_id,
                            )
                            clear_library_caches()
                            st.rerun()
                    with delete_col:
                        if st.button("削除", key=f"del_{row_dict['id']}", use_container_width=True):
                            delete_result = delete_paper(supabase, user_id, row_dict)
                            clear_library_caches()
                            st.success("削除しました")
                            if delete_result.get("storage_errors"):
                                st.session_state["post_action_warning"] = (
                                    "DBからは削除しましたが、Storageファイル削除に失敗しました: "
                                    + " / ".join(delete_result["storage_errors"])
                                )
                            st.rerun()

                with st.expander("編集"):
                    render_paper_edit_form(
                        row_dict,
                        user_id,
                        collections=collections,
                        collection_label_by_id=collection_label_by_id,
                        collection_id_by_label=collection_id_by_label,
                        key_prefix="list",
                    )

                st.divider()


elif menu == "詳細":
    user_id = get_current_user_id()
    st.header("文献詳細")

    try:
        result = fetch_user_papers(
            supabase,
            user_id,
            columns=(
                "id, item_id, title, authors, journal, year, doi, url, volume, issue, "
                "pages, publisher, item_type, status, notes, pdf_path, "
                "supporting_path, display_order"
            ),
        )
        papers = result.data or []
    except Exception:
        logger.exception("Failed to fetch papers for detail view")
        st.error("文献の取得に失敗しました。")
        papers = []

    if not papers:
        st.write("文献がありません。")
    else:
        try:
            collections_result = fetch_user_collections(supabase, user_id)
            collections = collections_result.data or []
        except Exception:
            logger.exception("Failed to fetch collections")
            collections = []
        collection_label_by_id, collection_id_by_label = build_collection_label_maps(collections)

        keyword = st.text_input("タイトル・著者・DOIで絞り込み", key="detail_keyword").strip()
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            status_filter = st.selectbox(
                "ステータス",
                [""] + READING_STATUSES,
                key="detail_status_filter",
            )
        with filter_col2:
            attachment_filter = st.selectbox(
                "添付",
                ["", "PDFあり", "補足資料あり", "添付あり", "添付なし"],
                key="detail_attachment_filter",
            )
        with filter_col3:
            selected_collection_label = st.selectbox(
                "コレクション",
                ["すべて"] + list(collection_id_by_label.keys()),
                key="detail_collection_filter",
            )

        scoped_papers = papers
        if selected_collection_label != "すべて":
            selected_collection_id = collection_id_by_label[selected_collection_label]
            try:
                scoped_papers = fetch_papers_for_collection(
                    supabase,
                    user_id,
                    selected_collection_id,
                    columns=(
                        "id, item_id, title, authors, journal, year, doi, url, volume, issue, "
                        "pages, publisher, item_type, status, notes, pdf_path, "
                        "supporting_path, display_order"
                    ),
                )
            except Exception:
                logger.exception("Failed to fetch papers for selected collection")
                st.warning("コレクション内の文献取得に失敗しました。全件から絞り込みます。")
                scoped_papers = papers

        filtered_papers = filter_papers(
            scoped_papers,
            keyword=keyword,
            status=status_filter,
            attachment_filter=attachment_filter,
        )

        if not filtered_papers:
            st.write("検索条件に一致する文献はありません。")
        else:
            paper_by_id = {str(paper["id"]): paper for paper in filtered_papers}
            paper_ids = list(paper_by_id.keys())
            if st.session_state.get("detail_selected_paper_id") not in paper_by_id:
                st.session_state["detail_selected_paper_id"] = paper_ids[0]
            current_index = paper_ids.index(st.session_state["detail_selected_paper_id"])

            nav_col1, nav_col2, nav_col3, nav_col4 = st.columns([1, 1, 1, 2])
            with nav_col1:
                if st.button("← 前へ", disabled=current_index == 0, key="detail_prev"):
                    st.session_state["detail_selected_paper_id"] = paper_ids[current_index - 1]
                    st.rerun()
            with nav_col2:
                if st.button(
                    "次へ →",
                    disabled=current_index >= len(paper_ids) - 1,
                    key="detail_next",
                ):
                    st.session_state["detail_selected_paper_id"] = paper_ids[current_index + 1]
                    st.rerun()
            with nav_col3:
                st.caption(f"{current_index + 1} / {len(paper_ids)}")
            with nav_col4:
                if st.button("一覧へ戻る", key="detail_back_to_list"):
                    st.session_state["active_menu"] = "一覧"
                    st.rerun()

            def format_detail_option(paper_id):
                paper = paper_by_id[paper_id]
                title = paper.get("title") or "無題"
                authors = paper.get("authors") or "著者不明"
                year = paper.get("year") or "-"
                doi = normalize_doi(paper.get("doi"))
                suffix = f" / DOI: {doi}" if doi else ""
                return f"{title} / {authors} / {year}{suffix}"

            selected_paper_id = st.selectbox(
                "文献",
                paper_ids,
                format_func=format_detail_option,
                key="detail_selected_paper_id",
            )
            selected_paper = paper_by_id[selected_paper_id]

            tag_map = get_tag_map_for_papers(supabase, [selected_paper])
            citation_usage_map = get_citation_usage_map_for_display(user_id, [selected_paper])

            info_tab, pdf_tab, reading_tab, tags_tab, citation_tab, edit_tab = st.tabs(
                ["概要", "PDF", "読書", "タグ", "引用", "編集"]
            )
            with info_tab:
                render_paper_summary(
                    selected_paper,
                    tag_map=tag_map,
                    citation_usage_map=citation_usage_map,
                )

            with pdf_tab:
                render_paper_pdf_preview(selected_paper, key_prefix="detail")

            with reading_tab:
                render_reading_workflow(selected_paper, user_id, key_prefix="detail_reading")

            with tags_tab:
                render_paper_tag_editor(
                    selected_paper,
                    user_id,
                    tag_map,
                    key_prefix="detail",
                )

            with citation_tab:
                citation_style = st.segmented_control(
                    "引用スタイル",
                    ["APA", "Vancouver", "Nature"],
                    default="APA",
                    key=f"detail_citation_style_{selected_paper['id']}",
                )
                citation_text = make_word_citation(selected_paper, style=citation_style)
                st.code(citation_text)
                citation_file_name = re.sub(
                    r"[^A-Za-z0-9._-]+",
                    "-",
                    selected_paper.get("title") or "citation",
                ).strip("-")
                with st.expander("エクスポート"):
                    export_col1, export_col2, export_col3 = st.columns(3)
                    with export_col1:
                        st.download_button(
                            "テキスト",
                            data=citation_text.encode("utf-8"),
                            file_name=f"{citation_file_name or 'citation'}-{citation_style}.txt",
                            mime="text/plain",
                            key=f"detail_citation_download_{selected_paper['id']}",
                            use_container_width=True,
                        )
                    bibtex_text = make_bibtex_entry(selected_paper)
                    with export_col2:
                        st.download_button(
                            "BibTeX",
                            data=bibtex_text.encode("utf-8"),
                            file_name=f"{citation_file_name or 'citation'}.bib",
                            mime="application/x-bibtex",
                            key=f"detail_bibtex_download_{selected_paper['id']}",
                            use_container_width=True,
                        )
                    ris_text = make_ris_entry(selected_paper)
                    with export_col3:
                        st.download_button(
                            "RIS",
                            data=ris_text.encode("utf-8"),
                            file_name=f"{citation_file_name or 'citation'}.ris",
                            mime="application/x-research-info-systems",
                            key=f"detail_ris_download_{selected_paper['id']}",
                            use_container_width=True,
                        )
                    preview_tab1, preview_tab2 = st.tabs(["BibTeX", "RIS"])
                    with preview_tab1:
                        st.code(bibtex_text, language="bibtex")
                    with preview_tab2:
                        st.code(ris_text)

            with edit_tab:
                render_paper_edit_form(
                    selected_paper,
                    user_id,
                    collections=collections,
                    collection_label_by_id=collection_label_by_id,
                    collection_id_by_label=collection_id_by_label,
                    key_prefix="detail",
                )


elif menu == "PDF読書":
    user_id = get_current_user_id()
    st.header("PDF読書")
    try:
        result = fetch_user_papers(
            supabase,
            user_id,
            columns=(
                "id, item_id, title, authors, journal, year, doi, url, volume, issue, "
                "pages, publisher, item_type, status, notes, pdf_path, supporting_path, display_order"
            ),
        )
        pdf_papers = [paper for paper in (result.data or []) if paper.get("pdf_path")]
    except Exception:
        logger.exception("Failed to fetch papers for PDF reading")
        st.error("PDF付き文献を取得できませんでした。")
        st.stop()

    if not pdf_papers:
        st.write("PDF付き文献はまだありません。一覧または詳細の編集タブからPDFを追加できます。")
    else:
        read_filter_col, sort_col = st.columns([1, 1])
        with read_filter_col:
            reading_filter = st.selectbox(
                "読書ステータス",
                ["すべて"] + READING_STATUSES,
                key="pdf_reading_status_filter",
            )
        with sort_col:
            pdf_sort = st.selectbox(
                "並び替え",
                SORT_OPTIONS,
                key="pdf_reading_sort",
            )
        if reading_filter != "すべて":
            pdf_papers = [
                paper for paper in pdf_papers if (paper.get("status") or "") == reading_filter
            ]
        if pdf_papers:
            pdf_papers = sort_papers_dataframe(
                pd.DataFrame(pdf_papers),
                pdf_sort,
            ).to_dict(orient="records")

        if not pdf_papers:
            st.write("条件に一致するPDF付き文献はありません。")
        else:
            paper_by_id = {str(paper["id"]): paper for paper in pdf_papers}
            paper_ids = list(paper_by_id.keys())
            if st.session_state.get("pdf_reading_selected_paper_id") not in paper_by_id:
                st.session_state["pdf_reading_selected_paper_id"] = paper_ids[0]

            def format_pdf_reading_option(paper_id):
                paper = paper_by_id[paper_id]
                return (
                    f"{paper.get('title') or '無題'} / "
                    f"{paper.get('journal') or '雑誌未設定'} / "
                    f"{paper.get('year') or '-'}"
                )

            selected_pdf_paper_id = st.selectbox(
                "読む文献",
                paper_ids,
                format_func=format_pdf_reading_option,
                key="pdf_reading_selected_paper_id",
            )
            selected_pdf_paper = paper_by_id[selected_pdf_paper_id]
            reader_col, note_col = st.columns([1.7, 1])
            with reader_col:
                st.subheader(selected_pdf_paper.get("title") or "無題")
                render_paper_pdf_preview(selected_pdf_paper, key_prefix="pdf_reading")
            with note_col:
                st.subheader("読書メモ")
                render_reading_workflow(
                    selected_pdf_paper,
                    user_id,
                    key_prefix="pdf_reading_workflow",
                )


elif menu == "インポート":
    user_id = get_current_user_id()
    st.header("インポート")
    existing_result = fetch_user_papers(
        supabase,
        user_id,
        columns=(
            "id, item_id, title, authors, journal, year, doi, url, volume, issue, "
            "pages, publisher, status, notes, pdf_path"
        ),
    )
    existing_records = existing_result.data or []

    import_tab1, import_tab2, import_tab3, import_tab4 = st.tabs(
        ["BibTeX", "RIS", "DOIリスト", "PDF"]
    )
    with import_tab1:
        bibtex_file = st.file_uploader(
            "BibTeXファイル",
            type=["bib", "txt"],
            key="import_bibtex_file",
        )
        bibtex_text = st.text_area(
            "またはBibTeXを貼り付け",
            height=180,
            key="import_bibtex_text",
        )
        source_text = bibtex_text
        if bibtex_file:
            source_text = bibtex_file.getvalue().decode("utf-8", errors="ignore")
        bibtex_candidates = parse_bibtex_entries(source_text)
        render_import_candidates(
            bibtex_candidates,
            existing_records,
            key_prefix="import_bibtex",
        )

    with import_tab2:
        ris_file = st.file_uploader(
            "RISファイル",
            type=["ris", "txt"],
            key="import_ris_file",
        )
        ris_text_input = st.text_area(
            "またはRISを貼り付け",
            height=180,
            key="import_ris_text",
        )
        source_text = ris_text_input
        if ris_file:
            source_text = ris_file.getvalue().decode("utf-8", errors="ignore")
        ris_candidates = parse_ris_entries(source_text)
        render_import_candidates(
            ris_candidates,
            existing_records,
            key_prefix="import_ris",
        )

    with import_tab3:
        doi_text = st.text_area(
            "DOIを1行に1件ずつ入力",
            height=180,
            key="import_doi_text",
        )
        doi_values = [
            extract_doi(line) or normalize_doi(line)
            for line in doi_text.splitlines()
            if (extract_doi(line) or normalize_doi(line))
        ]
        invalid_doi_lines = [
            line.strip()
            for line in doi_text.splitlines()
            if line.strip() and not (extract_doi(line) or normalize_doi(line))
        ]
        if invalid_doi_lines:
            st.warning("DOIとして読めない行があります。")
            st.dataframe(
                pd.DataFrame({"入力行": invalid_doi_lines, "理由": "DOI形式ではありません"}),
                hide_index=True,
                use_container_width=True,
            )
        doi_candidates = []
        if doi_values:
            with st.spinner("Crossrefからメタデータを取得しています..."):
                for doi in doi_values:
                    metadata = fetch_doi(doi)
                    if metadata:
                        doi_candidates.append(
                            {
                                "title": metadata[0],
                                "authors": metadata[1],
                                "journal": metadata[2],
                                "year": metadata[3],
                                "volume": metadata[4],
                                "issue": metadata[5],
                                "pages": metadata[6],
                                "publisher": metadata[7],
                                "doi": doi,
                            }
                        )
                    else:
                        doi_candidates.append(
                            {
                                "doi": doi,
                                "import_error": "Crossrefからメタデータを取得できませんでした",
                            }
                        )
        render_import_candidates(
            doi_candidates,
            existing_records,
            key_prefix="import_doi",
        )

    with import_tab4:
        pdf_files = st.file_uploader(
            "PDFファイル",
            type=["pdf"],
            accept_multiple_files=True,
            key="import_pdf_files",
        )
        pdf_candidates = []
        if pdf_files:
            with st.spinner("PDFからDOIを抽出し、Crossrefでメタデータを取得しています..."):
                for pdf_file in pdf_files:
                    pdf_bytes = pdf_file.getvalue()
                    doi = extract_doi_from_pdf_bytes(pdf_bytes)
                    extracted_title = extract_title_from_pdf_bytes(pdf_bytes)
                    if doi:
                        metadata = fetch_doi(doi)
                        if metadata:
                            pdf_candidates.append(
                                {
                                    "title": metadata[0],
                                    "authors": metadata[1],
                                    "journal": metadata[2],
                                    "year": metadata[3],
                                    "volume": metadata[4],
                                    "issue": metadata[5],
                                    "pages": metadata[6],
                                    "publisher": metadata[7],
                                    "doi": doi,
                                }
                            )
                        else:
                            pdf_candidates.append(
                                {
                                    "title": extracted_title or pdf_file.name,
                                    "doi": doi,
                                    "import_error": "DOIは見つかりましたがCrossref取得に失敗しました",
                                }
                            )
                    else:
                        pdf_candidates.append(
                            {
                                "title": extracted_title or pdf_file.name,
                                "import_error": "PDFからDOIを抽出できませんでした",
                            }
                        )
        render_import_candidates(
            pdf_candidates,
            existing_records,
            key_prefix="import_pdf",
            pdf_files=pdf_files,
        )


elif menu == "タグ検索":
    user_id = get_current_user_id()
    tag = st.text_input("タグ名").strip()

    if st.button("検索"):
        tag_result = (
            supabase.table("tags")
            .select("id")
            .eq("name", tag)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        if not tag_result.data:
            st.write("見つかりません")
        else:
            tag_id = tag_result.data[0]["id"]
            paper_tag_result = (
                supabase.table("paper_tags")
                .select("paper_id")
                .eq("tag_id", tag_id)
                .execute()
            )
            item_tag_result = (
                supabase.table("item_tags")
                .select("item_id")
                .eq("tag_id", str(tag_id))
                .execute()
            )
            reference_ids = {
                str(row["paper_id"]) for row in (paper_tag_result.data or [])
            }
            reference_ids.update(
                str(row["item_id"]) for row in (item_tag_result.data or [])
            )

            if not reference_ids:
                st.write("見つかりません")
            else:
                papers_result = fetch_user_papers(
                    supabase,
                    user_id,
                    columns=(
                        "id, item_id, title, authors, journal, year, doi, url, "
                        "volume, issue, pages, publisher, item_type, status, notes, "
                        "pdf_path, supporting_path, display_order"
                    ),
                )
                papers = [
                    paper
                    for paper in (papers_result.data or [])
                    if str(paper.get("id")) in reference_ids
                    or str(paper.get("item_id")) in reference_ids
                ]

                if not papers:
                    st.write("見つかりません")
                else:
                    tag_map = get_tag_map_for_papers(supabase, papers)
                    citation_usage_map = get_citation_usage_map_for_display(user_id, papers)
                    for paper in papers:
                        with st.container():
                            render_paper_summary(
                                paper,
                                tag_map=tag_map,
                                citation_usage_map=citation_usage_map,
                            )
                            st.divider()


elif menu == "コレクション":
    user_id = get_current_user_id()
    st.header("コレクション")

    try:
        collections_result = fetch_user_collections(supabase, user_id)
        collections = collections_result.data or []
    except Exception:
        logger.exception("Failed to fetch collections")
        st.error("コレクションを取得できませんでした。Supabaseで collection migration を適用してください。")
        st.stop()

    with st.form("new_collection_form"):
        collection_name = st.text_input("新しいコレクション名")
        submitted = st.form_submit_button("作成")
        if submitted:
            try:
                create_collection(supabase, user_id, collection_name)
                clear_library_caches()
                st.success("コレクションを作成しました")
                st.rerun()
            except Exception:
                logger.exception("Failed to create collection")
                st.error("コレクションを作成できませんでした。同じ名前がないか確認してください。")

    if not collections:
        st.write("コレクションはまだありません。")
    else:
        collection_counts = fetch_collection_counts(
            supabase,
            [collection["id"] for collection in collections],
        )
        collection_options = {
            (
                f"{collection.get('name') or '無題'} "
                f"({collection_counts.get(collection['id'], 0)}件)"
            ): collection
            for collection in collections
        }
        selected_label = st.selectbox("表示するコレクション", list(collection_options.keys()))
        selected_collection = collection_options[selected_label]

        with st.expander("コレクションを編集"):
            with st.form(f"edit_collection_{selected_collection['id']}"):
                edited_name = st.text_input(
                    "コレクション名",
                    value=selected_collection.get("name") or "",
                )
                submitted = st.form_submit_button("名前を保存")
                if submitted:
                    try:
                        update_collection(
                            supabase,
                            user_id,
                            selected_collection["id"],
                            edited_name,
                        )
                        clear_library_caches()
                        st.success("コレクション名を更新しました")
                        st.rerun()
                    except Exception:
                        logger.exception("Failed to update collection")
                        st.error("コレクション名を更新できませんでした。")

            st.caption("削除しても論文本体は残ります。コレクションへの所属だけが削除されます。")
            delete_confirm = st.text_input(
                "削除する場合はコレクション名を入力",
                key=f"delete_collection_confirm_{selected_collection['id']}",
            )
            if st.button("コレクションを削除", key=f"delete_collection_{selected_collection['id']}"):
                if delete_confirm != (selected_collection.get("name") or ""):
                    st.error("確認用のコレクション名が一致しません。")
                else:
                    try:
                        delete_collection(supabase, user_id, selected_collection["id"])
                        clear_library_caches()
                        st.success("コレクションを削除しました")
                        st.rerun()
                    except Exception:
                        logger.exception("Failed to delete collection")
                        st.error("コレクションを削除できませんでした。")

        try:
            papers = fetch_papers_for_collection(
                supabase,
                user_id,
                selected_collection["id"],
                columns=(
                    "id, item_id, title, authors, journal, year, doi, url, volume, "
                    "issue, pages, publisher, item_type, status, notes, pdf_path, "
                    "supporting_path, display_order"
                ),
            )
        except Exception:
            logger.exception("Failed to fetch collection papers")
            st.error("このコレクションの文献を取得できませんでした。")
            st.stop()

        collection_keyword = st.text_input(
            "コレクション内検索",
            key=f"collection_search_{selected_collection['id']}",
        )
        collection_sort = st.selectbox(
            "コレクション内並び替え",
            SORT_OPTIONS,
            key=f"collection_sort_{selected_collection['id']}",
        )
        collection_added_oldest_key = (
            f"collection_added_oldest_first_{selected_collection['id']}"
        )
        collection_added_oldest_first = st.session_state.get(
            collection_added_oldest_key,
            False,
        )
        if collection_sort == "追加順":
            current_order_label = "古い順" if collection_added_oldest_first else "新しい順"
            if st.button(
                f"追加順を切替（現在: {current_order_label}）",
                key=f"toggle_collection_added_order_{selected_collection['id']}",
            ):
                st.session_state[collection_added_oldest_key] = (
                    not collection_added_oldest_first
                )
                st.rerun()
        visible_papers = filter_papers(papers, keyword=collection_keyword)
        if visible_papers:
            visible_df = sort_papers_dataframe(
                pd.DataFrame(visible_papers),
                collection_sort,
                added_oldest_first=collection_added_oldest_first,
            )
            visible_papers = visible_df.to_dict(orient="records")

        st.subheader(f"{selected_label} ({len(visible_papers)} / {len(papers)}件)")
        if not papers:
            st.write("このコレクションにはまだ文献がありません。一覧の編集欄から追加できます。")
        elif not visible_papers:
            st.write("検索条件に一致する文献はありません。")
        else:
            safe_collection_name = re.sub(
                r'[\\/:*?"<>|]+',
                "_",
                selected_collection.get("name") or "collection",
            )
            export_columns = {
                "title": "タイトル",
                "authors": "著者",
                "journal": "掲載誌",
                "year": "年",
                "doi": "DOI",
                "url": "URL",
                "volume": "巻",
                "issue": "号",
                "pages": "ページ",
                "publisher": "出版社",
                "status": "ステータス",
                "notes": "メモ",
            }
            export_df = pd.DataFrame(visible_papers)
            export_df = export_df[
                [column for column in export_columns if column in export_df.columns]
            ].rename(columns=export_columns)
            export_col1, export_col2 = st.columns(2)
            with export_col1:
                st.download_button(
                    "表示中の文献をCSV出力",
                    data=export_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{safe_collection_name}_papers.csv",
                    mime="text/csv",
                )
            with export_col2:
                st.download_button(
                    "表示中の文献をWord出力",
                    data=export_to_word_bytes(visible_papers),
                    file_name=f"{safe_collection_name}_references.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )

            tag_map = get_tag_map_for_papers(supabase, visible_papers)
            citation_usage_map = get_citation_usage_map_for_display(user_id, visible_papers)
            for paper in visible_papers:
                with st.container():
                    render_paper_summary(
                        paper,
                        tag_map=tag_map,
                        citation_usage_map=citation_usage_map,
                    )
                    st.divider()


elif menu == "重複確認":
    user_id = get_current_user_id()
    st.header("重複確認")

    result = fetch_user_papers(
        supabase,
        user_id,
        columns=(
            "id, item_id, title, authors, journal, year, doi, url, volume, issue, "
            "pages, publisher, item_type, status, notes, pdf_path, supporting_path"
        ),
    )
    papers = result.data or []
    duplicate_groups = find_duplicate_paper_groups(papers)

    with st.expander("データ品質チェック", expanded=False):
        quality_rows = []
        for paper in papers:
            normalized_authors = normalize_author_list_compat(paper.get("authors"))
            normalized_journal = normalize_journal_title_compat(paper.get("journal"))
            changes = []
            if normalized_authors and normalized_authors != (paper.get("authors") or ""):
                changes.append("著者")
            if normalized_journal and normalized_journal != (paper.get("journal") or ""):
                changes.append("雑誌名")
            if changes:
                quality_rows.append(
                    {
                        "id": paper.get("id"),
                        "タイトル": paper.get("title") or "無題",
                        "変更項目": " / ".join(changes),
                        "現在の著者": paper.get("authors") or "",
                        "正規化著者": normalized_authors,
                        "現在の雑誌": paper.get("journal") or "",
                        "正規化雑誌": normalized_journal,
                    }
                )

        if not quality_rows:
            st.write("著者名・雑誌名の正規化候補はありません。")
        else:
            st.caption("著者名は「姓, 名」形式、雑誌名は既知の略称を正式名へ寄せます。")
            quality_df = pd.DataFrame(quality_rows)
            edited_quality_df = st.data_editor(
                quality_df.assign(適用=False),
                hide_index=True,
                use_container_width=True,
                disabled=[
                    "id",
                    "タイトル",
                    "変更項目",
                    "現在の著者",
                    "正規化著者",
                    "現在の雑誌",
                    "正規化雑誌",
                ],
                key="quality_normalization_editor",
            )
            if st.button("選択した正規化を適用", key="apply_quality_normalization"):
                updated_count = 0
                paper_by_id = {str(paper.get("id")): paper for paper in papers}
                for row in edited_quality_df.to_dict(orient="records"):
                    if not row.get("適用"):
                        continue
                    paper = paper_by_id.get(str(row.get("id")))
                    if not paper:
                        continue
                    update_existing_paper_from_import(
                        paper,
                        {
                            "title": paper.get("title") or "",
                            "authors": row.get("正規化著者") or paper.get("authors") or "",
                            "journal": row.get("正規化雑誌") or paper.get("journal") or "",
                            "year": paper.get("year") or 0,
                            "doi": normalize_doi(paper.get("doi")),
                            "url": normalize_url(paper.get("url")) or "",
                            "volume": paper.get("volume") or "",
                            "issue": paper.get("issue") or "",
                            "pages": paper.get("pages") or "",
                            "publisher": paper.get("publisher") or "",
                        },
                        user_id,
                    )
                    updated_count += 1
                clear_library_caches()
                st.success(f"{updated_count}件を正規化しました。")
                st.rerun()

    with st.expander("統合履歴・復元", expanded=False):
        try:
            merge_backups = fetch_duplicate_merge_backups(supabase, user_id, limit=50)
        except Exception:
            logger.exception("Failed to fetch duplicate merge backups")
            st.warning("統合履歴を取得できませんでした。")
            merge_backups = []

        if not merge_backups:
            st.write("統合履歴はまだありません。")
        else:
            history_keyword = st.text_input(
                "統合履歴を検索",
                key="duplicate_merge_history_search",
            ).strip().casefold()
            if history_keyword:
                merge_backups = [
                    backup
                    for backup in merge_backups
                    if history_keyword
                    in " ".join(
                        [
                            str((backup.get("keeper_snapshot") or {}).get("title") or ""),
                            str((backup.get("duplicate_snapshot") or {}).get("title") or ""),
                            str(backup.get("merge_group_id") or ""),
                            str(backup.get("created_at") or ""),
                        ]
                    ).casefold()
                ]
            st.caption(
                "ここでは統合時点のスナップショットを確認できます。"
                "復元は、残す文献のメタデータを統合前の状態に戻します。"
                "統合元として削除された文献そのものも、スナップショットから再作成できます。"
            )
            history_rows = []
            for backup in merge_backups:
                keeper_snapshot = backup.get("keeper_snapshot") or {}
                duplicate_snapshot = backup.get("duplicate_snapshot") or {}
                history_rows.append(
                    {
                        "日時": backup.get("created_at"),
                        "残した文献": keeper_snapshot.get("title") or "無題",
                        "統合元": duplicate_snapshot.get("title") or "無題",
                        "残したID": backup.get("keeper_paper_id") or backup.get("keeper_item_id"),
                        "統合元ID": backup.get("duplicate_paper_id") or backup.get("duplicate_item_id"),
                    }
                )
            st.dataframe(pd.DataFrame(history_rows), use_container_width=True)

            for backup_index, backup in enumerate(merge_backups, start=1):
                keeper_snapshot = backup.get("keeper_snapshot") or {}
                duplicate_snapshot = backup.get("duplicate_snapshot") or {}
                with st.expander(
                    f"{backup_index}. {keeper_snapshot.get('title') or '無題'} ← "
                    f"{duplicate_snapshot.get('title') or '無題'}"
                ):
                    snapshot_col1, snapshot_col2 = st.columns(2)
                    with snapshot_col1:
                        st.write("残す文献の統合前スナップショット")
                        st.json(keeper_snapshot, expanded=False)
                    with snapshot_col2:
                        st.write("統合元のスナップショット")
                        st.json(duplicate_snapshot, expanded=False)

                    restore_confirm = st.text_input(
                        "残す文献のメタデータを戻す場合は「復元」と入力",
                        key=f"restore_merge_backup_confirm_{backup['id']}",
                    )
                    if st.button(
                        "残す文献を統合前メタデータに復元",
                        key=f"restore_merge_backup_{backup['id']}",
                    ):
                        if restore_confirm != "復元":
                            st.error("確認文字列が一致しません。")
                        else:
                            try:
                                restore_result = restore_keeper_from_merge_backup(
                                    supabase,
                                    user_id,
                                    backup,
                                )
                            except Exception as error:
                                logger.exception("Failed to restore duplicate merge backup")
                                st.error(f"復元に失敗しました: {error}")
                            else:
                                clear_library_caches()
                                st.success(
                                    "復元しました: "
                                    f"{restore_result['restored_table']} / "
                                    f"{restore_result['restored_id']}"
                                )
                                st.rerun()
                    duplicate_restore_confirm = st.text_input(
                        "統合元文献を再作成する場合は「再作成」と入力",
                        key=f"restore_duplicate_backup_confirm_{backup['id']}",
                    )
                    if st.button(
                        "統合元文献をスナップショットから再作成",
                        key=f"restore_duplicate_backup_{backup['id']}",
                    ):
                        if duplicate_restore_confirm != "再作成":
                            st.error("確認文字列が一致しません。")
                        else:
                            try:
                                restore_result = restore_duplicate_from_merge_backup_compat(
                                    supabase,
                                    user_id,
                                    backup,
                                )
                            except Exception as error:
                                logger.exception("Failed to restore duplicate from backup")
                                st.error(f"統合元の再作成に失敗しました: {error}")
                            else:
                                clear_library_caches()
                                st.success(
                                    "統合元を再作成しました: "
                                    f"{restore_result['restored_table']} / "
                                    f"{restore_result['restored_id']}"
                                )
                                st.rerun()

    if not duplicate_groups:
        st.write("重複候補は見つかりませんでした。")
    else:
        st.write(f"{len(duplicate_groups)}件の重複候補があります。")
        st.caption(
            "統合すると、タグ・コレクション・Word引用参照を残す文献へ移し、"
            "統合元のスナップショットを duplicate_merge_backups に保存します。"
        )

        for index, group in enumerate(duplicate_groups, start=1):
            reason = group["reason"]
            value = group["value"]
            group_papers = group["papers"]
            with st.expander(f"{index}. {reason}: {value} ({len(group_papers)}件)"):
                paper_by_label = {
                    format_duplicate_option_label(paper): paper
                    for paper in group_papers
                }
                for paper in group_papers:
                    st.markdown(f"**{paper.get('title') or '無題'}**")
                    st.write(f"ID: {paper.get('id')}")
                    if paper.get("authors"):
                        st.write(f"著者: {paper.get('authors')}")
                    if paper.get("journal") or paper.get("year"):
                        st.write(f"雑誌・年: {paper.get('journal') or ''} ({paper.get('year') or '-'})")
                    display_doi = normalize_doi(paper.get("doi"))
                    if display_doi:
                        st.write(f"DOI: {display_doi}")
                    if paper.get("status"):
                        st.write(f"ステータス: {paper.get('status')}")
                    if paper.get("notes"):
                        st.write("メモ:")
                        st.write(paper["notes"])
                    attachments = []
                    if paper.get("pdf_path"):
                        attachments.append("PDF")
                    if paper.get("supporting_path"):
                        attachments.append("補足資料")
                    if attachments:
                        st.caption("添付: " + " / ".join(attachments))
                    st.divider()

                st.subheader("統合")
                keeper_label = st.radio(
                    "残す文献",
                    list(paper_by_label.keys()),
                    key=f"merge_keeper_{index}",
                )
                merge_labels = st.multiselect(
                    "統合して削除する文献",
                    [
                        label
                        for label in paper_by_label
                        if label != keeper_label
                    ],
                    key=f"merge_targets_{index}",
                )
                merge_confirm = st.text_input(
                    "統合する場合は「統合」と入力",
                    key=f"merge_confirm_{index}",
                )
                if merge_labels:
                    keeper_preview = paper_by_label[keeper_label]
                    preview_rows = []
                    merge_field_choices = {}
                    for label in merge_labels:
                        duplicate_preview = paper_by_label[label]
                        for field, label_text in (
                            ("title", "タイトル"),
                            ("authors", "著者"),
                            ("journal", "雑誌"),
                            ("year", "年"),
                            ("doi", "DOI"),
                            ("status", "ステータス"),
                            ("pdf_path", "PDF"),
                            ("supporting_path", "補足資料"),
                            ("notes", "メモ"),
                        ):
                            keep_value = keeper_preview.get(field) or ""
                            duplicate_value = duplicate_preview.get(field) or ""
                            if field == "doi":
                                keep_value = normalize_doi(keep_value)
                                duplicate_value = normalize_doi(duplicate_value)
                            if keep_value or duplicate_value:
                                action = "保持"
                                if not keep_value and duplicate_value:
                                    action = "統合元から補完"
                                elif keep_value and duplicate_value and keep_value != duplicate_value:
                                    action = "残す文献を優先"
                                preview_rows.append(
                                    {
                                        "統合元": duplicate_preview.get("title") or "無題",
                                        "項目": label_text,
                                        "残す文献": keep_value,
                                        "統合元の値": duplicate_value,
                                        "処理": action,
                                    }
                                )
                    if preview_rows:
                        st.caption("統合プレビュー")
                        st.dataframe(pd.DataFrame(preview_rows), use_container_width=True)
                        with st.expander("フィールドごとに残す値を選ぶ"):
                            st.caption("添付ファイル以外の項目は、統合元の値を残す文献へ採用できます。")
                            for merge_label in merge_labels:
                                duplicate_preview = paper_by_label[merge_label]
                                st.markdown(f"**統合元: {duplicate_preview.get('title') or '無題'}**")
                                field_choice_cols = st.columns(2)
                                for field_index, (field, label_text) in enumerate(
                                    (
                                        ("title", "タイトル"),
                                        ("authors", "著者"),
                                        ("journal", "雑誌"),
                                        ("year", "年"),
                                        ("doi", "DOI"),
                                        ("url", "URL"),
                                        ("volume", "巻"),
                                        ("issue", "号"),
                                        ("pages", "ページ"),
                                        ("publisher", "出版社"),
                                        ("status", "ステータス"),
                                    )
                                ):
                                    keep_value = keeper_preview.get(field) or ""
                                    duplicate_value = duplicate_preview.get(field) or ""
                                    if field == "doi":
                                        keep_value = normalize_doi(keep_value)
                                        duplicate_value = normalize_doi(duplicate_value)
                                    if not duplicate_value or keep_value == duplicate_value:
                                        continue
                                    with field_choice_cols[field_index % 2]:
                                        choice = st.selectbox(
                                            label_text,
                                            ["残す文献の値", "統合元の値"],
                                            key=f"merge_field_choice_{index}_{merge_label}_{field}",
                                            help=f"残す: {keep_value or '(空)'} / 統合元: {duplicate_value}",
                                        )
                                    merge_field_choices.setdefault(merge_label, {})[field] = (
                                        "duplicate" if choice == "統合元の値" else "keeper"
                                    )

                if st.button("選択した文献を統合", key=f"merge_button_{index}"):
                    if merge_confirm != "統合":
                        st.error("確認文字列が一致しません。")
                    elif not merge_labels:
                        st.error("統合する文献を選んでください。")
                    else:
                        try:
                            keeper = paper_by_label[keeper_label]
                            citation_updates = 0
                            backup_ids = []
                            merge_group_id = str(uuid.uuid4())
                            for label in merge_labels:
                                merge_result = merge_duplicate_paper(
                                    supabase,
                                    user_id,
                                    keeper,
                                    paper_by_label[label],
                                    merge_group_id=merge_group_id,
                                    preferred_fields=merge_field_choices.get(label),
                                )
                                citation_updates += merge_result["citation_updates"]
                                backup_ids.extend(merge_result.get("backup_ids", []))
                                keeper.update(merge_result["updated_fields"])
                            clear_library_caches()
                            st.success(
                                f"統合しました。Word引用参照の更新: {citation_updates}件 / "
                                f"バックアップ: {len(backup_ids)}件"
                            )
                            st.rerun()
                        except ValueError as error:
                            st.error(str(error))
                        except Exception as error:
                            logger.exception("Failed to merge duplicate papers")
                            st.error(f"統合に失敗しました: {error}")

                st.subheader("削除")
                delete_labels = st.multiselect(
                    "削除する文献",
                    list(paper_by_label.keys()),
                    key=f"delete_targets_{index}",
                )
                delete_confirm = st.text_input(
                    "削除する場合は「削除」と入力",
                    key=f"delete_confirm_{index}",
                )
                if st.button("選択した文献を削除", key=f"delete_button_{index}"):
                    if delete_confirm != "削除":
                        st.error("確認文字列が一致しません。")
                    elif not delete_labels:
                        st.error("削除する文献を選んでください。")
                    elif len(delete_labels) >= len(group_papers):
                        st.error("候補グループ内の全件削除はできません。少なくとも1件は残してください。")
                    else:
                        try:
                            blocked = []
                            for label in delete_labels:
                                paper = paper_by_label[label]
                                if paper_has_document_citation_refs(
                                    supabase,
                                    user_id,
                                    [
                                        value
                                        for value in (paper.get("id"), paper.get("item_id"))
                                        if value is not None
                                    ],
                                ):
                                    blocked.append(label)

                            if blocked:
                                st.error(
                                    "Word引用で使われている文献は削除できません。"
                                    " 統合を使って参照先を移してください: "
                                    + ", ".join(blocked)
                                )
                            else:
                                storage_errors = []
                                for label in delete_labels:
                                    delete_result = delete_paper(
                                        supabase,
                                        user_id,
                                        paper_by_label[label],
                                    )
                                    storage_errors.extend(
                                        delete_result.get("storage_errors", [])
                                    )
                                clear_library_caches()
                                st.success("選択した文献を削除しました。")
                                if storage_errors:
                                    st.session_state["post_action_warning"] = (
                                        "DBからは削除しましたが、Storageファイル削除に失敗しました: "
                                        + " / ".join(storage_errors)
                                    )
                                st.rerun()
                        except Exception as error:
                            logger.exception("Failed to delete duplicate papers")
                            st.error(f"削除に失敗しました: {error}")


elif menu == "文書引用":
    user_id = get_current_user_id()
    st.header("Word文書の引用")

    try:
        documents_result = fetch_user_documents(supabase, user_id)
        documents = documents_result.data or []
    except Exception:
        logger.exception("Failed to fetch documents")
        st.error(
            "文書引用を取得できませんでした。"
            " Supabaseで documents / document_citations / paper_items_view の migration を確認してください。"
        )
        st.stop()

    if not documents:
        st.write("同期済みのWord文書はまだありません。Wordアドインで引用を挿入・更新すると表示されます。")
    else:
        document_options = {
            f"{doc.get('title') or '無題'} / {doc.get('citation_style') or '-'} / {doc.get('updated_at') or ''}": doc
            for doc in documents
        }
        selected_label = st.selectbox("文書", list(document_options.keys()))
        selected_document = document_options[selected_label]
        selected_document_title = selected_document.get("title") or "無題"

        st.write(f"文書名: {selected_document_title}")
        st.write(f"引用スタイル: {selected_document.get('citation_style')}")
        if selected_document.get("locale"):
            st.write(f"ロケール: {selected_document.get('locale')}")
        if selected_document.get("updated_at"):
            st.caption(f"最終同期: {selected_document['updated_at']}")

        with st.expander("この同期文書を削除"):
            st.caption(
                "アプリ側に保存されたこのWord文書の同期記録と引用一覧を削除します。"
                "Word本文やWordファイル自体は削除されません。"
            )
            confirm_title = st.text_input(
                "削除するには文書名を入力",
                key=f"delete_document_confirm_{selected_document['id']}",
            )
            if st.button(
                "同期文書を削除",
                key=f"delete_document_{selected_document['id']}",
                disabled=confirm_title != selected_document_title,
            ):
                try:
                    delete_user_document(supabase, user_id, selected_document["id"])
                    st.success("同期文書を削除しました。")
                    st.rerun()
                except Exception as error:
                    logger.exception("Failed to delete document")
                    st.error(f"削除に失敗しました: {error}")

        try:
            citations_result = fetch_document_citations(supabase, selected_document["id"])
            citations = citations_result.data or []
        except Exception:
            logger.exception("Failed to fetch document citations")
            st.error("この文書の引用一覧を取得できませんでした。")
            st.stop()

        if not citations:
            st.write("この文書には同期済みの引用がありません。")
        else:
            citation_paper_ids = []
            for citation in citations:
                for item in citation.get("citation_items") or []:
                    if isinstance(item, dict) and item.get("paperId"):
                        citation_paper_ids.append(str(item["paperId"]))
            all_citation_paper_ids = list(citation_paper_ids)
            citation_paper_ids = list(dict.fromkeys(citation_paper_ids))
            paper_map = {}
            if citation_paper_ids:
                try:
                    paper_result = fetch_user_papers_by_ids(
                        supabase,
                        user_id,
                        citation_paper_ids,
                        columns=(
                            "id, item_id, title, authors, journal, year, doi, volume, "
                            "issue, pages, publisher"
                        ),
                    )
                    paper_map = {
                        str(paper.get("id")): paper
                        for paper in (paper_result.data or [])
                        if paper.get("id")
                    }
                except Exception:
                    logger.exception("Failed to fetch citation papers")
                    st.warning("引用に使われた文献情報の一部を取得できませんでした。")

            citation_keyword = st.text_input(
                "引用文・文献を検索",
                key=f"document_citation_search_{selected_document['id']}",
            )
            visible_citations = filter_document_citations(citations, paper_map, citation_keyword)
            context_count = sum(1 for citation in citations if citation.get("context_text"))
            missing_context_count = len(citations) - context_count
            repeated_paper_count = sum(
                1
                for count in pd.Series(all_citation_paper_ids).value_counts().tolist()
                if count > 1
            ) if all_citation_paper_ids else 0
            metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
            metric_col1.metric("引用", len(citations))
            metric_col2.metric("引用文あり", context_count)
            metric_col3.metric("未同期", missing_context_count)
            metric_col4.metric("複数回引用", repeated_paper_count)

            export_rows = build_document_citation_export_rows(visible_citations, paper_map)
            if export_rows:
                export_df = pd.DataFrame(export_rows)
                st.download_button(
                    "表示中の引用をCSV出力",
                    data=export_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{selected_document_title}_citations.csv",
                    mime="text/csv",
                )

            st.subheader(f"引用一覧 ({len(visible_citations)}件)")
            if not visible_citations:
                st.write("検索条件に一致する引用はありません。")
            for citation in visible_citations:
                with st.container():
                    rendered_text = citation.get("rendered_text") or "引用"
                    context_text = citation.get("context_text") or ""
                    sort_order = citation.get("sort_order") or "-"
                    st.markdown(f"**{sort_order}. {rendered_text}**")
                    if context_text:
                        st.write(f"引用に使った文: {context_text}")
                    else:
                        st.caption("引用に使った文はまだ同期されていません。Wordアドインで参考文献を更新すると反映されます。")

                    items = citation.get("citation_items") or []
                    if items:
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            paper = paper_map.get(str(item.get("paperId") or ""))
                            if paper:
                                details = [paper.get("title") or "無題"]
                                if paper.get("authors"):
                                    details.append(str(paper["authors"]))
                                if paper.get("year"):
                                    details.append(str(paper["year"]))
                                if paper.get("journal"):
                                    details.append(str(paper["journal"]))
                            else:
                                details = ["文献情報を取得できませんでした"]

                            reference_number = item.get("referenceNumber")
                            locator = item.get("locator")
                            if reference_number:
                                details.append(f"参考文献番号: {reference_number}")
                            if locator:
                                details.append(f"位置: {locator}")
                            st.write("- " + " / ".join(details))
                    else:
                        st.caption("文献アイテムなし")

                    if citation.get("updated_at"):
                        st.caption(f"更新: {citation['updated_at']}")
                    with st.expander("引用行を編集・削除"):
                        edited_sort_order = st.number_input(
                            "引用順",
                            min_value=1,
                            value=int(citation.get("sort_order") or 1),
                            key=f"document_citation_sort_{citation['id']}",
                        )
                        edited_rendered_text = st.text_input(
                            "表示テキスト",
                            value=citation.get("rendered_text") or "",
                            key=f"document_citation_rendered_{citation['id']}",
                        )
                        edited_context_text = st.text_area(
                            "引用に使った文",
                            value=citation.get("context_text") or "",
                            height=100,
                            key=f"document_citation_context_{citation['id']}",
                        )
                        edit_col1, edit_col2 = st.columns(2)
                        with edit_col1:
                            if st.button(
                                "引用行を保存",
                                key=f"save_document_citation_{citation['id']}",
                                use_container_width=True,
                            ):
                                update_document_citation_compat(
                                    supabase,
                                    user_id,
                                    citation["id"],
                                    rendered_text=edited_rendered_text,
                                    context_text=edited_context_text,
                                    sort_order=edited_sort_order,
                                )
                                st.success("引用行を更新しました。")
                                st.rerun()
                        with edit_col2:
                            delete_confirm = st.text_input(
                                "削除する場合は「削除」と入力",
                                key=f"delete_document_citation_confirm_{citation['id']}",
                            )
                            if st.button(
                                "この引用行を削除",
                                key=f"delete_document_citation_{citation['id']}",
                                disabled=delete_confirm != "削除",
                                use_container_width=True,
                            ):
                                delete_document_citation_compat(supabase, citation["id"])
                                st.success("アプリ側の引用行を削除しました。Word本文は削除されません。")
                                st.rerun()
                    st.divider()
