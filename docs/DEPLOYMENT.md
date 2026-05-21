# Deployment

This document covers the Streamlit web app. The Word add-in deployment is in
the `word_addin` repository at `docs/DEPLOYMENT.md`.

## Streamlit Cloud

This app can run without a local PC by deploying the `main` branch to Streamlit
Cloud.

Use these settings:

- Repository: `luka8267/bunken`
- Branch: `main`
- Main file path: `app.py`

Set these Streamlit secrets:

```toml
SUPABASE_URL = "https://udhgdndfcmdgpnxpksvo.supabase.co"
SUPABASE_KEY = "<Supabase anon or publishable key>"

# Optional. Set this to the deployed Streamlit URL after deployment.
PASSWORD_RESET_REDIRECT_URL = "https://<your-streamlit-app>.streamlit.app"
```

Do not set a Supabase service-role key in Streamlit. The app runs as a user
client and should use the anon/publishable key with RLS.

## Supabase

Before deploying, confirm the database migrations on `main` have been applied.
When changing database schema, take a backup first and keep the rollback path in
`docs/DB_BACKUP_RUNBOOK.md`.

Recommended release flow:

```powershell
git pull --ff-only
supabase migration list
python -m py_compile app.py paper_utils.py auth_utils.py tests\test_paper_utils.py
python -m unittest discover -s tests -v
```

If migrations are pending:

1. Create a DB backup from the repository root.
2. Review each SQL file under `supabase/migrations/`.
3. Apply migrations through the established Supabase workflow.
4. Run verification SQL and smoke tests.
5. Record backup file names and migration versions in the release notes.

## Password Reset

In Supabase Dashboard > Authentication > URL Configuration, add the deployed
Streamlit URL to Redirect URLs. If `PASSWORD_RESET_REDIRECT_URL` is set, use the
same URL there.

## Local deployment check

Run the app locally before release:

```powershell
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
curl.exe -I http://127.0.0.1:8501
```

Expected result is `HTTP/1.1 200 OK`.

## Production smoke test

After Streamlit Cloud deploys `main`:

- open the production app
- log in
- open `一覧`
- open `PDF読書`
- open `インポート` and confirm previews render
- open `重複確認` and confirm history loads
- open `文書引用` and confirm synced documents load

If any step fails, check Streamlit logs, then Supabase API/Postgres logs.
