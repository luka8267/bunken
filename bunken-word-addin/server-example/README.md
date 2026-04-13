# server-example

`bunken` 本体へ移植するための API サンプルです。

目的:
- Word Add-in から呼ぶ `/api/addin/*` を先に形にする
- 認証、文献検索、citation 整形、bibliography 整形の責務を分離する

想定:
- `bunken` 本体は Python ベース
- 文献データは Supabase から取得する
- アドインは Cookie ベースまたはトークン付きでアクセスする

## 含まれるもの

- `app.py`
  - FastAPI エントリポイント
- `models.py`
  - Pydantic モデル
- `paper_repository.py`
  - 文献取得の抽象
- `citation_service.py`
  - citation / bibliography 整形

## bunken へ移すときの考え方

1. `paper_repository.py` の in-memory 実装を Supabase 実装へ差し替える
2. `get_current_session()` を既存認証に接続する
3. `citation_service.py` を既存の引用出力ロジックと統合する

## 注意

これはそのまま本番投入するための完成版ではなく、Add-in 連携の最初の接着層です。
