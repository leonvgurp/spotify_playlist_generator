import asyncio
from collections import defaultdict
from datetime import UTC, datetime

from .matching import choose_match, normalized
from .models import Snapshot
from .providers import ProviderError
from .recommendations import normalized_candidates


async def together(*coroutines):
    tasks = [asyncio.create_task(c) for c in coroutines]
    try:
        return await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def entries(payload, container, item):
    value = payload.get(container, {}).get(item, [])
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []


class Discovery:
    """Bounded live acquisition; ranking itself performs no network requests."""

    def __init__(self, spotify, lastfm):
        self.spotify, self.lastfm = spotify, lastfm

    async def collect(self, request, progress):
        raw = []
        proposals = {}
        signals = defaultdict(lambda: defaultdict(float))
        semaphore = asyncio.Semaphore(3)

        async def fm(method, **params):
            async with semaphore:
                result = await self.lastfm.call(method, **params)
                raw.append(
                    {"provider": "lastfm", "method": method, "params": params, "response": result}
                )
                return result

        def propose(artist, title, band, score):
            if not artist or not title or score <= 0:
                return
            key = (normalized(artist), normalized(title))
            proposals.setdefault(key, (artist, title))
            signals[key][band] += score

        async def band_candidates(band):
            band_id, name = band.artist.id, band.artist.name
            own = await fm("artist.getTopTracks", artist=name, limit=30)
            for i, track in enumerate(entries(own, "toptracks", "track")):
                propose(name, track["name"], band_id, 0.4 / (1 + i / 10))
            similar = await fm("artist.getSimilar", artist=name, limit=8)
            for artist in entries(similar, "similarartists", "artist"):
                tops = await fm("artist.getTopTracks", artist=artist["name"], limit=15)
                affinity = max(0, min(1, float(artist.get("match", 0))))
                for i, track in enumerate(entries(tops, "toptracks", "track")):
                    propose(artist["name"], track["name"], band_id, 0.4 * affinity / (1 + i / 10))
            for seed in band.tracks:
                # A seed is eligible, not guaranteed, when inclusion is disabled.
                propose(name, seed.name, band_id, 0.6 / len(band.tracks))
                result = await fm("track.getSimilar", artist=name, track=seed.name, limit=25)
                for track in entries(result, "similartracks", "track"):
                    artist = track.get("artist", {})
                    artist = artist.get("name", "") if isinstance(artist, dict) else artist
                    propose(
                        artist,
                        track["name"],
                        band_id,
                        0.6 * max(0, min(1, float(track.get("match", 0)))) / len(band.tracks),
                    )

        progress("Discovering songs across your input bands…")
        await together(*(band_candidates(b) for b in request.bands))
        progress("Resolving candidate recordings on Spotify…")
        resolved = {}
        resolved_signals = defaultdict(lambda: defaultdict(float))
        seed_by_key = {
            (normalized(a.name), normalized(t.name)): t
            for band in request.bands
            for t in band.tracks
            for a in t.artists
        }
        # Balance acquisition across bands rather than exhausting a popular band's results.
        band_ids = sorted(b.artist.id for b in request.bands)
        per_band = {b: sorted(proposals, key=lambda k: (-signals[k][b], k)) for b in band_ids}
        queue, seen = [], set()
        for i in range(max((len(v) for v in per_band.values()), default=0)):
            for band in band_ids:
                values = per_band[band]
                if i < len(values) and values[i] not in seen and signals[values[i]][band] > 0:
                    seen.add(values[i])
                    queue.append(values[i])
        # At most 600 searches per run, 3 concurrent. Seeds never consume this budget.
        bounded = list(dict.fromkeys([*seed_by_key, *queue[:600]]))
        rejected = 0
        completed = 0

        async def resolve(key):
            nonlocal rejected, completed
            if key in seed_by_key:
                track = seed_by_key[key]
            else:
                artist, title = proposals[key]
                query = (
                    'artist:"'
                    + artist.replace('"', "")
                    + '" track:"'
                    + title.replace('"', "")
                    + '"'
                )
                async with semaphore:
                    matches = await self.spotify.search(query, "track")
                raw.append(
                    {
                        "provider": "spotify",
                        "query": query,
                        "response": [t.model_dump() for t in matches],
                    }
                )
                track = choose_match(artist, title, matches)
            if track:
                resolved[track.id] = track
                for band, score in signals[key].items():
                    resolved_signals[track.id][band] += score
            else:
                rejected += 1
            completed += 1
            progress(f"Matched {completed}/{len(bounded)} candidates · {len(resolved)} eligible")

        await together(*(resolve(k) for k in bounded))
        if not resolved:
            raise ProviderError("No recordings could be matched. Try different bands or songs.")
        warnings = []
        if rejected:
            warnings.append(f"Skipped {rejected} uncertain, alternate, or unavailable recordings.")
        if len(queue) > 600:
            warnings.append(
                "Candidate search reached its 600-query budget; results use a bounded pool."
            )
        return Snapshot(
            candidates=normalized_candidates(resolved, resolved_signals, band_ids),
            captured_at=datetime.now(UTC).isoformat(),
            provider_responses=sorted(
                raw, key=lambda r: str((r.get("method"), r.get("params"), r.get("query")))
            ),
            warnings=warnings,
        )
