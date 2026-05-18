# Deployment

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

## Password Reset

In Supabase Dashboard > Authentication > URL Configuration, add the deployed
Streamlit URL to Redirect URLs. If `PASSWORD_RESET_REDIRECT_URL` is set, use the
same URL there.
