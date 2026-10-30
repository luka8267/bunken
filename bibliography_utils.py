"""DOI metadata review and backed-up, owner-scoped bibliography updates."""

import hashlib
import html
import json
import re
import time
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from html.parser import HTMLParser
from urllib.parse import quote

import requests

import paper_utils as papers


FIELDS = ("title", "authors", "journal", "year", "doi", "volume", "issue", "pages", "publisher")
ITEM_FIELDS = {field: ("publication_title" if field == "journal" else field) for field in FIELDS if field != "authors"}
CREATOR_COLUMNS = "id,item_id,creator_type,first_name,last_name,literal_name,position"


class _TitleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def clean_text(value):
    text = papers.normalize_text_db_value(value).strip()
    return "" if text.casefold() in {"nan", "none", "null", "<na>", "nat"} else text


def clean_title(value):
    parser = _TitleText()
    parser.feed(html.unescape(clean_text(value)))
    text = "".join(parser.parts)
    text = re.sub(r"(?:\$\$|\$)?\\pi\s*(?:\$\$|\$)?", "π", text)
    return re.sub(r"\s+", " ", text).strip()


def title_for_match(value):
    text = clean_title(value)
    text = re.sub(r"\s*\|.*$", "", text)
    text = re.sub(r"\s+-\s+[^-]+\s+-\s+\d{4}\s+-.*Wiley Online Library.*$", "", text)
    return re.sub(r"[^\w]+", "", text.casefold())


def metadata_from_crossref(message):
    authors = []
    for author in message.get("author") or []:
        family, given, literal = clean_text(author.get("family")), clean_text(author.get("given")), clean_text(author.get("name"))
        if family:
            authors.append({"family": family, "given": given})
        elif literal:
            authors.append({"literal": literal})
    year = None
    for key in ("published-print", "issued", "published-online"):
        dates = (message.get(key) or {}).get("date-parts") or []
        if dates and dates[0]:
            year = dates[0][0]
            break
    return {
        "title": clean_title((message.get("title") or [""])[0]),
        "authors": "; ".join(a.get("literal") or f"{a['family']}, {a['given']}".rstrip(", ") for a in authors),
        "author_list": authors,
        "journal": clean_text((message.get("container-title") or [""])[0]),
        "year": year,
        "doi": papers.normalize_doi(message.get("DOI")),
        "volume": clean_text(message.get("volume")),
        "issue": clean_text(message.get("issue")),
        "pages": papers.normalize_publication_pages(message.get("article-number"), message.get("page")),
        "publisher": clean_text(message.get("publisher")),
    }


def fetch_doi_metadata(doi):
    normalized = papers.normalize_doi(doi)
    if not normalized or not normalized.lower().startswith("10."):
        raise ValueError("有効なDOIがありません。")
    candidates = [normalized]
    if normalized.lower().endswith("/html"):
        candidates.append(normalized[:-5])
    if not normalized.endswith("+"):
        candidates.append(normalized + "+")
    for candidate in dict.fromkeys(candidates):
        for attempt in range(3):
            response = requests.get(
                "https://api.crossref.org/works/" + quote(candidate, safe="/"),
                headers={"User-Agent": "bunken/1.0 (bibliography-review)"}, timeout=20,
            )
            if response.status_code not in {429, 502, 503, 504} or attempt == 2:
                break
            delay = response.headers.get("Retry-After", "2")
            time.sleep(min(float(delay), 20) if delay.isdigit() else 2)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        message = response.json().get("message")
        if not isinstance(message, dict) or papers.normalize_doi(message.get("DOI")).casefold() not in {value.casefold() for value in candidates}:
            raise ValueError("DOIの一致を確認できませんでした。")
        result = metadata_from_crossref(message)
        result["source_url"] = "https://api.crossref.org/works/" + quote(result["doi"], safe="/")
        return result
    raise ValueError("Crossrefに登録情報が見つかりません。DOIを確認してください。")


def review_paper(paper, metadata):
    before_title, after_title = title_for_match(paper.get("title")), title_for_match(metadata.get("title"))
    similarity = SequenceMatcher(None, before_title, after_title).ratio()
    prefix = len(before_title) >= 35 and after_title.startswith(before_title)
    if before_title and similarity < 0.65 and not prefix:
        return {"paper": paper, "candidate": metadata, "changes": {}, "status": "要確認: DOIとタイトルが一致しません"}
    changes = {}
    for field in FIELDS:
        value = metadata.get(field)
        if not clean_text(value):
            continue
        current = paper.get(field)
        if field == "authors" and paper.get("author_list"):
            current = "; ".join(papers.normalize_bibtex_authors(paper["author_list"]))
        same = clean_text(current).casefold() == clean_text(value).casefold() if field == "doi" else clean_text(current) == clean_text(value)
        if not same:
            changes[field] = value
    return {"paper": paper, "candidate": metadata, "changes": changes, "status": "更新候補" if changes else "差分なし"}


def build_review(paper_list, fetcher=fetch_doi_metadata, progress=None):
    result = []
    for index, paper in enumerate(paper_list):
        try:
            row = review_paper(paper, fetcher(paper.get("doi"))) if papers.normalize_doi(paper.get("doi")) else {"paper": paper, "candidate": {}, "changes": {}, "status": "DOIなし"}
        except (requests.RequestException, ValueError, TypeError, KeyError) as error:
            row = {"paper": paper, "candidate": {}, "changes": {}, "status": "取得失敗", "error": str(error)}
        result.append(row)
        if progress:
            progress(index + 1, len(paper_list))
    return result


def _item_snapshot(supabase, user_id, item_id):
    result = supabase.table("items").select("id,user_id,updated_at," + ",".join(ITEM_FIELDS.values())).eq("id", item_id).eq("user_id", user_id).limit(1).execute()
    if not result.data:
        raise ValueError("対象文献の所有権を確認できません。")
    authors = supabase.table("creators").select(CREATOR_COLUMNS).eq("item_id", item_id).eq("creator_type", "author").order("position").execute().data or []
    return {"item": result.data[0], "authors": authors}


def _fingerprint(snapshot):
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def prepare_backup(supabase, user_id, selected):
    entries = []
    for review in selected:
        item_id = papers.normalize_text_db_value(review["paper"].get("item_id"))
        if not item_id or review.get("status") != "更新候補":
            raise ValueError("更新できない文献が含まれています。")
        snapshot = _item_snapshot(supabase, user_id, item_id)
        # Reject stale previews before writing a backup or applying changes.
        preview_time = review["paper"].get("updated_at")
        if preview_time and preview_time != snapshot["item"].get("updated_at"):
            raise ValueError("候補取得後に文献が変更されました。もう一度候補を取得してください。")
        entries.append({"item_id": item_id, "before": snapshot, "changes": review["changes"], "candidate": review["candidate"]})
    if not entries:
        raise ValueError("更新する文献を選択してください。")
    return {"version": 1, "kind": "bunken-bibliography-backup", "user_id": user_id, "created_at": datetime.now(timezone.utc).isoformat(), "entries": entries}


def persist_backup(supabase, user_id, backup):
    if backup.get("user_id") != user_id:
        raise ValueError("バックアップのユーザーが一致しません。")
    path = f"{user_id}/metadata-backups/{uuid.uuid4().hex}.json"
    body = json.dumps(backup, ensure_ascii=False, default=str).encode("utf-8")
    supabase.storage.from_(papers.BUCKET_NAME).upload(path, body, {"content-type": "application/json", "upsert": "false"})
    return path


def list_backups(supabase, user_id):
    prefix = f"{user_id}/metadata-backups"
    rows = supabase.storage.from_(papers.BUCKET_NAME).list(prefix, {"limit": 100, "sortBy": {"column": "created_at", "order": "desc"}})
    return [f"{prefix}/{row['name']}" for row in rows if re.fullmatch(r"[a-f0-9]{32}\.json", row.get("name", ""))]


def read_backup(supabase, user_id, path):
    if not re.fullmatch(re.escape(str(user_id)) + r"/metadata-backups/[a-f0-9]{32}\.json", path):
        raise ValueError("このユーザーのバックアップではありません。")
    return json.loads(supabase.storage.from_(papers.BUCKET_NAME).download(path))


def _write_authors(supabase, item_id, authors):
    rows = []
    for position, author in enumerate(authors, 1):
        rows.append({"item_id": item_id, "creator_type": "author", "position": position,
                     "first_name": author.get("given") or None, "last_name": author.get("family") or None,
                     "literal_name": author.get("literal") or None})
    if not rows:
        raise ValueError("著者情報が空のため更新を中止しました。")
    supabase.table("creators").upsert(rows, on_conflict="item_id,creator_type,position").execute()
    supabase.table("creators").delete().eq("item_id", item_id).eq("creator_type", "author").gt("position", len(rows)).execute()


def apply_backup(supabase, user_id, backup):
    if backup.get("kind") != "bunken-bibliography-backup" or backup.get("user_id") != user_id:
        raise ValueError("バックアップの形式またはユーザーが一致しません。")
    # Fail closed: a private, persistent backup must exist before the first DB write.
    path = persist_backup(supabase, user_id, backup)
    outcomes = []
    for entry in backup["entries"]:
        try:
            current = _item_snapshot(supabase, user_id, entry["item_id"])
            if _fingerprint(current) != _fingerprint(entry["before"]):
                raise ValueError("変更前の情報が一致しないためスキップしました。")
            fields = {ITEM_FIELDS[k]: v for k, v in entry["changes"].items() if k in ITEM_FIELDS}
            # Even an authors-only change takes an optimistic lock on the owning item.
            if not fields:
                fields = {"title": current["item"]["title"]}
            query = supabase.table("items").update(fields).eq("id", entry["item_id"]).eq("user_id", user_id)
            if current["item"].get("updated_at"):
                query = query.eq("updated_at", current["item"]["updated_at"])
            if not query.execute().data:
                raise ValueError("文献が変更されたか、更新権限がありません。")
            if "authors" in entry["changes"]:
                _write_authors(supabase, entry["item_id"], entry["candidate"]["author_list"])
            outcomes.append({"item_id": entry["item_id"], "status": "更新済み"})
        except Exception as error:
            outcomes.append({"item_id": entry["item_id"], "status": "未完了・要確認", "error": str(error)})
    return {"backup_path": path, "outcomes": outcomes}


def restore_backup(supabase, user_id, backup):
    if backup.get("kind") != "bunken-bibliography-backup" or backup.get("version") != 1 or backup.get("user_id") != user_id:
        raise ValueError("このアカウントの書誌情報バックアップを指定してください。")
    entries = backup.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("復元対象がありません。")
    current_backup = {**backup, "entries": []}
    for entry in entries:
        if entry["before"]["item"].get("id") != entry["item_id"] or entry["before"]["item"].get("user_id") != user_id:
            raise ValueError("バックアップの対象文献が一致しません。")
        authors = entry["before"]["authors"]
        if any(author.get("item_id") != entry["item_id"] or author.get("creator_type") != "author" for author in authors):
            raise ValueError("バックアップの著者情報が一致しません。")
        if authors:
            existing_ids = supabase.table("creators").select("id,item_id,creator_type").in_("id", [author["id"] for author in authors]).execute().data or []
            if any(author["item_id"] != entry["item_id"] or author["creator_type"] != "author" for author in existing_ids):
                raise ValueError("別の文献の著者情報は復元できません。")
        current = _item_snapshot(supabase, user_id, entry["item_id"])
        current_backup["entries"].append({**entry, "before": current})
    # Preserve the state immediately before restoration, too.
    path = persist_backup(supabase, user_id, current_backup)
    results = []
    for entry, current_entry in zip(entries, current_backup["entries"]):
        before = entry["before"]
        fields = {ITEM_FIELDS[field]: before["item"].get(ITEM_FIELDS[field]) for field in entry["changes"] if field in ITEM_FIELDS}
        if not fields:
            fields = {"title": current_entry["before"]["item"]["title"]}
        query = supabase.table("items").update(fields).eq("id", entry["item_id"]).eq("user_id", user_id)
        if current_entry["before"]["item"].get("updated_at"):
            query = query.eq("updated_at", current_entry["before"]["item"]["updated_at"])
        result = query.execute()
        if not result.data:
            raise ValueError("復元先を更新できませんでした。")
        if "authors" not in entry["changes"]:
            results.append(entry["item_id"])
            continue
        authors = before["authors"]
        if authors:
            safe_authors = [{key: author.get(key) for key in CREATOR_COLUMNS.split(",")} for author in authors]
            supabase.table("creators").upsert(safe_authors, on_conflict="id").execute()
        existing = supabase.table("creators").select("id").eq("item_id", entry["item_id"]).eq("creator_type", "author").execute().data or []
        keep = {row["id"] for row in authors}
        remove = [row["id"] for row in existing if row["id"] not in keep]
        if remove:
            supabase.table("creators").delete().eq("item_id", entry["item_id"]).eq("creator_type", "author").in_("id", remove).execute()
        results.append(entry["item_id"])
    return {"backup_path": path, "restored": results}
