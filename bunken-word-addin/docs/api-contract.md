# API Contract

## 方針

Word アドインは、文献検索と整形を `bunken` API に依頼する。
アドイン内に複雑な引用ルールを埋め込みすぎない。

## Endpoints

### `POST /api/addin/auth/session`

アドイン用セッション確認。

Response:

```json
{
  "userId": "uuid",
  "email": "user@example.com",
  "username": "user"
}
```

### `GET /api/addin/papers?q=keyword`

文献検索。

Response:

```json
{
  "items": [
    {
      "id": "paper_123",
      "title": "Sample Paper",
      "authors": "Suzuki, Sato",
      "journal": "Journal A",
      "year": 2024,
      "doi": "10.1000/xyz"
    }
  ]
}
```

### `GET /api/addin/papers/:id`

1件の文献詳細取得。

### `POST /api/addin/citations/format`

本文用 citation を整形。

Request:

```json
{
  "style": "apa",
  "items": [
    {
      "paperId": "paper_123",
      "locator": "p. 25",
      "prefix": "",
      "suffix": ""
    }
  ]
}
```

Response:

```json
{
  "text": "(Suzuki, 2024, p. 25)",
  "items": [
    {
      "paperId": "paper_123",
      "renderedText": "(Suzuki, 2024, p. 25)"
    }
  ]
}
```

### `POST /api/addin/bibliography/format`

参考文献一覧を整形。

Request:

```json
{
  "style": "apa",
  "paperIds": ["paper_123", "paper_456"]
}
```

Response:

```json
{
  "title": "References",
  "entries": [
    "Suzuki, T. (2024). Sample Paper. Journal A.",
    "Sato, H. (2023). Another Paper. Journal B."
  ]
}
```

## 推奨レスポンス設計

- Add-in で直接描画しやすい最小 JSON にする
- citation と bibliography は同じ style enum を使う
- paper の内部IDと表示用文字列を分離する

## エラー方針

```json
{
  "error": {
    "code": "PAPER_NOT_FOUND",
    "message": "paper was not found"
  }
}
```

代表例:
- `UNAUTHORIZED`
- `PAPER_NOT_FOUND`
- `STYLE_NOT_SUPPORTED`
- `VALIDATION_ERROR`
