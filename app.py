import streamlit as st
import os
import time
import requests
import pandas as pd
from docx import Document
from supabase import create_client, Client

# -----------------------------
# Supabase 接続
# -----------------------------
supabase: Client = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_KEY"]
)

supabase_admin: Client = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
)

BUCKET_NAME = "paper-pdfs"

# -----------------------------
# Word出力
# -----------------------------
def export_to_word(papers):
    doc = Document()
    doc.add_heading("参考文献", 0)

    for i, p in enumerate(papers, start=1):
        text = f"[{i}] {p.get('authors', '')} ({p.get('year', '')}). {p.get('title', '')}. {p.get('journal', '')}."
        doc.add_paragraph(text)

    filepath = "references.docx"
    doc.save(filepath)
    return filepath

# -----------------------------
# DOI取得
# -----------------------------
def fetch_doi(doi):
    url = f"https://api.crossref.org/works/{doi}"
    res = requests.get(url, timeout=15)

    if res.status_code != 200:
        return None

    data = res.json()["message"]

    title = data["title"][0] if data.get("title") else ""
    authors = ", ".join([a.get("family", "") for a in data.get("author", [])])
    journal = data["container-title"][0] if data.get("container-title") else ""
    year = data["issued"]["date-parts"][0][0] if data.get("issued") else 0

    return title, authors, journal, year

# -----------------------------
# Storage: PDFアップロード
# -----------------------------
def upload_pdf_to_storage(pdf_file, user_id):
    filename = pdf_file.name
    name, ext = os.path.splitext(filename)
    safe_name = f"{name}_{int(time.time())}{ext}"
    storage_path = f"{user_id}/{safe_name}"

    file_bytes = pdf_file.read()

    supabase_admin.storage.from_(BUCKET_NAME).upload(
        path=storage_path,
        file=file_bytes,
        file_options={"content-type": "application/pdf"}
    )
    return storage_path

# -----------------------------
# Storage: 署名付きURL生成
# -----------------------------
def create_pdf_signed_url(storage_path, expires_in=3600):
    response = (
        supabase_admin.storage
        .from_(BUCKET_NAME)
        .create_signed_url(storage_path, expires_in)
    )

    if isinstance(response, dict):
        return response.get("signedURL") or response.get("signedUrl")
    return None


def delete_pdf_from_storage(storage_path):
    if not storage_path:
        return

    supabase_admin.storage.from_(BUCKET_NAME).remove([storage_path])

# -----------------------------
# タグ取得
# -----------------------------
def get_tags_for_paper(paper_id):
    pt_result = (
        supabase.table("paper_tags")
        .select("tag_id")
        .eq("paper_id", paper_id)
        .execute()
    )

    if not pt_result.data:
        return []

    tag_ids = [x["tag_id"] for x in pt_result.data]

    tag_result = (
        supabase.table("tags")
        .select("id, name")
        .in_("id", tag_ids)
        .execute()
    )

    if not tag_result.data:
        return []

    return [x["name"] for x in tag_result.data]

# -----------------------------
# 並び順入れ替え
# -----------------------------
def move_up(user_id, paper_id, display_order):
    prev_result = (
        supabase.table("papers")
        .select("id, display_order")
        .eq("user_id", user_id)
        .lt("display_order", display_order)
        .order("display_order", desc=True)
        .limit(1)
        .execute()
    )

    if prev_result.data:
        prev = prev_result.data[0]

        supabase.table("papers").update({
            "display_order": prev["display_order"]
        }).eq("id", paper_id).execute()

        supabase.table("papers").update({
            "display_order": display_order
        }).eq("id", prev["id"]).execute()

def move_down(user_id, paper_id, display_order):
    next_result = (
        supabase.table("papers")
        .select("id, display_order")
        .eq("user_id", user_id)
        .gt("display_order", display_order)
        .order("display_order")
        .limit(1)
        .execute()
    )

    if next_result.data:
        nxt = next_result.data[0]

        supabase.table("papers").update({
            "display_order": nxt["display_order"]
        }).eq("id", paper_id).execute()

        supabase.table("papers").update({
            "display_order": display_order
        }).eq("id", nxt["id"]).execute()

# -----------------------------
# ログイン
# -----------------------------
if "user_id" not in st.session_state:
    st.title("ログイン")

    auth_mode = st.radio("選択", ["ログイン", "新規登録"])

    username = st.text_input("ユーザー名")
    password = st.text_input("パスワード", type="password")

    if auth_mode == "新規登録":
        if st.button("登録"):
            try:
                supabase.table("users").insert({
                    "username": username,
                    "password": password
                }).execute()
                st.success("登録完了")
            except Exception:
                st.error("ユーザー名が既に存在する可能性があります")

    else:
        if st.button("ログイン"):
            result = (
                supabase.table("users")
                .select("id")
                .eq("username", username)
                .eq("password", password)
                .execute()
            )

            if result.data:
                st.session_state["user_id"] = result.data[0]["id"]
                st.session_state["username"] = username
                st.success("ログイン成功")
                st.rerun()
            else:
                st.error("失敗")

    st.stop()

# -----------------------------
# ログアウト
# -----------------------------
if st.sidebar.button("ログアウト"):
    st.session_state.clear()
    st.rerun()

st.sidebar.write(f"ログイン中: {st.session_state.get('username', '')}")

st.title("📚 文献管理アプリ")

menu = st.sidebar.selectbox("メニュー", ["追加", "検索", "一覧", "タグ検索"])

# -----------------------------
# 文献追加
# -----------------------------
if menu == "追加":
    user_id = st.session_state["user_id"]
    st.header("文献追加")

    title = st.text_input("タイトル", value=st.session_state.get("title", ""))
    authors = st.text_input("著者", value=st.session_state.get("authors", ""))
    journal = st.text_input("雑誌", value=st.session_state.get("journal", ""))
    year = st.number_input("年", value=int(st.session_state.get("year", 2024)), step=1)
    pdf_file = st.file_uploader("PDFアップロード", type=["pdf"])

    doi = st.text_input("DOI")

    if st.button("DOIから自動入力"):
        result = fetch_doi(doi)
        if result:
            st.session_state["title"] = result[0]
            st.session_state["authors"] = result[1]
            st.session_state["journal"] = result[2]
            st.session_state["year"] = result[3]
            st.rerun()
        else:
            st.error("取得失敗")

    tags = st.text_input("タグ（カンマ区切り）")

    if st.button("追加"):
        user_id = st.session_state["user_id"]
        doi = doi.strip()

        if doi:
            existing = (
            supabase.table("papers")
            .select("id, title")
            .eq("user_id", user_id)
            .eq("doi", doi)
            .limit(1)
            .execute()
        )

        if existing.data:
            st.warning("このDOIの文献はすでに登録されています。")
            st.stop()

    try:
        pdf_path = None
        if pdf_file is not None:
            pdf_path = upload_pdf_to_storage(pdf_file, user_id)

        max_result = (
            supabase.table("papers")
            .select("display_order")
            .eq("user_id", user_id)
            .order("display_order", desc=True)
            .limit(1)
            .execute()
        )

        next_order = 1
        if max_result.data:
            current_max = max_result.data[0]["display_order"]
            next_order = (current_max or 0) + 1

        insert_result = (
            supabase.table("papers")
            .insert({
                "title": title,
                "authors": authors,
                "journal": journal,
                "year": int(year),
                "doi": doi if doi else None,
                "pdf_path": pdf_path,
                "user_id": user_id,
                "display_order": next_order
            })
            .execute()
        )

        paper_id = insert_result.data[0]["id"]

        for tag in tags.split(","):
            tag = tag.strip()
            if tag == "":
                continue

            tag_result = (
                supabase.table("tags")
                .select("id")
                .eq("name", tag)
                .execute()
            )

            if tag_result.data:
                tag_id = tag_result.data[0]["id"]
            else:
                new_tag = (
                    supabase.table("tags")
                    .insert({"name": tag})
                    .execute()
                )
                tag_id = new_tag.data[0]["id"]

            supabase.table("paper_tags").upsert({
                "paper_id": paper_id,
                "tag_id": tag_id
            }).execute()

        st.success("追加しました！")

    except Exception as e:
        st.error(f"エラー内容: {e}")
        st.exception(e)

# -----------------------------
# 検索
# -----------------------------
elif menu == "検索":
    user_id = st.session_state["user_id"]
    keyword = st.text_input("キーワード")

    if st.button("検索"):
        user_id = st.session_state["user_id"]

        result = (
            supabase.table("papers")
            .select("id, title, authors, year")
            .eq("user_id", user_id)
            .execute()
        )

        papers = result.data or []

        filtered = []
        for p in papers:
            title_val = p.get("title") or ""
            authors_val = p.get("authors") or ""

            if keyword.lower() in title_val.lower() or keyword.lower() in authors_val.lower():
                filtered.append(p)

        for r in filtered:
            st.write((r["id"], r["title"], r["authors"], r["year"]))

# -----------------------------
# 一覧
# -----------------------------
elif menu == "一覧":
    user_id = st.session_state["user_id"]

    result = (
        supabase.table("papers")
        .select("*")
        .eq("user_id", user_id)
        .order("display_order")
        .execute()
    )

    df = pd.DataFrame(result.data)

    sort_option = st.selectbox(
        "並び替え",
        ["追加順", "年（新しい順）", "年（古い順）", "タイトル"]
    )

    if not df.empty:
        if sort_option == "年（新しい順）":
            df = df.sort_values(by="year", ascending=False)
        elif sort_option == "年（古い順）":
            df = df.sort_values(by="year", ascending=True)
        elif sort_option == "タイトル":
            df = df.sort_values(by="title", ascending=True)

        df = df.reset_index(drop=True)
        df["ref_no"] = df.index + 1

    st.header("📚 論文一覧")

    if not df.empty and st.button("📄 Word出力"):
        papers = df.to_dict(orient="records")
        filepath = export_to_word(papers)

        with open(filepath, "rb") as f:
            st.download_button(
                "ダウンロード",
                f,
                file_name="references.docx"
            )

    if df.empty:
        st.write("データがありません")
    else:
        for _, row in df.iterrows():
            with st.container():
                st.markdown(f"### [{row['ref_no']}] {row['title']}")
                st.write(f"著者: {row['authors']}")
                st.write(f"雑誌: {row['journal']} ({row['year']})")

                tags_list = get_tags_for_paper(row["id"])
                if tags_list:
                    st.write("タグ:", ", ".join(tags_list))

                col1, col2, col3, col4, col5, col6 = st.columns(6)

                with col1:
                    pdf_path = row.get("pdf_path")
                    if pdf_path:
                        signed_url = create_pdf_signed_url(pdf_path, 3600)
                        if signed_url:
                            st.link_button("📄 PDF", signed_url)

                with col2:
                    pdf_path = row.get("pdf_path")
                    if pdf_path:
                        signed_url = create_pdf_signed_url(pdf_path, 3600)
                        if signed_url:
                            st.link_button("👀 開く", signed_url)

                with col3:
                    if st.button("🗑 削除", key=f"del_{row['id']}"):
                        pdf_path = row.get("pdf_path")
                        if pdf_path:
                            delete_pdf_from_storage(pdf_path)

                        supabase.table("paper_tags").delete().eq("paper_id", row["id"]).execute()
                        supabase.table("papers").delete().eq("id", row["id"]).execute()

                        st.success("削除しました")
                        st.rerun()

                with col4:
                    if st.button("📋 コピー", key=f"copy_{row['id']}"):
                        citation = f"[{row['ref_no']}] {row['authors']} ({row['year']}). {row['title']}. {row['journal']}."
                        st.code(citation)

                with col5:
                    if st.button("⬆", key=f"up_{row['id']}"):
                        move_up(user_id, row["id"], row["display_order"])
                        st.rerun()

                with col6:
                    if st.button("⬇", key=f"down_{row['id']}"):
                        move_down(user_id, row["id"], row["display_order"])
                        st.rerun()

                st.divider()

# -----------------------------
# タグ検索
# -----------------------------
elif menu == "タグ検索":
    user_id = st.session_state["user_id"]
    tag = st.text_input("タグ名")

    if st.button("検索"):
        user_id = st.session_state["user_id"]

        tag_result = (
            supabase.table("tags")
            .select("id")
            .eq("name", tag)
            .execute()
        )

        if not tag_result.data:
            st.write("見つかりません")
        else:
            tag_id = tag_result.data[0]["id"]

            pt_result = (
                supabase.table("paper_tags")
                .select("paper_id")
                .eq("tag_id", tag_id)
                .execute()
            )

            paper_ids = [x["paper_id"] for x in pt_result.data]

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

                for r in papers_result.data:
                    st.write((r["id"], r["title"]))
                
