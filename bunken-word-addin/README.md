# bunken-word-addin

`bunken` と連携して Word 上で引用挿入・参考文献更新を行う Office Add-in の雛形です。

対象:
- Word on Windows
- Word on Mac

基本方針:
- `Task Pane Add-in` を採用する
- Windows 固有の COM/VSTO には依存しない
- `WordApiDesktop` 依存を避け、クロスプラットフォームで使いやすい API を優先する
- 文書中の引用は `ContentControl` とメタデータで追跡する
- 文献検索や整形は `bunken` 側 API と分担する

## 想定ディレクトリ構成

```text
bunken-word-addin/
  README.md
  docs/
    architecture.md
    api-contract.md
  manifest/
    manifest.template.xml
  src/
    taskpane/
      App.tsx
      index.tsx
      components/
        CitationSearchPanel.tsx
        CitationResultList.tsx
        CitationActions.tsx
        BibliographyPanel.tsx
      services/
        bunkenApi.ts
        officeWord.ts
        auth.ts
      types/
        citation.ts
        paper.ts
        documentState.ts
      utils/
        citationFormatter.ts
        platform.ts
```

## MVP

1. `bunken` にログインする
2. 文献を検索する
3. 選択中カーソル位置へ引用を挿入する
4. 引用箇所を `ContentControl` として追跡する
5. 文末の参考文献ブロックを生成・更新する
6. 既存の引用を再読込して一括更新する

## 文書内で保持する情報

- 引用コントロール単位
  - `citationId`
  - `paperIds`
  - `style`
  - `locator`
  - `prefix`
  - `suffix`

- 文書全体
  - `bibliographyControlId`
  - `style`
  - `citations`

## 役割分担

- Word Add-in
  - UI
  - 選択位置への挿入
  - ContentControl の作成・更新
  - 文書状態の同期

- `bunken` API
  - 文献検索
  - 書誌データ取得
  - 引用文字列の整形
  - 参考文献一覧の整形

## 次の実装順

1. `bunken` 側に API を追加
2. Office Add-in の雛形を作成
3. 引用挿入を実装
4. 参考文献更新を実装
5. スタイル切替と locator を追加

## 現在入っているもの

- `src/taskpane/`
  - React + TypeScript の MVP UI
- `taskpane.html` / `commands.html`
  - Office Add-in のエントリポイント
- `manifest/manifest.template.xml`
  - Word 用タスクペインアドインのテンプレート
- `server-example/`
  - `bunken` 本体へ移植するための `/api/addin/*` サンプル
