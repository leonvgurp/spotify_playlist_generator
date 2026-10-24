import asyncio
import base64
import hashlib
import re
import secrets
import time
from urllib.parse import urlencode

import httpx

from .models import Artist, Track


class ProviderError(Exception):
    pass


class ProviderHTTPError(ProviderError):
    def __init__(self, provider, status):
        self.status = status
        super().__init__(f"{provider} returned HTTP {status}. Reconnect or try again later.")


async def request_json(client, method, url, *, provider, **kwargs):
    """Retry reads only. Writes with uncertain outcomes must be reconciled first."""
    for attempt in range(3):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.RequestError:
            if method == "GET" and attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            raise ProviderError(f"{provider} could not be reached. Try again later.") from None
        if response.status_code == 429:
            try:
                delay = float(response.headers.get("Retry-After", "2"))
            except ValueError:
                delay = 2
            if method == "GET" and attempt < 2 and 0 <= delay <= 5:
                await asyncio.sleep(delay)
                continue
            raise ProviderError(f"{provider} rate limit reached. Retry after {delay:g} seconds.")
        if response.status_code >= 500 and method == "GET" and attempt < 2:
            await asyncio.sleep(attempt + 1)
            continue
        if response.status_code >= 400:
            raise ProviderHTTPError(provider, response.status_code)
        try:
            return response.json() if response.content else {}
        except ValueError:
            raise ProviderError(f"{provider} returned an invalid response.") from None
    raise ProviderError(f"{provider} request failed.")


def spotify_reference(text, kind):
    text = text.strip()
    match = re.fullmatch(
        rf"(?:spotify:{kind}:|https://open\.spotify\.com/(?:intl-[a-z]+/)?{kind}/)"
        r"([A-Za-z0-9]{22})(?:\?[^\s]*)?",
        text,
    )
    return match.group(1) if match else None


def artist_from(data):
    return Artist(id=data["id"], name=data["name"])


def track_from(data):
    return Track(
        id=data["id"],
        name=data["name"],
        artists=[artist_from(a) for a in data["artists"]],
        album=data.get("album", {}).get("name", ""),
        isrc=data.get("external_ids", {}).get("isrc"),
        duration_ms=data.get("duration_ms", 0),
        playable=data.get("is_playable", True)
        and not data.get("is_local", False)
        and not data.get("restrictions"),
    )


class Spotify:
    base = "https://api.spotify.com/v1"
    token_url = "https://accounts.spotify.com/api/token"

    def __init__(self, settings, store, client):
        self.settings, self.store, self.client = settings, store, client
        self.token_lock = asyncio.Lock()

    def authorization_url(self):
        if not self.settings.spotify_client_id:
            raise ProviderError("Set SPOTIFY_CLIENT_ID in .env first.")
        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(32)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        self.store.put(
            "oauth",
            {
                "state": state,
                "verifier": verifier,
                "expires_at": time.time() + 600,
            },
        )
        return "https://accounts.spotify.com/authorize?" + urlencode(
            {
                "client_id": self.settings.spotify_client_id,
                "response_type": "code",
                "redirect_uri": self.settings.redirect_uri,
                "scope": "playlist-modify-private playlist-read-private",
                "code_challenge_method": "S256",
                "code_challenge": challenge,
                "state": state,
            }
        )

    async def callback(self, code, state):
        pending = self.store.get("oauth", {})
        if (
            not state
            or not secrets.compare_digest(pending.get("state", ""), state)
            or pending.get("expires_at", 0) < time.time()
        ):
            raise ProviderError("Spotify login expired or state did not match. Connect again.")
        self.store.delete("oauth")
        token = await request_json(
            self.client,
            "POST",
            self.token_url,
            provider="Spotify authorization",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.redirect_uri,
                "client_id": self.settings.spotify_client_id,
                "code_verifier": pending["verifier"],
            },
        )
        token["expires_at"] = time.time() + token["expires_in"]
        self.store.put("token", token)

    async def access_token(self, force=False):
        async with self.token_lock:
            token = self.store.get("token")
            if not token:
                raise ProviderError("Connect your Spotify account first.")
            if force or token.get("expires_at", 0) <= time.time() + 60:
                refreshed = await request_json(
                    self.client,
                    "POST",
                    self.token_url,
                    provider="Spotify authorization",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": token["refresh_token"],
                        "client_id": self.settings.spotify_client_id,
                    },
                )
                token.update(refreshed)
                token["expires_at"] = time.time() + token["expires_in"]
                self.store.put("token", token)
            return token["access_token"]

    async def call(self, method, path, **kwargs):
        for attempt in range(2):
            token = await self.access_token(force=attempt == 1)
            try:
                return await request_json(
                    self.client,
                    method,
                    self.base + path,
                    provider="Spotify",
                    headers={"Authorization": f"Bearer {token}"},
                    **kwargs,
                )
            except ProviderHTTPError as exc:
                if exc.status != 401 or attempt:
                    raise

    async def search(self, query, kind):
        reference = spotify_reference(query, kind)
        if reference:
            result = await self.call("GET", f"/{kind}s/{reference}")
            return [artist_from(result) if kind == "artist" else track_from(result)]
        result = await self.call(
            "GET",
            "/search",
            params={
                "q": query,
                "type": kind,
                "limit": 10,
            },
        )
        convert = artist_from if kind == "artist" else track_from
        return [convert(d) for d in result.get(f"{kind}s", {}).get("items", []) if d]


class LastFM:
    def __init__(self, settings, client):
        self.settings, self.client = settings, client

    async def call(self, method, **params):
        if not self.settings.lastfm_api_key:
            raise ProviderError("Set LASTFM_API_KEY in .env first.")
        result = await request_json(
            self.client,
            "GET",
            "https://ws.audioscrobbler.com/2.0/",
            provider="Last.fm",
            params={
                "method": method,
                "api_key": self.settings.lastfm_api_key,
                "format": "json",
                "autocorrect": 1,
                **params,
            },
        )
        if "error" in result:
            # Unknown tracks/artists are a coverage limitation, not an outage.
            if result["error"] == 6:
                return {}
            raise ProviderError(
                f"Last.fm returned error {result['error']}. Check your API key or retry."
            )
        return result
