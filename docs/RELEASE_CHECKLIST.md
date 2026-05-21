# Release checklist

Use this checklist before pushing or deploying a production release.

## 1. Confirm scope

- Confirm the release branch is `main`.
- Confirm unrelated local files are not staged.
- Confirm whether the release changes DB schema or data.
- If DB changes are included, create a backup first.

```powershell
git status --short --branch
supabase migration list
```

## 2. Backup when needed

Required for:

- Supabase migration
- SQL data repair
- backfill
- delete/update operation
- storage path repair

Follow `docs/DB_BACKUP_RUNBOOK.md` and record the backup file name.

## 3. Web app checks

```powershell
python -m py_compile app.py paper_utils.py auth_utils.py tests\test_paper_utils.py
python -m unittest discover -s tests -v
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
curl.exe -I http://127.0.0.1:8501
```

Manual smoke test:

- login
- add/search/list a paper
- open 3-pane list
- open PDF reading page
- run import preview without importing
- open duplicate history
- open document citation view

## 4. Word add-in checks

From `C:\Users\run_r\OneDrive\ドキュメント\word_addin\word_addin`:

```powershell
python -m py_compile `
  api\_bunken_vercel.py `
  bunkenn\word-app\api\shared\data_access.py `
  bunkenn\word-app\api\shared\bunken_service.py `
  bunkenn\word-app\api\shared\bunken_models.py
python -m unittest discover -s tests -v
node --check bunkenn\word-app\static\taskpane.js
npm run build
```

Manual smoke test:

- Word add-in loads
- login works
- search works by title, DOI, tag, and collection
- citation insert works
- reference list update does not duplicate old bibliography blocks
- style switching updates existing citations
- document citation sync shows context count

## 5. Deploy

Web app:

- Push `bunken/main`.
- Let Streamlit Cloud deploy.
- Check production app logs.

Word add-in:

- Push `word_addin/main`.
- Let Vercel deploy.
- Check:

```powershell
curl.exe -L "https://word-addin-sooty.vercel.app/taskpane.html"
curl.exe -L "https://word-addin-sooty.vercel.app/api/addin/papers?_debug=version"
```

## 6. Release notes

Record:

- commit hashes for `bunken` and `word_addin`
- migrations applied
- backup file name, if any
- smoke test result
- known risks or manual follow-up
