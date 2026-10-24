import random
from collections import Counter

from .matching import recording_key
from .models import ALGORITHM_VERSION, Candidate, GenerationRequest, Snapshot


class ShortageError(ValueError):
    def __init__(self, message, available=None):
        super().__init__(message)
        self.available = available or {}


def ordered(tracks, request):
    tracks = sorted(tracks, key=lambda t: t.id)
    if request.ordering == "random":
        random.Random(f"{request.seed}:ordering:{ALGORITHM_VERSION}").shuffle(tracks)
    else:

        def key(t):
            band = t.artists[0].name.casefold()
            song = t.name.casefold()
            return (band, song, t.id) if request.ordering == "band" else (song, band, t.id)

        tracks.sort(key=key)
    return tracks


def select(request: GenerationRequest, snapshot: Snapshot, excluded=None):
    excluded = set(excluded or [])
    bands = {b.artist.id for b in request.bands}
    names = {b.artist.id: b.artist.name for b in request.bands}
    inputs = {t.id: t for b in request.bands for t in b.tracks}
    # Canonical choice must not depend on provider response ordering.
    unique = {}
    for track in sorted(inputs.values(), key=lambda t: t.id):
        unique.setdefault(recording_key(track), track)
    mandatory = list(unique.values()) if request.include_inputs else []
    if len(mandatory) > request.count:
        raise ShortageError(f"Choose at least {len(mandatory)} songs or turn input inclusion off.")
    if any(not t.playable for t in mandatory):
        raise ShortageError(
            "An input song is unavailable. Select another recording or disable inclusion."
        )
    pool = {}
    for candidate in sorted(snapshot.candidates, key=lambda c: c.track.id):
        if candidate.track.id in excluded or not candidate.track.playable:
            continue
        key = recording_key(candidate.track)
        if key not in pool:
            pool[key] = candidate.model_copy(deep=True)
        else:
            for band, value in candidate.affinities.items():
                pool[key].affinities[band] = max(pool[key].affinities.get(band, 0), value)
    for track in mandatory:
        pool.pop(recording_key(track), None)
    candidates = list(pool.values())

    def outside(t):
        return not bands.intersection(a.id for a in t.artists)

    needed = request.count - len(mandatory)
    new_target = (needed * request.discovery_percent + 50) // 100
    targets = {True: new_target, False: needed - new_target}
    available = Counter(outside(c.track) for c in candidates)
    if len(candidates) < needed or (
        request.discovery_mode == "adjustable"
        and any(available[category] < count for category, count in targets.items())
    ):
        raise ShortageError(
            f"Not enough eligible recordings: {available[False]} from supplied bands, "
            f"{available[True]} from other bands for {needed} generated places. "
            "Reduce the size, change the discovery percentage, choose relevance mode, "
            "or add more input bands/songs.",
            {"supplied_bands": available[False], "other_bands": available[True]},
        )
    rng = random.Random(f"{request.seed}:selection:{ALGORITHM_VERSION}")
    tie = {c.track.id: rng.random() for c in sorted(candidates, key=lambda c: c.track.id)}
    representation = Counter()
    artist_counts = Counter()
    chosen = list(mandatory)
    picked = Counter()
    explanations = {t.id: "Selected input · mandatory" for t in mandatory}
    while len(chosen) < request.count:
        eligible = [
            c
            for c in candidates
            if request.discovery_mode == "relevance"
            or picked[outside(c.track)] < targets[outside(c.track)]
        ]

        def score(c):
            support = sum(c.affinities.get(b, 0) > 0 for b in bands)
            affinity = sum(
                c.affinities.get(b, 0) / (1 + representation[b]) for b in sorted(bands)
            ) / len(bands)
            repetition = max((artist_counts[a.id] for a in c.track.artists), default=0)
            return affinity * (1 + 0.15 * max(0, support - 1)) / (1 + 0.3 * repetition)

        winner = max(eligible, key=lambda c: (score(c), tie[c.track.id], c.track.id))
        chosen.append(winner.track)
        candidates.remove(winner)
        picked[outside(winner.track)] += 1
        total = sum(winner.affinities.get(b, 0) for b in sorted(bands))
        for band in sorted(bands):
            representation[band] += winner.affinities.get(band, 0) / total if total else 0
        artist_counts.update(a.id for a in winner.track.artists)
        linked = [names[b] for b in sorted(bands) if winner.affinities.get(b, 0) > 0]
        explanations[winner.track.id] = "Linked to " + ", ".join(linked)
    input_keys = set(unique)
    return [
        {
            "track": t.model_dump(),
            "input": recording_key(t) in input_keys,
            "locked": any(recording_key(t) == recording_key(m) for m in mandatory),
            "explanation": explanations[t.id],
        }
        for t in ordered(chosen, request)
    ]


def document(request, snapshot):
    return {
        "request": request.model_dump(),
        "snapshot": snapshot.model_dump(),
        "algorithm_version": ALGORITHM_VERSION,
        "tracks": select(request, snapshot),
        "status": "ready",
        "export": {},
        "excluded": [],
        "edited": False,
    }


def normalized_candidates(tracks, signals, band_ids):
    """Normalize each band's maximum to one, irrespective of its number of seeds."""
    maxima = {b: max((s.get(b, 0) for s in signals.values()), default=0) for b in band_ids}
    return [
        Candidate(
            track=tracks[key],
            affinities={
                b: signals[key].get(b, 0) / maxima[b] for b in sorted(band_ids) if maxima[b]
            },
        )
        for key in sorted(tracks)
    ]
