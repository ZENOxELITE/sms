"""Supabase access for the portal.

Creating a full ``supabase.create_client`` costs 0.7-1.5 s (it builds several
HTTP clients and TLS contexts), and every new connection pays a fresh TLS
handshake on its first query. The portal therefore keeps ONE pooled HTTP
connection for the whole process and builds lightweight per-user clients on
top of it. Each request still carries its own ``Authorization`` header, so
one user's token is never shared with another request.
"""

import os
import threading
from functools import lru_cache

import httpx
from postgrest import SyncPostgrestClient
from supabase_auth import SyncGoTrueClient

_http_lock = threading.Lock()
_http_client: httpx.Client | None = None


def _settings() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_ANON_KEY to connect Supabase.")
    return url.rstrip("/"), key


def shared_http_client() -> httpx.Client:
    """One keep-alive connection pool reused by every Supabase call."""
    global _http_client
    with _http_lock:
        if _http_client is None:
            _http_client = httpx.Client(
                # HTTP/1.1: idle HTTP/2 connections can fail on reuse (WinError 10035
                # on Windows). Limits live on the transport because it is set explicitly.
                transport=httpx.HTTPTransport(
                    http2=False,
                    retries=1,
                    limits=httpx.Limits(
                        max_connections=40,
                        max_keepalive_connections=20,
                        keepalive_expiry=60,
                    ),
                ),
                follow_redirects=True,
                timeout=httpx.Timeout(20.0, connect=10.0),
            )
        return _http_client


class SupabaseClient:
    """The parts of the Supabase client the portal uses: tables and auth."""

    def __init__(self, access_token: str | None = None):
        url, key = _settings()
        self._url = url
        self._key = key
        self.postgrest = SyncPostgrestClient(
            f"{url}/rest/v1",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "apikey": key,
                "Authorization": f"Bearer {access_token or key}",
            },
            http_client=shared_http_client(),
        )
        self._auth: SyncGoTrueClient | None = None

    def table(self, name: str):
        return self.postgrest.from_(name)

    @property
    def auth(self) -> SyncGoTrueClient:
        if self._auth is None:
            self._auth = SyncGoTrueClient(
                url=f"{self._url}/auth/v1",
                headers={"apikey": self._key, "Authorization": f"Bearer {self._key}"},
                auto_refresh_token=False,
                persist_session=False,
                http_client=shared_http_client(),
            )
        return self._auth


def create_supabase_client(access_token: str | None = None) -> SupabaseClient:
    return SupabaseClient(access_token)


@lru_cache(maxsize=1)
def get_supabase_client() -> SupabaseClient:
    return create_supabase_client()
