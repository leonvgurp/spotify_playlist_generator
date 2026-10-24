# Playlist Garden

Annoyed with AI playlist generators and Spotify's built-in playlist tools? Playlist Garden takes a collection of bands and songs, evaluates them as a group, and suggests songs from the connections across the whole collection. Connect your Spotify account to write new private playlists directly. Spotify Premium is required for the development app's owner under [Spotify's API rules](https://developer.spotify.com/documentation/web-api/concepts/quota-modes).

## Install

Install [Pixi](https://pixi.prefix.dev/latest/installation/), then clone the repository and install its pinned environment:

```sh
git clone https://github.com/leonvgurp/spotify_playlist_generator.git
cd spotify_playlist_generator
pixi install --locked
```

Apple Silicon macOS and Linux x86-64 are supported. Complete the [one-time Spotify and Last.fm API setup in INIT.md](INIT.md) before starting the app.

## Run and connect

From the repository root:

```sh
pixi run dev
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000), click **Connect Spotify**, and sign in with the account allowed in your Spotify developer app. Approve permission to read and modify private playlists. Spotify returns you to the local app.

Keep the server running during login and use. Stop it with Ctrl+C; restart after changing `.env`. For configuration or login problems, see [INIT.md](INIT.md#registration-and-login-troubleshooting).

To check Spotify search and Last.fm similarity, run this in a second terminal:

```sh
pixi run smoke
```

A successful check reports `PASS`. Missing configuration or login returns exit code `2`. This check does not create a playlist.

## Options and workflow

1. Search for up to **10 bands or artists** and optionally choose up to **10 songs per artist**. Spotify artist/track links and URIs also work.
2. Set the playlist title, **song count (1–200)**, and integer **random seed** (default `42`).
3. Generate a preview, review the suggestions, and replace or remove songs.
4. Click **Save to Spotify** to create a new private playlist. CSV and JSON downloads are also available. Generating a preview never creates a Spotify playlist automatically.

| Option | What it does |
| --- | --- |
| **Include all input songs** | On by default: reserves a place for every unique selected recording. When off, input songs can still appear but have no guaranteed place. |
| **Choose the mix** | Sets the share of recommended songs from bands you did not supply. With mandatory inputs, it applies to the remaining places; otherwise, it applies to the whole playlist. Fractional quotas round to the nearest song, with halves rounded up. |
| **Let relevance decide** | Selects without a quota for other bands. |
| **Order the playlist** | Sorts by band or song, or uses a seeded shuffle. Title and ordering do not affect membership. |
| **Random seed** | Resolves score ties and controls shuffling. Different seeds do not necessarily change which songs are selected. |

Mandatory input songs stay locked in the preview. Removing a recommendation reduces the saved target count by one; replacing it preserves the count and, in adjustable mode, its discovery category.

The preview shows the **saved** title and settings. **Apply settings to saved data** rebuilds it from the same provider snapshot and discards manual edits in the new copy. After changing input bands or songs, use **Refresh recommendations** to fetch current data. If there are too few matches, the app keeps the snapshot so you can reduce the count or adjust the mix without downloading again.

**Reproduce this generation** creates an editable local copy without a Spotify export attached. It reruns the algorithm for an unedited generation, or copies the exact selections of a manually edited preview.

### How recommendations work

Last.fm supplies similar songs, similar artists, and top tracks. Spotify resolves these to recordings in its catalogue. The app combines evidence across your collection, gives each input band an equal voice, rewards songs supported by multiple bands, and reduces repeated band/artist representation.

Artist evidence has an initial weight of 0.4, with decreasing top-track rank; song-similarity evidence has a weight of 0.6, averaged across that band's selected songs. Each band's maximum affinity is normalized to one before selection. This uses listening-based similarity; it does not directly identify listeners who like your entire collection.

## Considerations and technical details

### Results and reproducibility

Snapshots store the inputs, settings, algorithm version, timestamped provider responses, candidates, scores, explanations, and ordered recordings. The same inputs, settings, algorithm version, and snapshot produce the same result without network calls. A live refresh can change results even with the same seed.

Matching requires normalized artist and song names. Uncertain recordings and automatically discovered live, remix, or remastered versions are skipped; explicitly selected versions are allowed. Recordings are deduplicated by ISRC where available, with normalized song/artist identifiers as a fallback. Availability checks are limited to the catalogue information Spotify exposes.

Discovery is bounded to eight similar artists per input band, 30 own-band top tracks, 15 tracks per similar artist, 25 neighbors per seed song, and at most 600 Spotify candidate searches. Provider calls run with concurrency three and a ten-minute deadline. Sparse coverage and conservative matching can cause shortfalls; the app reports these instead of changing the requested count or mix. Progress indicates acquisition, not recommendation quality.

### Local data and Spotify exports

The stack is Python 3.12, FastAPI, and SQLite. `pyproject.toml` defines the environment and tasks; `pixi.lock` pins dependencies.

`data/playlist.sqlite3` holds generation history, provider snapshots, and Spotify tokens. The data directory has private permissions and the database has owner-only permissions, but tokens have no application-level encryption. Protect the computer and its backups. `.env`, data, and caches are ignored by Git; credentials and tokens are never sent to the UI.

Searches go to Spotify, and input artist/song names go to Last.fm. The app does not request your listening history. **Disconnect Spotify** removes local tokens. To delete local history, stop the server and delete the directory configured by `PLAYLIST_DATA_DIR` (default `data`). Playlists already saved to Spotify remain there.

Keep the server on loopback. It includes host restrictions and CSRF protection and is intended for personal local use; public multi-user hosting is outside its scope.

Saving an already exported generation reuses its playlist. Interrupted appends are reconciled with Spotify before retrying. If playlist creation times out, check Spotify and attach the playlist link in the app, or confirm that no playlist exists before resetting the attempt. The app will not overwrite externally edited playlists. Reproduce a completed generation to make changes or create another playlist.

### Validation

```sh
pixi run lint
pixi run test
pixi run smoke
```

Tests use isolated databases and mocked providers to cover selection, replay, matching, authentication, edits, and uncertain writes. They do not establish live API access or recommendation quality. The smoke check verifies real provider access with your credentials.

To also check playlist creation:

```sh
pixi run smoke --write
```

This creates a private one-song playlist called **Playlist Garden integration check** and records its generation for recovery. Delete the test playlist in Spotify when finished.

Recommendation quality still needs listening evaluation: compare several mixed-band profiles against recommendations made independently per band, recording relevance, discovery, and band coverage.

### API references

- Spotify: [search](https://developer.spotify.com/documentation/web-api/reference/search), [create playlist](https://developer.spotify.com/documentation/web-api/reference/create-playlist), [playlist items](https://developer.spotify.com/documentation/web-api/reference/add-items-to-playlist), and [2026 API changes](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide).
- Last.fm: [similar tracks](https://www.last.fm/api/show/track.getSimilar), [similar artists](https://www.last.fm/api/show/artist.getSimilar), and [top tracks](https://www.last.fm/api/show/artist.getTopTracks). Review its [API terms](https://www.last.fm/api/tos) before adapting this personal tool for commercial or research use.
