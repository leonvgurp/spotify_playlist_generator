import asyncio
import time

import httpx
import pytest

from playlist_garden.config import Settings
from playlist_garden.providers import (
    LastFM,
    ProviderError,
    Spotify,
    request_json,
    spotify_reference,
)
from playlist_garden.store import Store


def test_refresh_and_401_retry(tmp_path):
    store = Store(tmp_path)
    store.put(
        "token",
        {"access_token": "old", "refresh_token": "refresh", "expires_at": time.time() + 1000},
    )
    seen = []

    async def handler(request):
        seen.append(request)
        if request.url.path.endswith("token"):
            return httpx.Response(200, json={"access_token": "new", "expires_in": 3600})
        if request.headers["Authorization"] == "Bearer old":
            return httpx.Response(401)
        return httpx.Response(200, json={"id": "me"})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            spotify = Spotify(Settings(spotify_client_id="client"), store, client)
            assert await spotify.call("GET", "/me") == {"id": "me"}

    asyncio.run(scenario())
    assert len(seen) == 3
    assert store.get("token")["refresh_token"] == "refresh"


def test_expired_token_and_pkce(tmp_path):
    store = Store(tmp_path)
    store.put("token", {"access_token": "old", "refresh_token": "r", "expires_at": 0})

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"access_token": "new", "expires_in": 3600})
            )
        ) as client:
            spotify = Spotify(Settings(spotify_client_id="client"), store, client)
            url = spotify.authorization_url()
            assert "code_challenge_method=S256" in url and "client_secret" not in url
            assert await spotify.access_token() == "new"
            with pytest.raises(ProviderError, match="state"):
                await spotify.callback("code", "wrong")

    asyncio.run(scenario())


def test_rate_limit_outages_and_non_retrying_writes(monkeypatch):
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", sleep)

    async def scenario():
        calls = []

        def handler(r):
            calls.append(r)
            return httpx.Response(429, headers={"Retry-After": "2"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ProviderError, match="rate limit"):
                await request_json(client, "GET", "https://example.org", provider="Test")
            assert len(calls) == 3 and sleeps == [2, 2]
            with pytest.raises(ProviderError):
                await request_json(client, "POST", "https://example.org", provider="Test")
            assert len(calls) == 4
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(503))
        ) as client:
            with pytest.raises(ProviderError, match="503"):
                await request_json(client, "GET", "https://example.org", provider="Test")
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"error": 10}))
        ) as client:
            with pytest.raises(ProviderError, match="error 10"):
                await LastFM(Settings(lastfm_api_key="hidden"), client).call(
                    "artist.getSimilar", artist="A"
                )

    asyncio.run(scenario())


def test_spotify_links_are_not_arbitrary_urls():
    identifier = "A" * 22
    assert (
        spotify_reference(f"https://open.spotify.com/artist/{identifier}?si=x", "artist")
        == identifier
    )
    assert spotify_reference(f"spotify:track:{identifier}", "track") == identifier
    assert spotify_reference("https://evil.example/artist/" + identifier, "artist") is None
