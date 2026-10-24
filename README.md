# Playlist Garden

A personal web app that grows a playlist from a collection of bands and songs. Give each band an equal voice, keep your input songs or use them only as inspiration, and discover connections across the whole collection.

Python 3.12 · FastAPI · SQLite · Last.fm discovery · Spotify catalogue and private playlists.

## Setup

Install [Pixi](https://pixi.prefix.dev/latest/installation/). The supported environments are Apple Silicon macOS and Linux x86-64. All project configuration lives in `pyproject.toml`; `pixi.lock` pins the environments.

From this directory:

```sh
pixi install --locked
cp .env.example .env
```

Complete these manual prerequisites:

1. Sign into the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) with a **Premium** account and create a Web API app. New development apps permit at most five authorized users; this tool is intended for your own account.
2. Register **exactly** `http://127.0.0.1:8000/auth/callback` as a redirect URI. Use the IP address, not `localhost`. Add your Spotify account under the app's user access settings if required.
3. Copy the app's **Client ID** into `SPOTIFY_CLIENT_ID` in `.env`. A client secret is not needed: this app uses Authorization Code with PKCE.
4. [Create a Last.fm API account/key](https://www.last.fm/api/account/create) and put the **API key** in `LASTFM_API_KEY`. Last.fm account authentication and its shared secret are not needed.

Your `.env` should look like this, with your own values:

```dotenv
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8000/auth/callback
LASTFM_API_KEY=your_lastfm_api_key
PLAYLIST_DATA_DIR=data
```

Start the app:

```sh
pixi run dev
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000), click **Connect Spotify**, and authorize it. Restart the server after changing `.env`. Keep the server bound to loopback; public hosting is outside this version's scope. Stop it with Ctrl+C.

## Make a playlist

1. Search for up to 10 artists and select the correct Spotify result. Optionally select up to 10 songs per artist. Spotify artist/track links and URIs also work.
2. Set a title, song count (1–200), and integer seed (default `42`).
3. **Include all input songs**, on by default, reserves places for every unique selected recording. Turn it off to let input songs compete normally; they can still appear, but none are guaranteed.
4. Choose the discovery mix: **Choose the mix** sets the share of generated places from bands you did not supply; **Let relevance decide** has no quota. When input songs are mandatory, the mix applies only to remaining places. Otherwise it applies to the whole playlist. Fractional quotas round to the nearest song, with halves rounded up.
5. Order by band, song, or a seeded shuffle. Ordering and title do not affect membership.
6. Generate, review, replace recommendations, or remove them. Removing a song reduces the saved target count by one; replacement preserves it and the song's discovery category in adjustable mode. Mandatory inputs stay locked.
7. Click **Save to Spotify** to create a new private playlist. Generation never creates a Spotify playlist automatically. CSV and JSON downloads are available independently.

The preview always shows the **saved** title/settings. After changing the form, click **Apply settings to saved data** to generate a new preview from the same snapshot. Changing the input bands/songs requires **Refresh recommendations**, which fetches current provider data. Shortages retain their snapshots so you can reduce the count or adjust the mix without downloading again.

## Recommendations and reproducibility

Last.fm supplies similar songs (based on listening data), similar artists, and top tracks. Spotify identifies the actual recordings and receives playlist writes. This combines similarity across your profile; it does not directly find individual listeners who like your entire seed combination. New Spotify apps cannot use its recommendation or related-artist endpoints.

The initial scoring model combines artist candidates (0.4 weight, with decreasing top-track rank) with mean song-similarity evidence (0.6 weight, divided by that band's number of selected songs). Each band's maximum affinity is normalized to one. Selection averages equal band contributions, rewards support from multiple bands, and reduces repeated band/artist representation. The seed deterministically resolves score ties and shuffles the final order; it is not a promise that every seed produces different membership.

Every saved generation contains the confirmed inputs, settings, algorithm version, timestamped provider responses, resolved candidates, affinities, explanations, and ordered recordings. No network calls are needed for **Reproduce this generation**. Identical inputs, settings, algorithm version, and snapshot produce identical results. A new live refresh can change results even with the same seed.

Reproducing an unedited generation reruns the algorithm; reproducing a manually edited preview copies its exact saved selections. Both create an editable local copy with no Spotify export attached. Applying settings rebuilds the recommendation from the snapshot and discards manual edits in the new copy.

Spotify candidates require matching normalized artist and song names. Uncertain recordings and automatically discovered live/remix/remastered versions are skipped; explicitly selected versions are allowed as inputs. Deduplication uses ISRC where available and normalized song/artist identifiers otherwise. Availability checks use catalogue information returned by Spotify and remain limited by what the API exposes.

Acquisition is bounded to eight similar artists per input band, 30 own-band top tracks, 15 tracks per similar artist, 25 neighbors per seed song, and at most 600 Spotify candidate searches, with three concurrent provider calls and a ten-minute deadline. Sparse coverage or conservative matching can cause shortfalls; the app reports these instead of silently changing your requested count or mix. Progress reports acquisition, not measured recommendation quality.

## Data and recovery

`data/playlist.sqlite3` holds generation snapshots and server-side Spotify tokens. The directory is created with private permissions and the database with owner-only permissions. Tokens are stored locally without application-level encryption; protect this computer and its backups. `.env`, data, and caches are ignored by Git. The UI only receives catalogue results and generation records, never access/refresh tokens or API keys.

**Disconnect Spotify** removes local tokens. To delete local history and snapshots, stop the server and delete the configured data directory. Spotify playlists already saved remain in Spotify. Searches go to Spotify; input artist/song names go to Last.fm. The app does not request your listening history. It includes loopback host restrictions and CSRF protection and is not designed as a public multi-user service.

An interrupted playlist append is reconciled against Spotify before retrying. A saved export can be clicked again without creating another playlist. If creation itself times out, the app stops: check Spotify, then attach the playlist link for that generation, or explicitly confirm that no playlist exists to reset the attempt. It will not overwrite externally edited playlists. Reproduce a completed generation to make changes or create a separate playlist.

## Validation

```sh
pixi run lint
pixi run test
pixi run smoke
```

The smoke check uses your configured credentials and connected account for real Spotify search and Last.fm similarity. It returns exit code `2` when configuration/login is missing. To also exercise playlist creation, explicitly run:

```sh
pixi run smoke --write
```

This creates a private one-song playlist titled **Playlist Garden integration check** and records its generation for recovery in the app. Delete that test playlist in Spotify when finished.

Tests use isolated databases and mocked providers for quota semantics, 23 mandatory + 27 recommended songs, deterministic replay, optional inputs, matching, authentication, API errors, preview edits, and uncertain writes. They do not prove real-provider access or recommendation quality. For a listening evaluation, compare several mixed-band profiles with recommendations made independently per band, and record relevance, discovery, and band coverage; live listening evaluation requires your credentials and judgment.

## Source references

- [Spotify search](https://developer.spotify.com/documentation/web-api/reference/search), [create playlist](https://developer.spotify.com/documentation/web-api/reference/create-playlist), [playlist items](https://developer.spotify.com/documentation/web-api/reference/add-items-to-playlist), [2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide), and [PKCE](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow).
- Last.fm [similar tracks](https://www.last.fm/api/show/track.getSimilar), [similar artists](https://www.last.fm/api/show/artist.getSimilar), and [top tracks](https://www.last.fm/api/show/artist.getTopTracks). Review [API terms](https://www.last.fm/api/tos) before changing this personal tool into a commercial or research service.
