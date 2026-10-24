import asyncio

import pytest

from playlist_garden.export import Exporter
from playlist_garden.providers import ProviderError
from playlist_garden.recommendations import document
from playlist_garden.store import Store


class FakeSpotify:
    def __init__(self):
        self.creates = 0
        self.items = []
        self.append_timeout = True
        self.create_timeout = False

    async def call(self, method, path, **kwargs):
        if path == "/me/playlists":
            self.creates += 1
            if self.create_timeout:
                raise ProviderError("Connection lost after creation")
            return {"id": "A" * 22}
        if method == "GET":
            return {"items": [{"item": {"uri": uri}} for uri in self.items], "next": None}
        self.items.extend(kwargs["json"]["uris"])
        if self.append_timeout:
            self.append_timeout = False
            raise ProviderError("Connection lost after append")
        return {"snapshot_id": "s"}


def test_export_reconciles_append_timeout_without_duplicate(tmp_path, fixture_profile):
    store, spotify = Store(tmp_path), FakeSpotify()
    doc = store.save(document(*fixture_profile))
    exporter = Exporter(store, spotify)

    async def scenario():
        with pytest.raises(ProviderError):
            await exporter.save(doc)
        recovered = store.generation(doc["id"])
        result = await exporter.save(recovered)
        assert result["status"] == "complete"
        await exporter.save(store.generation(doc["id"]))
        assert spotify.creates == 1
        assert len(spotify.items) == len(set(spotify.items)) == 50

    asyncio.run(scenario())


def test_uncertain_create_requires_explicit_recovery(tmp_path, fixture_profile):
    store, spotify = Store(tmp_path), FakeSpotify()
    spotify.create_timeout = True
    doc = store.save(document(*fixture_profile))
    exporter = Exporter(store, spotify)

    async def scenario():
        with pytest.raises(ProviderError):
            await exporter.save(doc)
        doc2 = store.generation(doc["id"])
        assert doc2["export"]["status"] == "uncertain"
        with pytest.raises(ProviderError, match="may have created"):
            await exporter.save(doc2)
        assert spotify.creates == 1

    asyncio.run(scenario())


def test_export_preserves_external_edits(tmp_path, fixture_profile):
    store, spotify = Store(tmp_path), FakeSpotify()
    spotify.items = ["spotify:track:external"]
    doc = store.save(document(*fixture_profile))

    async def scenario():
        with pytest.raises(ProviderError, match="edited externally"):
            await Exporter(store, spotify).save(doc)

    asyncio.run(scenario())
    assert spotify.items == ["spotify:track:external"]
