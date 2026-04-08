import streamlit as st
import sqlite3
import os
import shutil
import time
import requests   # ← 追加

DB_NAME = "papers.db"

def get_connection():
    return sqlite3.connect(DB_NAME)

# 👇ここに追加（重要）
def fetch_doi(doi):
    url = f"https://api.crossref.org/works/{doi}"
    res = requests.get(url)

    if res.status_code != 200:
        return None

    data = res.json()["message"]

    title = data["title"][0] if data.get("title") else ""
    authors = ", ".join([a["family"] for a in data.get("author", [])])
    journal = data["container-title"][0] if data.get("container-title") else ""
    year = data["issued"]["date-parts"][0][0] if data.get("issued") else 0

    return title, authors, journal, year

st.title("📚 文献管理アプリ")

menu = st.sidebar.selectbox("メニュー", ["追加", "検索", "一覧", "タグ検索"])

# -------------------
# 文献追加
# -------------------
if menu == "追加":
    st.header("文献追加")

    title = st.text_input("タイトル", value=st.session_state.get("title", ""))
    authors = st.text_input("著者", value=st.session_state.get("authors", ""))
    journal = st.text_input("雑誌", value=st.session_state.get("journal", ""))
    year = st.number_input("年", value=st.session_state.get("year", 2024))
    pdf_file = st.file_uploader("PDFアップロード", type=["pdf"])


    doi = st.text_input("DOI")

    if st.button("DOIから自動入力"):
       result = fetch_doi(doi)
       if result:
          title, authors, journal, year = result
          st.session_state["title"] = title
          st.session_state["authors"] = authors
          st.session_state["journal"] = journal
          st.session_state["year"] = year
          st.rerun()
       else:
          st.error("取得失敗")

    if st.button("追加"):
        if pdf_file is not None:
            os.makedirs("pdfs", exist_ok=True)

            filename = pdf_file.name
            name, ext = os.path.splitext(filename)
            new_filename = f"{name}_{int(time.time())}{ext}"
            new_path = os.path.join("pdfs", new_filename)

            with open(new_path, "wb") as f:
                f.write(pdf_file.read())

            conn = get_connection()
            c = conn.cursor()

            c.execute("INSERT INTO papers (title, authors, journal, year, pdf_path) VALUES (?, ?, ?, ?, ?)",
                      (title, authors, journal, int(year), new_path))
            paper_id = c.lastrowid

            tags = st.text_input("タグ（カンマ区切り）")
            for tag in tags.split(","):
                tag = tag.strip()
                c.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
                c.execute("SELECT id FROM tags WHERE name=?", (tag,))
                tag_id = c.fetchone()[0]
                c.execute("INSERT INTO paper_tags (paper_id, tag_id) VALUES (?, ?)", (paper_id, tag_id))

            conn.commit()
            conn.close()

            st.success("追加しました！")

# -------------------
# 検索
# -------------------
elif menu == "検索":
    keyword = st.text_input("キーワード")

    if st.button("検索"):
        conn = get_connection()
        c = conn.cursor()

        c.execute("""
        SELECT id, title, authors, year FROM papers
        WHERE title LIKE ? OR authors LIKE ?
        """, (f"%{keyword}%", f"%{keyword}%"))

        results = c.fetchall()
        conn.close()

        for r in results:
            st.write(r)

# -------------------
# 一覧
# -------------------
elif menu == "一覧":
    import pandas as pd

    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM papers", conn)
    conn.close()

    st.header("📚 論文一覧")

    if df.empty:
        st.write("データがありません")
    else:
        for _, row in df.iterrows():
            with st.container():
                st.markdown(f"### {row['title']}")
                st.write(f"著者: {row['authors']}")
                st.write(f"雑誌: {row['journal']} ({row['year']})")

                # タグ取得
                conn = get_connection()
                c = conn.cursor()
                c.execute("""
                SELECT tags.name FROM tags
                JOIN paper_tags ON tags.id = paper_tags.tag_id
                WHERE paper_tags.paper_id = ?
                """, (row['id'],))
                tags = [t[0] for t in c.fetchall()]
                conn.close()

                if tags:
                    st.write("タグ:", ", ".join(tags))

                col1, col2, col3 = st.columns(3)

                # PDF表示
                with col1:
                    if os.path.exists(row['pdf_path']):
                        with open(row['pdf_path'], "rb") as f:
                            st.download_button(
                                "📄 PDF",
                                f,
                                file_name=os.path.basename(row['pdf_path']),
                                key=f"dl_{row['id']}"
                            )

                # プレビュー
                with col2:
                    if st.button("👀 プレビュー", key=f"preview_{row['id']}"):
                        with open(row['pdf_path'], "rb") as f:
                            st.download_button(
                                "開く",
                                f,
                                file_name=os.path.basename(row['pdf_path'])
                            )

                # 削除
                with col3:
                    if st.button("🗑 削除", key=f"del_{row['id']}"):
                        conn = get_connection()
                        c = conn.cursor()

                        c.execute("DELETE FROM papers WHERE id=?", (row['id'],))
                        c.execute("DELETE FROM paper_tags WHERE paper_id=?", (row['id'],))
                        conn.commit()
                        conn.close()

                        if os.path.exists(row['pdf_path']):
                            os.remove(row['pdf_path'])

                        st.success("削除しました")
                        st.rerun()

                st.divider()

# -------------------
# タグ検索
# -------------------
elif menu == "タグ検索":
    tag = st.text_input("タグ名")

    if st.button("検索"):
        conn = get_connection()
        c = conn.cursor()

        c.execute("""
        SELECT papers.id, papers.title
        FROM papers
        JOIN paper_tags ON papers.id = paper_tags.paper_id
        JOIN tags ON tags.id = paper_tags.tag_id
        WHERE tags.name = ?
        """, (tag,))

        results = c.fetchall()
        conn.close()

        for r in results:
            st.write(r)