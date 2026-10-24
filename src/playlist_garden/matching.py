import re
import unicodedata

from .models import Track


def normalized(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        re.findall(r"[^\W_]+", "".join(c for c in value if not unicodedata.combining(c)))
    )


def recording_key(track: Track):
    if track.isrc:
        return "isrc:" + track.isrc.upper()
    # Conservative name-based backup when the catalogue does not expose an ISRC.
    title = re.sub(r"\s*[-(]\s*(?:\d{4}\s+)?remaster(?:ed)?.*$", "", track.name, flags=re.I)
    return "name:" + normalized(title) + ":" + ",".join(sorted(a.id for a in track.artists))


def alternate_version(title):
    return bool(
        re.search(
            r"(?:\s[-–—]\s|\()[^()]*(?:\blive\b|\bremaster(?:ed)?\b|\bremix\b|"
            r"\bacoustic\b|\binstrumental\b|\bkaraoke\b|\bdemo\b|\bedit\b)",
            title,
            re.I,
        )
    )


def choose_match(artist, title, results):
    """Require exact normalized artist/title; do not guess between uncertain recordings."""
    valid = [
        t
        for t in results
        if t.playable
        and normalized(t.name) == normalized(title)
        and any(normalized(a.name) == normalized(artist) for a in t.artists)
        and not alternate_version(t.name)
    ]
    if not valid:
        return None
    keys = {recording_key(t) for t in valid}
    if len(keys) != 1:
        return None
    return min(valid, key=lambda t: t.id)
