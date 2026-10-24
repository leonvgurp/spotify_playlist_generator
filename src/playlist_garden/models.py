from typing import Literal

from pydantic import BaseModel, Field, model_validator

ALGORITHM_VERSION = "equal-band-v1"


class Artist(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class Track(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    artists: list[Artist] = Field(min_length=1)
    album: str = ""
    isrc: str | None = None
    duration_ms: int = 0
    playable: bool = True

    @property
    def uri(self):
        return f"spotify:track:{self.id}"


class BandInput(BaseModel):
    artist: Artist
    tracks: list[Track] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def belongs_to_artist(self):
        if any(self.artist.id not in {a.id for a in t.artists} for t in self.tracks):
            raise ValueError("Each input song must credit its selected band.")
        return self


class GenerationRequest(BaseModel):
    bands: list[BandInput] = Field(min_length=1, max_length=10)
    count: int = Field(default=50, ge=1, le=200)
    include_inputs: bool = True
    discovery_mode: Literal["adjustable", "relevance"] = "adjustable"
    discovery_percent: int = Field(default=50, ge=0, le=100)
    ordering: Literal["band", "song", "random"] = "random"
    seed: int = Field(default=42, ge=-(2**63), le=2**63 - 1)
    title: str = Field(default="Discovery playlist", max_length=100)

    @model_validator(mode="after")
    def unique_bands(self):
        if len({b.artist.id for b in self.bands}) != len(self.bands):
            raise ValueError("Choose each band only once.")
        return self


class Candidate(BaseModel):
    track: Track
    # Per-band normalized affinity. Provider provenance is kept in the snapshot.
    affinities: dict[str, float] = Field(default_factory=dict)


class Snapshot(BaseModel):
    candidates: list[Candidate]
    captured_at: str
    provider_responses: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
