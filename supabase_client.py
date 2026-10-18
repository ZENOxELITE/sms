import os
from functools import lru_cache

from supabase import Client, ClientOptions, create_client


def create_supabase_client(access_token: str | None = None) -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_ANON_KEY to connect Supabase.")
    client = create_client(
        url,
        key,
        options=ClientOptions(auto_refresh_token=False, persist_session=False),
    )
    if access_token:
        client.postgrest.auth(access_token)
    return client


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    return create_supabase_client()
