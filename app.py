import streamlit as st
import sqlite3
import os
import shutil
import time
import requests   # ← 追加
from docx import Document

def export_to_word(papers):
    doc = Document()
    doc.add_heading("参考文献", 0)

    for i, p in enumerate(papers, start=1):
        text = f"[{i}] {p['authors']} ({p['year']}). {p['title']}. {p['journal']}."
        doc.add_paragraph(text)

    filepath = "references.docx"
    doc.save(filepath)
    return filepath

DB_NAME = "papers.db"

def get_connection():
    return sqlite3.connect(DB_NAME)


# ここに追加
def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS papers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        authors TEXT,
        journal TEXT,
        year INTEGER,
        pdf_path TEXT,
        user_id INTEGER
        display_order INTEGER
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS paper_tags (
        paper_id INTEGER,
        tag_id INTEGER
    )
    """)

    conn.commit()
    conn.close()

# 起動時に実行
init_db()

if "user_id" not in st.session_state:
    st.title("ログイン")

    menu = st.radio("選択", ["ログイン", "新規登録"])

    username = st.text_input("ユーザー名")
    password = st.text_input("パスワード", type="password")

    conn = get_connection()
    c = conn.cursor()

    if menu == "新規登録":
        if st.button("登録"):
            try:
                c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
                conn.commit()
                st.success("登録完了")
            except:
                st.error("ユーザー名が既に存在")

    else:
        if st.button("ログイン"):
            c.execute("SELECT id FROM users WHERE username=? AND password=?", (username, password))
            user = c.fetchone()

            if user:
                st.session_state["user_id"] = user[0]
                st.success("ログイン成功")
                st.rerun()
            else:
                st.error("失敗")
    
    try:
        c.execute("ALTER TABLE papers ADD COLUMN display_order INTEGER")
    except sqlite3.OperationalError:
        pass  # すでに存在する場合は無視

    conn.commit()
    conn.close()
    st.stop()

# ログアウトボタン
if st.sidebar.button("ログアウト"):
    st.session_state.clear()
    st.rerun()

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

    tags = st.text_input("タグ（カンマ区切り）")
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

            user_id = st.session_state["user_id"]
           

            c.execute("SELECT MAX(display_order) FROM papers WHERE user_id=?", (user_id,))
            max_order = c.fetchone()[0]
            next_order = (max_order + 1) if max_order else 1

            c.execute("""
            INSERT INTO papers (title, authors, journal, year, pdf_path, user_id, display_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (title, authors, journal, int(year), new_path, user_id, next_order))

            paper_id = c.lastrowid

            for tag in tags.split(","):
                tag = tag.strip()
                if tag == "":
                    continue
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
        WHERE (title LIKE ? OR authors LIKE ?)
        AND user_id=?
        """, (f"%{keyword}%", f"%{keyword}%", st.session_state["user_id"]))
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
    user_id = st.session_state["user_id"]

    df = pd.read_sql_query(
       "SELECT * FROM papers WHERE user_id=? ORDER BY display_order",
       conn,
       params=(user_id,)
    )
    conn.close()

    sort_option = st.selectbox(
    "並び替え",
    ["追加順", "年（新しい順）", "年（古い順）", "タイトル"]
    )

    if sort_option == "年（新しい順）":
        df = df.sort_values(by="year", ascending=False)

    elif sort_option == "年（古い順）":
        df = df.sort_values(by="year", ascending=True)

    elif sort_option == "タイトル":
        df = df.sort_values(by="title", ascending=True)

    df = df.reset_index(drop=True)
    df["ref_no"] = df.index + 1

# 「追加順」は何もしない（そのまま）

    st.header("📚 論文一覧")

    if st.button("📄 Word出力"):
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

                col1, col2, col3, col4, col5, col6,= st.columns(6)

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
                
                with col4:
                    if st.button("📋 コピー", key=f"copy_{row['id']}"):
                        citation = f"[{row['ref_no']}] {row['authors']} ({row['year']}). {row['title']}. {row['journal']}."
                        st.code(citation)

                with col5:
                    if st.button("⬆", key=f"up_{row['id']}"):
                        conn = get_connection()
                        c = conn.cursor()

                        c.execute("""
                        SELECT id, display_order FROM papers
                        WHERE user_id=? AND display_order < ?
                        ORDER BY display_order DESC LIMIT 1
                        """, (user_id, row['display_order']))
                        prev = c.fetchone()

                        if prev:
                            c.execute("UPDATE papers SET display_order=? WHERE id=?", (prev[1], row['id']))
                            c.execute("UPDATE papers SET display_order=? WHERE id=?", (row['display_order'], prev[0]))
                            conn.commit()

                        conn.close()
                        st.rerun()     

                with col6:
                    if st.button("⬇", key=f"down_{row['id']}"):
                        conn = get_connection()
                        c = conn.cursor()

                        c.execute("""
                        SELECT id, display_order FROM papers
                        WHERE user_id=? AND display_order > ?
                        ORDER BY display_order ASC LIMIT 1
                        """, (user_id, row['display_order']))
                        nxt = c.fetchone()

                        if nxt:
                           c.execute("UPDATE papers SET display_order=? WHERE id=?", (nxt[1], row['id']))
                           c.execute("UPDATE papers SET display_order=? WHERE id=?", (row['display_order'], nxt[0]))
                           conn.commit()

                        conn.close()
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
        AND papers.user_id = ?
        """, (tag, st.session_state["user_id"]))

        results = c.fetchall()
        conn.close()

        for r in results:
            st.write(r)
