# bunken

## Password reset setup

In Supabase Dashboard > Authentication > URL Configuration, add the app URL to
Redirect URLs. If the reset destination should be explicit, add this Streamlit
secret:

```toml
PASSWORD_RESET_REDIRECT_URL = "https://your-app-url.example.com"
```
