import pytest

from playlist_garden.models import Artist, BandInput, Candidate, GenerationRequest, Snapshot, Track


def track(i, artist=None, **kwargs):
    artist = artist or Artist(id="other", name="Other Band")
    return Track(id=f"{i:022d}", name=f"Song {i:03d}", artists=[artist], isrc=f"ISRC{i}", **kwargs)


@pytest.fixture
def fixture_profile():
    bands = [Artist(id=f"{i:022d}", name=f"Band {i}") for i in range(7)]
    inputs = []
    number = 0
    for i, artist in enumerate(bands):
        songs = []
        for _ in range(4 if i < 2 else 3):
            number += 1
            songs.append(track(number, artist))
        inputs.append(BandInput(artist=artist, tracks=songs))
    candidates = []
    for i in range(1, 161):
        artist = bands[i % 7] if i <= 80 else Artist(id=f"outside-{i % 20}", name=f"New {i % 20}")
        t = track(i, artist)
        # Match seed metadata exactly.
        t = next((s for b in inputs for s in b.tracks if s.id == t.id), t)
        candidates.append(
            Candidate(
                track=t, affinities={b.id: ((i + j) % 10 + 1) / 10 for j, b in enumerate(bands)}
            )
        )
    return GenerationRequest(bands=inputs), Snapshot(
        candidates=candidates, captured_at="2026-10-24T12:00:00Z"
    )
