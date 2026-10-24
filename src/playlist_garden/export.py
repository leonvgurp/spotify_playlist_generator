import re

from .providers import ProviderError, ProviderHTTPError


class Exporter:
    def __init__(self, store, spotify):
        self.store, self.spotify = store, spotify

    async def save(self, doc):
        if len(doc["tracks"]) != doc["request"]["count"] or doc["status"] != "ready":
            raise ValueError("Complete the playlist preview before saving.")
        title = doc["request"]["title"].strip()
        if not title:
            raise ValueError("Enter a playlist title before saving.")
        state = doc["export"]
        if state.get("status") == "complete":
            return state
        if state.get("status") in {"creating", "uncertain"} and not state.get("playlist_id"):
            raise ProviderError(
                "Spotify may have created the playlist before the connection failed. "
                "Check Spotify, then attach its playlist link to resume safely. "
                "If no playlist exists, explicitly reset the export attempt."
            )
        if not state.get("playlist_id"):
            state["status"] = "creating"
            self.store.save(doc)
            try:
                created = await self.spotify.call(
                    "POST",
                    "/me/playlists",
                    json={
                        "name": title,
                        "public": False,
                        "description": f"Playlist Garden · generation {doc['id']}",
                    },
                )
            except ProviderError as exc:
                state["status"] = (
                    "not_created"
                    if isinstance(exc, ProviderHTTPError) and exc.status < 500
                    else "uncertain"
                )
                self.store.save(doc)
                raise
            state.update(
                playlist_id=created["id"],
                status="writing",
                url=f"https://open.spotify.com/playlist/{created['id']}",
            )
            self.store.save(doc)
        playlist_id = state["playlist_id"]
        expected = [f"spotify:track:{row['track']['id']}" for row in doc["tracks"]]
        existing = []
        offset = 0
        while True:
            page = await self.spotify.call(
                "GET", f"/playlists/{playlist_id}/items", params={"limit": 100, "offset": offset}
            )
            for entry in page.get("items", []):
                item = entry.get("item") or entry.get("track") or {}
                existing.append(item.get("uri"))
            if not page.get("next"):
                break
            offset += len(page["items"])
            if offset > 1000:
                raise ProviderError("Unexpected playlist size. Export stopped for inspection.")
        if existing != expected[: len(existing)] or len(existing) > len(expected):
            raise ProviderError(
                "Spotify playlist was edited externally. Export stopped to preserve it."
            )
        # Re-read on every retry: a timeout may mean the previous append succeeded.
        for start in range(len(existing), len(expected), 100):
            await self.spotify.call(
                "POST",
                f"/playlists/{playlist_id}/items",
                json={"uris": expected[start : start + 100]},
            )
        state["status"] = "complete"
        self.store.save(doc)
        return state

    async def recover(self, doc, reference):
        state = doc["export"]
        if state.get("playlist_id") or state.get("status") not in {"creating", "uncertain"}:
            raise ValueError("Only an uncertain creation can be recovered.")
        match = re.fullmatch(
            r"(?:https://open\.spotify\.com/playlist/|spotify:playlist:)?([A-Za-z0-9]{22})(?:\?\S*)?",
            reference.strip(),
        )
        if not match:
            raise ValueError("Enter a Spotify playlist link or ID.")
        playlist_id = match.group(1)
        playlist = await self.spotify.call("GET", f"/playlists/{playlist_id}")
        me = await self.spotify.call("GET", "/me")
        if (
            playlist.get("owner", {}).get("id") != me["id"]
            or f"generation {doc['id']}" not in playlist.get("description", "")
            or playlist.get("public") is not False
        ):
            raise ValueError(
                "Use the private playlist created for this generation in your account."
            )
        state.update(
            playlist_id=playlist_id,
            status="writing",
            url=f"https://open.spotify.com/playlist/{playlist_id}",
        )
        self.store.save(doc)
