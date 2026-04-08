import sqlite3
import os
import shutil
import time


DB_NAME = "papers.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute('''
    CREATE TABLE IF NOT EXISTS papers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        authors TEXT,
        journal TEXT,
        year INTEGER,
        pdf_path TEXT
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS paper_tags (
        paper_id INTEGER,
        tag_id INTEGER,
        FOREIGN KEY(paper_id) REFERENCES papers(id),
        FOREIGN KEY(tag_id) REFERENCES tags(id)
    )
    ''')

    conn.commit()
    conn.close()


def add_paper(title, authors, journal, year, pdf_path, tag_list):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # PDF保存フォルダ作成
    os.makedirs("pdfs", exist_ok=True)

    # ファイルコピー
    if not os.path.exists(pdf_path):
       print("PDFファイルが見つかりません")
       return
    
    filename = os.path.basename(pdf_path)
    name, ext = os.path.splitext(filename)

    new_filename = f"{name}_{int(time.time())}{ext}"
    new_path = os.path.join("pdfs", new_filename)
 
    shutil.copy(pdf_path, new_path)

    # DBにはコピー先を保存
    c.execute("INSERT INTO papers (title, authors, journal, year, pdf_path) VALUES (?, ?, ?, ?, ?)",
              (title, authors, journal, year, new_path))
    paper_id = c.lastrowid

    for tag in tag_list:
        tag = tag.strip()
        c.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
        c.execute("SELECT id FROM tags WHERE name=?", (tag,))
        tag_id = c.fetchone()[0]

        c.execute("INSERT INTO paper_tags (paper_id, tag_id) VALUES (?, ?)", (paper_id, tag_id))

    conn.commit()
    conn.close()


def search_papers(keyword):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
    SELECT id, title, authors, year FROM papers
    WHERE title LIKE ? OR authors LIKE ?
    """, (f"%{keyword}%", f"%{keyword}%"))

    results = c.fetchall()
    conn.close()

    for r in results:
        print(r)


def show_all():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT id, title FROM papers")
    for row in c.fetchall():
        print(row)

    conn.close()

def open_pdf(paper_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT pdf_path FROM papers WHERE id=?", (paper_id,))
    result = c.fetchone()
    conn.close()

    if result:
        os.startfile(result[0])
    else:
        print("見つかりません")

def search_by_tag(tag_name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
    SELECT papers.id, papers.title
    FROM papers
    JOIN paper_tags ON papers.id = paper_tags.paper_id
    JOIN tags ON tags.id = paper_tags.tag_id
    WHERE tags.name = ?
    """, (tag_name,))

    results = c.fetchall()
    conn.close()

    for r in results:
        print(r)

def delete_paper(paper_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # PDFパス取得
    c.execute("SELECT pdf_path FROM papers WHERE id=?", (paper_id,))
    result = c.fetchone()

    if result:
        pdf_path = result[0]

        # DBから削除
        c.execute("DELETE FROM papers WHERE id=?", (paper_id,))

        # タグ関連も削除
        c.execute("DELETE FROM paper_tags WHERE paper_id=?", (paper_id,))

        conn.commit()
        conn.close()

        # PDFファイル削除
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

        print("削除しました")
    else:
        conn.close()
        print("見つかりません")


if __name__ == "__main__":
    init_db()

    while True:
        print("\n1: 追加  2: 検索  3: 一覧  4: PDF開く  5: タグ検索  0: 終了")
        cmd = input(">> ")

        if cmd == "1":
            title = input("タイトル: ")
            authors = input("著者: ")
            journal = input("雑誌: ")
            year = int(input("年: "))
            pdf_path = input("PDFパス: ")
            tags = input("タグ(カンマ区切り): ").split(",")

            add_paper(title, authors, journal, year, pdf_path, tags)

        elif cmd == "2":
            keyword = input("検索キーワード: ")
            search_papers(keyword)

        elif cmd == "3":
            show_all()
        
        elif cmd == "4":
             pid = int(input("論文ID: "))
             open_pdf(pid)
        
        elif cmd == "5":
             tag = input("タグ名: ")
             search_by_tag(tag)

        elif cmd == "6":
             pid = int(input("削除する論文ID: "))
             delete_paper(pid)

        elif cmd == "0":
            break

        