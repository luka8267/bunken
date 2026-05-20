import ipaddress
import logging
import re
import socket
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
    export_to_word_bytes,
    fetch_collection_counts,
    fetch_document_citations,
    fetch_paper_collection_ids,
    fetch_papers_for_collection,
    find_existing_user_paper_by_doi,
    fetch_user_papers,
    fetch_user_papers_by_ids,
    fetch_user_collections,
    fetch_user_documents,
    filter_document_citations,
    filter_papers,
    find_duplicate_paper_groups,
    get_document_citation_usage_map,
    get_next_display_order,
    get_tag_map_for_papers,
    make_bibtex_entry,
    make_word_citation,
    merge_duplicate_paper,
    move_paper,
    normalize_doi,
    normalize_title_for_match,
    paper_has_document_citation_refs,
    replace_tags_for_paper,
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

supabase: Client = build_supabase_client(SUPABASE_URL, SUPABASE_KEY)
logger = logging.getLogger(__name__)


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
    if paper.get("doi"):
        st.write(f"DOI: {paper.get('doi')}")
    if paper.get("status"):
        st.write(f"ステータス: {paper.get('status')}")
    if paper.get("notes"):
        st.write("メモ:")
        st.write(paper["notes"])

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
            st.success("タグを更新しました")
            st.rerun()
        except Exception:
            logger.exception("Failed to update paper tags")
            st.error("タグの更新に失敗しました。入力内容とログを確認してください。")


def render_paper_pdf_preview(paper, key_prefix="paper"):
    signed_url = create_pdf_signed_url(supabase, paper.get("pdf_path"), 3600)
    if not signed_url:
        st.caption("PDFは添付されていません。")
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        st.link_button("PDFを開く", signed_url)
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
            )

    st.caption("Chromeのブロックを避けるため、アプリ内PDF埋め込みは無効にしています。")


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


def has_missing_publication_metadata(paper):
    return any(not paper.get(field) for field in ("volume", "issue", "pages", "publisher"))


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
MENU_OPTIONS = ["追加", "検索", "一覧", "詳細", "タグ検索", "コレクション", "重複確認", "文書引用"]
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
    result = fetch_user_papers(supabase, user_id)
    df = pd.DataFrame(result.data or [])

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

    st.header("📚 論文一覧")

    if not df.empty:
        word_bytes = export_to_word_bytes(df.to_dict(orient="records"))
        st.download_button(
            "📄 Word出力",
            data=word_bytes,
            file_name="references.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    if df.empty:
        st.write("データがありません")
    else:
        records = df.to_dict(orient="records")
        tag_map = get_tag_map_for_papers(supabase, records)
        citation_usage_map = get_citation_usage_map_for_display(user_id, records)
        missing_doi_records = [
            record for record in records if not normalize_doi(record.get("doi"))
        ]
        with st.expander(f"DOI一括取得（未入力: {len(missing_doi_records)}件）"):
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
                        st.success(
                            f"DOI候補を適用しました: 更新 {updated_count}件 / スキップ {skipped_count}件"
                        )
                        st.rerun()
            elif missing_doi_records:
                st.write("候補検索を実行してください。")
            else:
                st.write("DOI未入力の文献はありません。")
        doi_metadata_records = [
            record
            for record in records
            if normalize_doi(record.get("doi"))
            and clean_optional_id(record.get("item_id"))
            and has_missing_publication_metadata(record)
        ]
        with st.expander(f"DOIメタデータ補完（不足: {len(doi_metadata_records)}件）"):
            st.caption(
                "既にDOIがある文献について、Crossrefから巻・号・ページ・出版社を取得します。"
                "既に入力済みの値は上書きしません。"
            )
            if st.button("不足メタデータ候補を検索", key="preview_doi_metadata_candidates"):
                with st.spinner("CrossrefでDOIメタデータを取得しています..."):
                    st.session_state["doi_metadata_candidates"] = build_existing_doi_metadata_candidates(
                        doi_metadata_records
                    )

            metadata_candidates = st.session_state.get("doi_metadata_candidates", [])
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
                        st.success(f"DOIメタデータを補完しました: {updated_count}件")
                        st.rerun()
            elif doi_metadata_records:
                st.write("候補検索を実行してください。")
            else:
                st.write("DOIメタデータが不足している正規化文献はありません。")
        try:
            collections_result = fetch_user_collections(supabase, user_id)
            collections = collections_result.data or []
        except Exception:
            logger.exception("Failed to fetch collections")
            collections = []
        collection_label_by_id, collection_id_by_label = build_collection_label_maps(collections)

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
                if row_dict.get("doi"):
                    st.write(f"DOI: {row_dict['doi']}")

                if row_dict.get("status"):
                    st.write(f"ステータス: {row_dict['status']}")

                if row_dict.get("notes"):
                    st.write("メモ:")
                    st.write(row_dict["notes"])

                if paper_url:
                    st.link_button("Webページ", paper_url)

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

                col1, col2, col3, col4, col5, col6, col7, col8 = st.columns(8)

                with col1:
                    if signed_url:
                        st.link_button("📄 PDF", signed_url)

                with col2:
                    if supporting_url:
                        st.link_button("資料", supporting_url)

                with col3:
                    if signed_url:
                        st.link_button("👀 開く", signed_url)

                with col4:
                    if st.button("🗑 削除", key=f"del_{row_dict['id']}"):
                        delete_result = delete_paper(supabase, user_id, row_dict)
                        st.success("削除しました")
                        if delete_result.get("storage_errors"):
                            st.session_state["post_action_warning"] = (
                                "DBからは削除しましたが、Storageファイル削除に失敗しました: "
                                + " / ".join(delete_result["storage_errors"])
                            )
                        st.rerun()

                with col5:
                    if st.button("📚 引用", key=f"cite_{row_dict['id']}"):
                        st.code(make_word_citation(row_dict, style="APA"))

                with col6:
                    if st.button("詳細", key=f"detail_{row_dict['id']}"):
                        st.session_state["detail_selected_paper_id"] = str(row_dict["id"])
                        st.session_state["active_menu"] = "詳細"
                        st.rerun()

                with col7:
                    if st.button("⬆", key=f"up_{row_dict['id']}"):
                        move_paper(
                            supabase,
                            user_id,
                            row_dict["id"],
                            row_dict["display_order"],
                            "up",
                            item_id=item_id,
                        )
                        st.rerun()

                with col8:
                    if st.button("⬇", key=f"down_{row_dict['id']}"):
                        move_paper(
                            supabase,
                            user_id,
                            row_dict["id"],
                            row_dict["display_order"],
                            "down",
                            item_id=item_id,
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

            render_paper_summary(
                selected_paper,
                tag_map=tag_map,
                citation_usage_map=citation_usage_map,
            )

            st.subheader("PDF")
            render_paper_pdf_preview(selected_paper, key_prefix="detail")

            st.subheader("タグ")
            render_paper_tag_editor(
                selected_paper,
                user_id,
                tag_map,
                key_prefix="detail",
            )

            st.subheader("参考文献")
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
            st.download_button(
                "参考文献をダウンロード",
                data=citation_text.encode("utf-8"),
                file_name=f"{citation_file_name or 'citation'}-{citation_style}.txt",
                mime="text/plain",
                key=f"detail_citation_download_{selected_paper['id']}",
            )
            bibtex_text = make_bibtex_entry(selected_paper)
            with st.expander("BibTeX"):
                st.code(bibtex_text, language="bibtex")
                st.download_button(
                    "BibTeXをダウンロード",
                    data=bibtex_text.encode("utf-8"),
                    file_name=f"{citation_file_name or 'citation'}.bib",
                    mime="application/x-bibtex",
                    key=f"detail_bibtex_download_{selected_paper['id']}",
                )

            st.subheader("編集")
            render_paper_edit_form(
                selected_paper,
                user_id,
                collections=collections,
                collection_label_by_id=collection_label_by_id,
                collection_id_by_label=collection_id_by_label,
                key_prefix="detail",
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

    if not duplicate_groups:
        st.write("重複候補は見つかりませんでした。")
    else:
        st.write(f"{len(duplicate_groups)}件の重複候補があります。")
        st.caption("この画面は確認専用です。ここから文献は削除されません。")

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
                    if paper.get("doi"):
                        st.write(f"DOI: {paper.get('doi')}")
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
                if st.button("選択した文献を統合", key=f"merge_button_{index}"):
                    if merge_confirm != "統合":
                        st.error("確認文字列が一致しません。")
                    elif not merge_labels:
                        st.error("統合する文献を選んでください。")
                    else:
                        try:
                            keeper = paper_by_label[keeper_label]
                            citation_updates = 0
                            for label in merge_labels:
                                merge_result = merge_duplicate_paper(
                                    supabase,
                                    user_id,
                                    keeper,
                                    paper_by_label[label],
                                )
                                citation_updates += merge_result["citation_updates"]
                                keeper.update(merge_result["updated_fields"])
                            st.success(
                                f"統合しました。Word引用参照の更新: {citation_updates}件"
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
            metric_col1, metric_col2, metric_col3 = st.columns(3)
            metric_col1.metric("引用", len(citations))
            metric_col2.metric("引用文あり", context_count)
            metric_col3.metric("未同期", missing_context_count)

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
                    st.divider()
