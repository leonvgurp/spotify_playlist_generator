import random

import pytest
from conftest import track
from pydantic import ValidationError

from playlist_garden.matching import choose_match, recording_key
from playlist_garden.models import Artist, BandInput, GenerationRequest, Snapshot
from playlist_garden.recommendations import ShortageError, normalized_candidates, ordered, select


def ids(rows):
    return [r["track"]["id"] for r in rows]


def test_23_mandatory_plus_27_and_split(fixture_profile):
    spec, snapshot = fixture_profile
    rows = select(spec, snapshot)
    assert len(rows) == len(set(ids(rows))) == 50
    assert sum(r["locked"] for r in rows) == 23
    assert {t.id for b in spec.bands for t in b.tracks} <= set(ids(rows))
    bands = {b.artist.id for b in spec.bands}
    additions = [r for r in rows if not r["locked"]]
    assert (
        sum(not bands.intersection(a["id"] for a in r["track"]["artists"]) for r in additions) == 14
    )


@pytest.mark.parametrize("mode", ["adjustable", "relevance"])
def test_optional_inputs_allow_smaller_count_and_compete(fixture_profile, mode):
    spec, snapshot = fixture_profile
    spec = spec.model_copy(update={"count": 5, "include_inputs": False, "discovery_mode": mode})
    rows = select(spec, snapshot)
    assert len(rows) == 5
    assert not any(r["locked"] for r in rows)
    if mode == "adjustable":
        assert sum(r["track"]["artists"][0]["id"].startswith("outside") for r in rows) == 3


def test_optional_inputs_can_all_or_none_appear(fixture_profile):
    spec, snapshot = fixture_profile
    spec = spec.model_copy(
        update={"count": 3, "include_inputs": False, "discovery_mode": "relevance"}
    )
    inputs = {t.id for b in spec.bands for t in b.tracks}
    for only_inputs in (True, False):
        subset = snapshot.model_copy(
            update={
                "candidates": [
                    c for c in snapshot.candidates if (c.track.id in inputs) == only_inputs
                ]
            }
        )
        rows = select(spec, subset)
        assert all(r["input"] == only_inputs for r in rows)


def test_determinism_reordering_and_title_independence(fixture_profile):
    spec, snapshot = fixture_profile
    before = random.getstate()
    reference = select(spec, snapshot)
    assert reference == select(spec, Snapshot.model_validate_json(snapshot.model_dump_json()))
    reversed_snapshot = snapshot.model_copy(
        update={"candidates": list(reversed(snapshot.candidates))}
    )
    assert reference == select(spec, reversed_snapshot)
    for ordering in ("band", "song", "random"):
        result = select(
            spec.model_copy(update={"ordering": ordering, "title": "Another title"}), snapshot
        )
        assert set(ids(reference)) == set(ids(result))
    assert random.getstate() == before


def test_alphabetical_ties():
    artist = Artist(id="a", name="alpha")
    tracks = [
        track(2, artist).model_copy(update={"name": "Same"}),
        track(1, artist).model_copy(update={"name": "same"}),
    ]
    spec = GenerationRequest(bands=[BandInput(artist=artist)])
    for ordering in ("band", "song"):
        assert [
            t.id for t in ordered(tracks, spec.model_copy(update={"ordering": ordering}))
        ] == sorted(t.id for t in tracks)


def test_shortages_and_duplicate_seed_recordings(fixture_profile):
    spec, snapshot = fixture_profile
    with pytest.raises(ShortageError, match="at least 23"):
        select(spec.model_copy(update={"count": 22}), snapshot)
    with pytest.raises(ShortageError, match="Not enough"):
        select(spec, snapshot.model_copy(update={"candidates": snapshot.candidates[:25]}))
    spec.bands[0].tracks.append(spec.bands[0].tracks[0].model_copy(update={"id": "duplicate"}))
    assert sum(r["locked"] for r in select(spec, snapshot)) == 23


def test_equal_normalization_and_multi_band_support():
    tracks = {"a": track(1), "b": track(2)}
    candidates = normalized_candidates(tracks, {"a": {"one": 10}, "b": {"two": 1}}, ["one", "two"])
    assert candidates[0].affinities["one"] == candidates[1].affinities["two"] == 1


def test_matching_rejects_wrong_and_alternate_recordings():
    artist = Artist(id="a", name="Björk")
    song = track(1, artist).model_copy(update={"name": "Jóga"})
    assert choose_match("Bjork", "Joga", [song]) == song
    assert choose_match("Other band", "Joga", [song]) is None
    assert choose_match("Bjork", "Joga", [song.model_copy(update={"playable": False})]) is None
    live = song.model_copy(update={"name": "Joga - Live"})
    assert choose_match("Bjork", "Joga - Live", [live]) is None
    original = song.model_copy(update={"name": "Live Forever"})
    assert choose_match("Bjork", "Live Forever", [original]) == original
    assert (
        choose_match("Bjork", "Joga", [song, song.model_copy(update={"isrc": "different"})]) is None
    )
    assert recording_key(song) == recording_key(song.model_copy(update={"id": "other"}))


def test_limits_artist_only_and_validation(fixture_profile):
    spec, snapshot = fixture_profile
    artist_only = spec.model_copy(deep=True)
    for band in artist_only.bands:
        band.tracks = []
    assert len(select(artist_only, snapshot)) == 50
    for update in (
        {"count": 201},
        {"bands": []},
        {"bands": spec.bands * 2},
        {"bands": [spec.bands[0]] * 2},
    ):
        with pytest.raises(ValidationError):
            GenerationRequest.model_validate({**spec.model_dump(), **update})
    with pytest.raises(ValidationError):
        BandInput(artist=spec.bands[0].artist, tracks=spec.bands[1].tracks)
    # A full 10x10 input profile is valid.
    bands = [
        BandInput(
            artist=Artist(id=str(i), name=str(i)),
            tracks=[track(i * 10 + j, Artist(id=str(i), name=str(i))) for j in range(10)],
        )
        for i in range(10)
    ]
    assert len(GenerationRequest(bands=bands, count=100).bands) == 10
