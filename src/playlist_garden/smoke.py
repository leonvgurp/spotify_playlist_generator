"""Explicit live integration check. Playlist writes require --write."""

import argparse
import asyncio

import httpx

from .config import Settings
from .providers import LastFM, ProviderError, Spotify
from .store import Store


async def check(write=False):
    settings = Settings.load()
    if not settings.spotify_client_id or not settings.lastfm_api_key:
        print(
            "Live smoke check unavailable: configure SPOTIFY_CLIENT_ID and LASTFM_API_KEY in .env."
        )
        return 2
    store = Store(settings.data_dir)
    if not store.get("token"):
        print("Live smoke check unavailable: connect Spotify in the web app first.")
        return 2
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            spotify, lastfm = Spotify(settings, store, client), LastFM(settings, client)
            results = await spotify.search(
                'artist:"Radiohead" track:"Weird Fishes/Arpeggi"', "track"
            )
            if not results:
                raise ProviderError("Spotify search returned no test recordings.")
            similar = await lastfm.call(
                "track.getSimilar", artist="Radiohead", track="Weird Fishes/Arpeggi", limit=5
            )
            if not similar.get("similartracks", {}).get("track"):
                raise ProviderError("Last.fm returned no test similarities.")
            print("PASS: authenticated Spotify search and Last.fm track similarity.")
            if write:
                # A stable generation ID makes uncertain writes recoverable in the regular UI.
                from datetime import UTC, datetime

                from .export import Exporter
                from .models import Artist, BandInput, Candidate, GenerationRequest, Snapshot
                from .recommendations import document

                track = results[0]
                spec = GenerationRequest(
                    bands=[
                        BandInput(artist=Artist.model_validate(track.artists[0]), tracks=[track])
                    ],
                    count=1,
                    title="Playlist Garden integration check",
                )
                doc = store.save(
                    document(
                        spec,
                        Snapshot(
                            candidates=[
                                Candidate(track=track, affinities={track.artists[0].id: 1})
                            ],
                            captured_at=datetime.now(UTC).isoformat(),
                        ),
                    )
                )
                print(f"Test generation recorded: {doc['id']}")
                exported = await Exporter(store, spotify).save(doc)
                print(f"PASS: created a private one-song test playlist: {exported['url']}")
            else:
                print(
                    "Playlist creation not exercised. Use pixi run smoke --write to create a private test playlist."
                )
            return 0
    except ProviderError as exc:
        print(f"FAIL: {exc}")
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="Create a private one-song test playlist"
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(check(args.write)))


if __name__ == "__main__":
    main()
