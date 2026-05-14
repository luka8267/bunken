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
    create_collection,
    create_pdf_signed_url,
    delete_collection,
    delete_paper,
    delete_pdf_from_storage,
    export_to_word_bytes,
    fetch_collection_counts,
    fetch_document_citations,
    fetch_paper_collection_ids,
    fetch_papers_for_collection,
    fetch_user_papers,
    fetch_user_papers_by_ids,
    fetch_user_collections,
    fetch_user_documents,
    filter_papers,
    find_duplicate_paper_groups,
    get_tag_map_for_papers,
    make_word_citation,
    move_paper,
    normalize_doi,
    save_tags_for_paper,
    search_user_papers,
    set_paper_collections,
    sort_papers_dataframe,
    update_collection,
    update_paper_details,
    update_paper_files,
    upload_pdf_to_storage,
    upload_supporting_file_to_storage,
)

DOI_FORM_FIELDS = ("title", "authors", "journal", "year")
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)
URL_FORM_FIELDS = ("title", "authors", "journal", "year", "doi")
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

    data = response.json().get("message", {})
    title = data["title"][0] if data.get("title") else ""
    authors = ", ".join(author.get("family", "") for author in data.get("author", []))
    journal = data["container-title"][0] if data.get("container-title") else ""

    issued = data.get("issued", {}).get("date-parts", [])
    year = issued[0][0] if issued and issued[0] else 0

    return title, authors, journal, year


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

    if not any([title, authors, journal, year, doi]):
        return None

    return title, authors, journal, year, doi


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
menu = st.sidebar.selectbox(
    "メニュー",
    ["追加", "検索", "一覧", "タグ検索", "コレクション", "重複確認", "文書引用"],
)


if menu == "追加":
    user_id = get_current_user_id()
    st.header("文献追加")

    title = st.text_input("タイトル", value=st.session_state.get("title", ""))
    authors = st.text_input("著者", value=st.session_state.get("authors", ""))
    journal = st.text_input("雑誌", value=st.session_state.get("journal", ""))
    year = st.number_input("年", value=int(st.session_state.get("year", 2024)), step=1)
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
            existing = (
                supabase.table("papers")
                .select("id, title")
                .eq("user_id", user_id)
                .eq("doi", normalized_doi)
                .limit(1)
                .execute()
            )

            if existing.data:
                st.warning("このDOIの文献はすでに登録されています。")
                st.stop()

        try:
            pdf_path = upload_pdf_to_storage(supabase, pdf_file, user_id) if pdf_file else None
            supporting_path = (
                upload_supporting_file_to_storage(supabase, supporting_file, user_id)
                if supporting_file
                else None
            )

            max_result = (
                supabase.table("papers")
                .select("display_order")
                .eq("user_id", user_id)
                .order("display_order", desc=True)
                .limit(1)
                .execute()
            )
            current_max = max_result.data[0]["display_order"] if max_result.data else 0
            next_order = (current_max or 0) + 1

            insert_result = (
                supabase.table("papers")
                .insert(
                    {
                        "title": title,
                        "authors": authors,
                        "journal": journal,
                        "year": int(year),
                        "doi": normalized_doi or None,
                        "url": normalized_url or None,
                        "pdf_path": pdf_path,
                        "supporting_path": supporting_path,
                        "user_id": user_id,
                        "display_order": next_order,
                        "status": status,
                        "notes": notes,
                    }
                )
                .execute()
            )

            paper_id = insert_result.data[0]["id"]
            save_tags_for_paper(supabase, user_id, paper_id, tags)
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
                "id, title, authors, journal, year, doi, status, notes, "
                "pdf_path, supporting_path"
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
            for paper in papers:
                st.write(
                    (
                        paper["id"],
                        paper["title"],
                        paper.get("authors"),
                        paper.get("year"),
                        paper.get("status"),
                    )
                )


elif menu == "一覧":
    user_id = get_current_user_id()
    result = fetch_user_papers(supabase, user_id)
    df = pd.DataFrame(result.data or [])

    sort_option = st.selectbox("並び替え", SORT_OPTIONS)
    df = sort_papers_dataframe(df, sort_option)

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
        tag_map = get_tag_map_for_papers(supabase, df["id"].tolist())
        try:
            collections_result = fetch_user_collections(supabase, user_id)
            collections = collections_result.data or []
        except Exception:
            logger.exception("Failed to fetch collections")
            collections = []
        collection_label_by_id = {
            collection["id"]: f"{collection.get('name') or '無題'} [{collection['id'][:8]}]"
            for collection in collections
        }
        collection_id_by_label = {
            collection_label_by_id[collection["id"]]: collection["id"]
            for collection in collections
        }

        for _, row in df.iterrows():
            row_dict = row.to_dict()
            pdf_path = row_dict.get("pdf_path")
            signed_url = create_pdf_signed_url(supabase, pdf_path, 3600)
            supporting_path = row_dict.get("supporting_path")
            supporting_url = create_pdf_signed_url(supabase, supporting_path, 3600)
            paper_url = normalize_url(row_dict.get("url"))

            with st.container():
                st.markdown(f"### [{row_dict['ref_no']}] {row_dict['title']}")
                st.write(f"著者: {row_dict['authors']}")
                st.write(f"雑誌: {row_dict['journal']} ({row_dict['year']})")

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

                tags_list = tag_map.get(row_dict["id"], [])
                if tags_list:
                    st.write("タグ:", ", ".join(tags_list))

                col1, col2, col3, col4, col5, col6, col7 = st.columns(7)

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
                        delete_paper(supabase, user_id, row_dict)
                        st.success("削除しました")
                        st.rerun()

                with col5:
                    if st.button("📚 引用", key=f"cite_{row_dict['id']}"):
                        st.code(make_word_citation(row_dict, style="APA"))

                with col6:
                    if st.button("⬆", key=f"up_{row_dict['id']}"):
                        move_paper(supabase, user_id, row_dict["id"], row_dict["display_order"], "up")
                        st.rerun()

                with col7:
                    if st.button("⬇", key=f"down_{row_dict['id']}"):
                        move_paper(
                            supabase,
                            user_id,
                            row_dict["id"],
                            row_dict["display_order"],
                            "down",
                        )
                        st.rerun()

                with st.expander("編集"):
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
                        key=f"status_{row_dict['id']}",
                    )

                    edit_notes = st.text_area(
                        "抄録メモ",
                        value=row_dict.get("notes") or "",
                        height=150,
                        key=f"notes_{row_dict['id']}",
                    )
                    edit_url = st.text_input(
                        "URL",
                        value=paper_url,
                        key=f"url_{row_dict['id']}",
                    )
                    selected_collection_labels = []
                    if collections:
                        try:
                            current_collection_ids = fetch_paper_collection_ids(
                                supabase,
                                row_dict["id"],
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
                            key=f"collections_{row_dict['id']}",
                        )
                    new_pdf_file = st.file_uploader(
                        "PDFを追加・差し替え",
                        type=["pdf"],
                        key=f"pdf_upload_{row_dict['id']}",
                    )
                    new_supporting_file = st.file_uploader(
                        "サポーティング資料を追加・差し替え",
                        type=SUPPORTING_FILE_TYPES,
                        key=f"supporting_upload_{row_dict['id']}",
                    )

                    if st.button("💾 保存", key=f"save_{row_dict['id']}"):
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
                            update_paper_details(
                                supabase,
                                user_id,
                                row_dict["id"],
                                edit_status,
                                edit_notes,
                                normalize_url(edit_url) or None,
                            )
                            update_paper_files(
                                supabase,
                                user_id,
                                row_dict["id"],
                                pdf_path=new_pdf_path,
                                supporting_path=new_supporting_path,
                            )
                            if collections:
                                set_paper_collections(
                                    supabase,
                                    row_dict["id"],
                                    [
                                        collection_id_by_label[label]
                                        for label in selected_collection_labels
                                    ],
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

                st.divider()


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
            paper_tag_result = (
                supabase.table("paper_tags")
                .select("paper_id")
                .eq("tag_id", tag_result.data[0]["id"])
                .execute()
            )
            paper_ids = [row["paper_id"] for row in (paper_tag_result.data or [])]

            if not paper_ids:
                st.write("見つかりません")
            else:
                papers_result = fetch_user_papers_by_ids(
                    supabase,
                    user_id,
                    paper_ids,
                    columns="id, title",
                )

                if not papers_result.data:
                    st.write("見つかりません")
                else:
                    for paper in papers_result.data:
                        st.write((paper["id"], paper["title"]))


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
                f"({collection_counts.get(collection['id'], 0)}件) "
                f"[{collection['id'][:8]}]"
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
            )
        except Exception:
            logger.exception("Failed to fetch collection papers")
            st.error("このコレクションの文献を取得できませんでした。")
            st.stop()

        st.subheader(f"{selected_label} ({len(papers)}件)")
        if not papers:
            st.write("このコレクションにはまだ文献がありません。一覧の編集欄から追加できます。")
        else:
            for paper in papers:
                st.write((paper["id"], paper["title"], paper.get("authors"), paper.get("year")))


elif menu == "重複確認":
    user_id = get_current_user_id()
    st.header("重複確認")

    result = fetch_user_papers(
        supabase,
        user_id,
        columns="id, title, authors, journal, year, doi",
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
                for paper in group_papers:
                    st.markdown(f"**{paper.get('title') or '無題'}**")
                    st.write(f"ID: {paper.get('id')}")
                    if paper.get("authors"):
                        st.write(f"著者: {paper.get('authors')}")
                    if paper.get("journal") or paper.get("year"):
                        st.write(f"雑誌・年: {paper.get('journal') or ''} ({paper.get('year') or '-'})")
                    if paper.get("doi"):
                        st.write(f"DOI: {paper.get('doi')}")
                    st.divider()


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

        st.write(f"文書ID: {selected_document.get('word_document_id')}")
        st.write(f"引用スタイル: {selected_document.get('citation_style')}")
        if selected_document.get("locale"):
            st.write(f"ロケール: {selected_document.get('locale')}")

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
            st.subheader(f"引用一覧 ({len(citations)}件)")
            for citation in citations:
                with st.container():
                    rendered_text = citation.get("rendered_text") or "引用"
                    st.markdown(f"**{citation.get('sort_order')}. {rendered_text}**")
                    if citation.get("word_control_id"):
                        st.caption(f"Word control: {citation['word_control_id']}")

                    items = citation.get("citation_items") or []
                    if items:
                        for item in items:
                            paper_id = item.get("paperId")
                            locator = item.get("locator")
                            reference_number = item.get("referenceNumber")
                            details = [f"paper_id={paper_id}"]
                            if reference_number:
                                details.append(f"ref={reference_number}")
                            if locator:
                                details.append(f"locator={locator}")
                            st.write("- " + ", ".join(details))
                    else:
                        st.caption("文献アイテムなし")

                    if citation.get("updated_at"):
                        st.caption(f"更新: {citation['updated_at']}")
                    st.divider()
