import asyncio

from conftest import track

from playlist_garden.discovery import Discovery
from playlist_garden.models import Artist, BandInput, GenerationRequest


def test_discovery_provenance_and_equal_band_pool():
    a, b = Artist(id="a", name="Alpha"), Artist(id="b", name="Beta")
    seed = track(1, a).model_copy(update={"name": "Seed"})

    class FM:
        async def call(self, method, **params):
            if method == "artist.getSimilar":
                return {"similarartists": {"artist": [{"name": "Other", "match": "0.8"}]}}
            if method == "artist.getTopTracks":
                return {"toptracks": {"track": [{"name": "Shared"}]}}
            return {
                "similartracks": {
                    "track": [{"name": "Shared", "artist": {"name": "Other"}, "match": "0.9"}]
                }
            }

    class Spotify:
        async def search(self, query, kind):
            artist = (
                a
                if '"Alpha"' in query
                else b
                if '"Beta"' in query
                else Artist(id="o", name="Other")
            )
            i = {"a": 2, "b": 3, "o": 4}[artist.id]
            return [track(i, artist).model_copy(update={"name": "Shared"})]

    async def scenario():
        spec = GenerationRequest(bands=[BandInput(artist=a, tracks=[seed]), BandInput(artist=b)])
        result = await Discovery(Spotify(), FM()).collect(spec, lambda m: None)
        assert len(result.candidates) == 4
        assert any(c.track.id == seed.id for c in result.candidates)
        shared = next(c for c in result.candidates if c.track.artists[0].id == "o")
        assert all(shared.affinities[b] > 0 for b in ("a", "b"))
        assert result.provider_responses and "api_key" not in str(result.provider_responses)

    asyncio.run(scenario())
