import asyncio

import httpx

from playlist_garden.config import Settings
from playlist_garden.providers import Spotify
from playlist_garden.store import Store


def search_with(tmp_path, responses, query="NOFX"):
    calls = []

    class SearchSpotify(Spotify):
        async def call(self, method, path, **kwargs):
            calls.append((path, kwargs.get("params", {}).get("q")))
            return responses[len(calls) - 1]

    async def scenario():
        async with httpx.AsyncClient() as client:
            spotify = SearchSpotify(Settings(), Store(tmp_path), client)
            return await spotify.search(query, "artist")

    return asyncio.run(scenario()), calls


def artists(*names):
    return {"artists": {"items": [{"id": name, "name": name} for name in names]}}


def test_exact_artist_precedes_related_and_prefix_matches(tmp_path):
    result, calls = search_with(tmp_path, [artists("Pennywise", "NOFXCE", "NOFX")])
    assert [a.name for a in result] == ["NOFX", "NOFXCE", "Pennywise"]
    assert calls == [("/search", 'artist:"NOFX"')]


def test_fallback_finds_exact_and_deduplicates(tmp_path):
    result, calls = search_with(
        tmp_path, [artists("NOFXCE"), artists("Pennywise", "NOFX", "NOFXCE")]
    )
    assert [a.name for a in result] == ["NOFX", "NOFXCE", "Pennywise"]
    assert calls == [("/search", 'artist:"NOFX"'), ("/search", "NOFX")]


def test_case_accents_and_typo_fallback(tmp_path):
    result, calls = search_with(tmp_path, [artists("Bj\u00f6rk")], "  bjork  ")
    assert result[0].name == "Bj\u00f6rk" and len(calls) == 1
    result, calls = search_with(tmp_path, [artists(), artists("Green Day", "NOFX")], "NOFXx")
    assert result[0].name == "NOFX" and len(calls) == 2


def test_artist_link_bypasses_search(tmp_path):
    identifier = "A" * 22
    result, calls = search_with(
        tmp_path,
        [{"id": identifier, "name": "NOFX"}],
        f"https://open.spotify.com/artist/{identifier}",
    )
    assert result[0].name == "NOFX"
    assert calls == [(f"/artists/{identifier}", None)]
