import re
from html.parser import HTMLParser
from urllib.parse import unquote

import pandas as pd
import requests
import streamlit as st
from supabase import Client

from auth_utils import (
    build_supabase_client,
    get_current_user_id,
    login_user,
    normalize_email,
    normalize_username,
    register_user,
    set_authenticated_user,
    sign_out_user,
    store_auth_session,
)
from paper_utils import (
    READING_STATUSES,
    SORT_OPTIONS,
    create_pdf_signed_url,
    delete_paper,
    delete_pdf_from_storage,
    export_to_word_bytes,
    fetch_user_papers,
    get_tag_map_for_papers,
    make_word_citation,
    move_paper,
    normalize_doi,
    save_tags_for_paper,
    search_user_papers,
    sort_papers_dataframe,
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

supabase: Client = build_supabase_client(SUPABASE_URL, SUPABASE_KEY)


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
    if not normalized_url:
        return None

    doi_from_url = extract_doi(normalized_url)
    if doi_from_url:
        doi_result = fetch_doi(doi_from_url)
        if doi_result:
            return (*doi_result, doi_from_url)

    try:
        response = requests.get(
            normalized_url,
            headers={"User-Agent": "bunken/1.0"},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None

    parser = MetadataParser()
    parser.feed(response.text[:300000])
    meta = parser.meta

    doi_from_page = extract_doi(response.url) or extract_doi(response.text[:300000])
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
    st.title("ログイン")

    auth_mode = st.radio("選択", ["ログイン", "新規登録"])

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
menu = st.sidebar.selectbox("メニュー", ["追加", "検索", "一覧", "タグ検索"])


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
            save_tags_for_paper(supabase, paper_id, tags)
            st.success("追加しました！")
        except Exception as error:
            st.error(f"エラー内容: {error}")
            st.exception(error)


elif menu == "検索":
    user_id = get_current_user_id()
    keyword = st.text_input("キーワード").strip()

    if st.button("検索"):
        result = search_user_papers(supabase, user_id, keyword)
        papers = result.data or []

        if not papers:
            st.write("見つかりません")
        else:
            for paper in papers:
                st.write((paper["id"], paper["title"], paper["authors"], paper["year"]))


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
                        except Exception as error:
                            st.error(f"更新失敗: {error}")

                st.divider()


elif menu == "タグ検索":
    user_id = get_current_user_id()
    tag = st.text_input("タグ名").strip()

    if st.button("検索"):
        tag_result = (
            supabase.table("tags")
            .select("id")
            .eq("name", tag)
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
                papers_result = (
                    supabase.table("papers")
                    .select("id, title")
                    .eq("user_id", user_id)
                    .in_("id", paper_ids)
                    .execute()
                )

                if not papers_result.data:
                    st.write("見つかりません")
                else:
                    for paper in papers_result.data:
                        st.write((paper["id"], paper["title"]))
