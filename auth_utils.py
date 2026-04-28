import streamlit as st
from supabase import create_client

try:
    from postgrest.exceptions import APIError
except ImportError:
    APIError = Exception

AUTH_SESSION_KEYS = (
    "access_token",
    "refresh_token",
    "user_id",
    "username",
    "email",
)


def clear_auth_session():
    for key in AUTH_SESSION_KEYS:
        st.session_state.pop(key, None)


def store_auth_session(session):
    st.session_state["access_token"] = session.access_token
    st.session_state["refresh_token"] = session.refresh_token


def build_supabase_client(supabase_url, supabase_key):
    client = create_client(supabase_url, supabase_key)
    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")

    if access_token and refresh_token:
        try:
            auth_response = client.auth.set_session(access_token, refresh_token)
            if getattr(auth_response, "session", None):
                store_auth_session(auth_response.session)
        except Exception:
            clear_auth_session()

    return client


def normalize_email(email):
    return (email or "").strip()


def normalize_username(username):
    return (username or "").strip()


def get_current_user_id():
    return st.session_state["user_id"]


def get_username_from_user(user):
    metadata = getattr(user, "user_metadata", None) or {}
    username = metadata.get("username")
    if username:
        return username

    email = getattr(user, "email", "") or ""
    if email and "@" in email:
        return email.split("@", maxsplit=1)[0]

    return "ユーザー"


def fetch_profile_username(supabase, user_id):
    try:
        result = (
            supabase.table("profiles")
            .select("username")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
    except APIError:
        return None

    if not result.data:
        return None
    return result.data[0].get("username")


def sync_profile_for_user(supabase, user, username=None):
    profile_username = username or fetch_profile_username(supabase, user.id) or get_username_from_user(user)

    try:
        (
            supabase.table("profiles")
            .upsert({"id": user.id, "username": profile_username})
            .execute()
        )
    except APIError:
        return get_username_from_user(user)

    return profile_username


def set_authenticated_user(supabase, user, username=None):
    st.session_state["user_id"] = user.id
    st.session_state["email"] = getattr(user, "email", "") or ""
    st.session_state["username"] = username or sync_profile_for_user(supabase, user)


def register_user(supabase, email, password, username):
    return supabase.auth.sign_up(
        {
            "email": email,
            "password": password,
            "options": {"data": {"username": username}},
        }
    )


def login_user(supabase, email, password):
    return supabase.auth.sign_in_with_password(
        {
            "email": email,
            "password": password,
        }
    )


def request_password_reset(supabase, email, redirect_to=None):
    options = {"redirect_to": redirect_to} if redirect_to else None
    return supabase.auth.reset_password_for_email(email, options)


def verify_password_reset_token(supabase, token_hash):
    return supabase.auth.verify_otp(
        {
            "token_hash": token_hash,
            "type": "recovery",
        }
    )


def update_password(supabase, password):
    return supabase.auth.update_user({"password": password})


def sign_out_user(supabase):
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    clear_auth_session()
