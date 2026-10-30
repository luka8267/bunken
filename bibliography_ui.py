import csv
import io
import json
import uuid

import streamlit as st

import bibliography_utils as bibliography


LABELS = {"title": "タイトル", "authors": "著者", "journal": "雑誌", "year": "年", "doi": "DOI", "volume": "巻", "issue": "号", "pages": "ページ / 論文番号", "publisher": "出版社"}


@st.dialog("DOIから書誌情報を更新", width="large")
def render_bibliography_review(supabase, user_id, records, clear_caches):
    key = f"bibliography_review_{user_id}"
    if key not in st.session_state:
        st.session_state[key] = {"rows": [], "revision": uuid.uuid4().hex}
    state = st.session_state[key]
    targets = [row for row in records if bibliography.papers.normalize_doi(row.get("doi"))]
    st.caption(f"DOIあり {len(targets)}件 / ライブラリ {len(records)}件")
    consent = st.checkbox("登録済みDOIのみをCrossref（api.crossref.org）へ送信して照合する", key=key + "_consent")
    if st.button("書誌情報の候補を取得", disabled=not consent, key=key + "_fetch"):
        progress = st.progress(0)
        state["rows"] = bibliography.build_review(targets, progress=lambda done, total: progress.progress(done / max(total, 1)))
        state["revision"] = uuid.uuid4().hex
        state.pop("backup", None)
        state.pop("result", None)
        progress.empty()

    rows = state["rows"]
    if rows:
        summary = [{"ID": row["paper"]["id"], "DOI": row["paper"].get("doi"), "タイトル": row["paper"].get("title"), "状態": row["status"], "詳細": row.get("error", ""), "変更項目": " / ".join(LABELS[field] for field in row["changes"])} for row in rows]
        st.dataframe(summary, hide_index=True, width="stretch")
        buffer = io.StringIO()
        export_rows = [
            {**summary_row,
             **{LABELS[field] + "（現在）": bibliography.clean_text(row["paper"].get(field)) for field in LABELS},
             **{LABELS[field] + "（候補）": bibliography.clean_text(row["candidate"].get(field)) for field in LABELS},
             "出典": row["candidate"].get("source_url", "")}
            for summary_row, row in zip(summary, rows)
        ]
        writer = csv.DictWriter(buffer, fieldnames=export_rows[0].keys())
        writer.writeheader()
        writer.writerows({key: "'" + str(value) if str(value).startswith(("=", "+", "-", "@")) else value for key, value in row.items()} for row in export_rows)
        st.download_button("照合結果CSV", buffer.getvalue().encode("utf-8-sig"), "bibliography-review.csv", "text/csv", key=key + "_csv")
        fields = st.multiselect("更新する項目", list(LABELS), default=list(LABELS), format_func=LABELS.get, key=key + "_fields")
        candidates = []
        for row in rows:
            changes = {field: value for field, value in row["changes"].items() if field in fields}
            if row["status"] == "更新候補" and changes and row["paper"].get("item_id"):
                candidates.append({**row, "changes": changes})
        if not candidates:
            state.pop("backup", None)
            state["signature"] = ""
        if candidates:
            select_all = st.checkbox("更新候補をすべて選択", key=key + "_all")
            selection = st.data_editor(
                [{"更新": select_all, "ID": str(row["paper"]["id"]), "DOI": row["candidate"]["doi"], "タイトル": row["candidate"]["title"]} for row in candidates],
                disabled=["ID", "DOI", "タイトル"], hide_index=True, width="stretch",
                key=f"{key}_selection_{state['revision']}_{select_all}_{','.join(fields)}",
            )
            chosen = [row for row, selected in zip(candidates, selection) if selected["更新"]]
            differences = [{"文献": row["paper"]["id"], "項目": LABELS[field], "変更前": bibliography.clean_text(row["paper"].get(field)), "変更後": bibliography.clean_text(value)} for row in chosen for field, value in row["changes"].items()]
            if differences:
                st.dataframe(differences, hide_index=True, width="stretch")
            signature = json.dumps([{ "item_id": row["paper"]["item_id"], "changes": row["changes"]} for row in chosen], sort_keys=True, ensure_ascii=False)
            if state.get("signature") != signature:
                state.pop("backup", None)
                state["signature"] = signature
            if st.button("変更前バックアップを準備", disabled=not chosen, key=key + "_prepare"):
                try:
                    state["backup"] = bibliography.prepare_backup(supabase, user_id, chosen)
                except Exception:
                    st.error("バックアップを準備できませんでした。文献を再読み込みして再度照合してください。")
            if state.get("backup"):
                st.download_button("変更前バックアップJSON", json.dumps(state["backup"], ensure_ascii=False, indent=2), "bibliography-backup.json", "application/json", key=key + "_backup_download")
                confirm = st.checkbox("差分とバックアップを確認しました。選択した項目を上書きします。", key=key + "_confirm_" + bibliography.hashlib.sha256(signature.encode()).hexdigest()[:16])
                if st.button("バックアップを保存して更新", disabled=not confirm, type="primary", key=key + "_apply"):
                    try:
                        state["result"] = bibliography.apply_backup(supabase, user_id, state["backup"])
                        clear_caches()
                        state["rows"] = []
                        state.pop("backup", None)
                    except Exception:
                        st.error("バックアップ保存に失敗したため更新しませんでした。接続・Storage権限を確認してください。")
    if state.get("result"):
        result = state["result"]
        st.dataframe(result["outcomes"], hide_index=True, width="stretch")
        st.caption("変更前バックアップ: " + result["backup_path"])
        if any(row["status"] != "更新済み" for row in result["outcomes"]):
            st.warning("一部の更新は未完了です。バックアップを保持し、対象文献を確認してください。")
        if st.button("一覧を更新して閉じる", key=key + "_close"):
            st.rerun()

    with st.expander("書誌情報をバックアップから復元"):
        if st.button("保存済みバックアップを取得", key=key + "_list_backups"):
            try:
                state["backup_paths"] = bibliography.list_backups(supabase, user_id)
            except Exception:
                st.error("保存済みバックアップを取得できませんでした。")
        paths = state.get("backup_paths") or []
        stored = None
        if paths:
            path = st.selectbox("保存済みバックアップ", paths, key=key + "_stored_path")
            if st.button("バックアップを読み込む", key=key + "_read_backup"):
                try:
                    state["restore_backup"] = bibliography.read_backup(supabase, user_id, path)
                    state["restore_path"] = path
                except Exception:
                    st.error("バックアップを読み込めませんでした。")
            if state.get("restore_path") == path:
                stored = state.get("restore_backup")
                if stored:
                    st.download_button("保存済みバックアップJSON", json.dumps(stored, ensure_ascii=False, indent=2), "bibliography-backup.json", "application/json", key=key + "_stored_download")
        upload = st.file_uploader("書誌情報バックアップJSON", type=["json"], key=key + "_restore_file")
        restore_confirm = st.checkbox("現在の書誌情報を、指定したバックアップの内容に戻します。", key=key + "_restore_confirm")
        if st.button("復元前バックアップを保存して復元", disabled=not (upload or stored) or not restore_confirm, key=key + "_restore"):
            try:
                if upload and upload.size > 5 * 1024 * 1024:
                    raise ValueError("バックアップが大きすぎます。")
                result = bibliography.restore_backup(supabase, user_id, json.loads(upload.getvalue()) if upload else stored)
                clear_caches()
                st.success(f"書誌情報を復元しました: {len(result['restored'])}件")
                st.caption("復元前バックアップ: " + result["backup_path"])
            except Exception:
                st.error("復元できませんでした。アカウント・バックアップ形式・文献の更新状態を確認してください。")
