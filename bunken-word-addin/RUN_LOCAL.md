# Run Local

Node.js なしで、Python だけで試作版 Word Add-in を動かす手順です。

## 1. bunkenn 側 API を起動

```powershell
cd C:\Users\run_r\OneDrive\ドキュメント\bunkenn
python .\addin_local_api.py
```

既定では `http://127.0.0.1:8765` で待ち受けます。

## 2. Add-in の静的ファイルを配信

別ターミナルで:

```powershell
cd C:\Users\run_r\AppData\Local\Packages\Microsoft.MinecraftUWP_8wekyb3d8bbwe\LocalState\games\com.mojang\development_behavior_packs\bunken-word-addin
python -m http.server 3001 --tls-cert C:\temp\bunkencert\cert.pem --tls-key C:\temp\bunkencert\key.pem
```

## 3. Manifest の URL を確認

`manifest/manifest.template.xml` は既定で次を向きます。

- `https://localhost:3001/taskpane.html`
- `https://localhost:3001/commands.html`

Windows 上では日本語パスだと TLS 読み込みに失敗することがあるため、証明書は `C:\temp\bunkencert\` の ASCII パスに置いて使う。

## 4. Word に sideload

Word の「挿入」→「アドイン」→「マイ アドイン」→「マイ アドインをアップロード」から
`manifest.template.xml` を読み込みます。

## 5. 動作確認

1. Task pane を開く
2. `clinical` で検索
3. `Sample Clinical Reasoning Paper` を選ぶ
4. 本文に引用を挿入
5. 参考文献を更新

## 注意

- いまは試作版です
- 文献取得元は `papers.db`
- スタイルは固定で `apa`
