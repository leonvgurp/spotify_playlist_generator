# One-time API setup

Playlist Garden uses Spotify for catalogue searches and playlist writes, and Last.fm for discovery. Register both once and put their credentials in the repository-root `.env` file.

First follow the clone and install steps in [README.md](README.md#install). From the repository root, create your local configuration file if it does not already exist:

```sh
cp .env.example .env
```

If `.env` already exists, edit it instead of overwriting it. Keep credentials out of Git; `.env` is ignored.

## Register the Spotify app

1. Open the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and sign in with the Spotify account you intend to use. The app owner needs **Spotify Premium** for development-mode API access. This personal tool can stay in development mode; no quota-extension application is needed. Spotify currently permits up to five authenticated users per development app ([requirements](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)).
2. Click **Create app**. Complete the form as follows:

   | Form field | What to enter or select |
   | --- | --- |
   | **App name** (required) | `Playlist Garden` |
   | **App description** (required) | `Personal local app to discover songs from selected artists and save private Spotify playlists.` |
   | **Website** | Leave blank; this local app does not need a public website. |
   | **Redirect URIs** (required) | `http://127.0.0.1:8000/auth/callback` |
   | **Which API/SDKs are you planning to use?** | Select **Web API** only. Leave Ads API, Web Playback SDK, iOS, and Android unchecked. The app searches the catalogue and saves playlists; it does not play audio. |
   | **Developer Terms of Service and Design Guidelines** | Read the linked terms/guidelines and tick the agreement checkbox if you agree. |

3. In the redirect URI field, click **Add** if that button is shown. Confirm the URI appears in the registered list, then click **Save** or **Create** to submit the form. **“This field is required” under App description means you must enter the description above before submitting.** The name and description identify your app on Spotify's authorization screen; Spotify generates the Client ID after registration.
4. Open the newly created app, then **Settings** (or **Basic Information** within Settings). Find **Client ID** and copy its full value. If your dashboard shows it directly on the app overview, you can copy it there. This is the app identifier, not your Spotify username, user ID, a playlist ID, or a track ID. See Spotify's [app settings guide](https://developer.spotify.com/documentation/web-api/concepts/apps).
5. Open the local `.env` file in this repository's root, beside `pyproject.toml`. Paste the value after `SPOTIFY_CLIENT_ID=` and save the file. Keep `SPOTIFY_REDIRECT_URI=http://127.0.0.1:8000/auth/callback`. You do **not** need to reveal, copy, or configure **Client Secret**: this implementation uses [Authorization Code with PKCE](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow). Access and refresh tokens are obtained automatically when you connect later.
6. In the dashboard, verify **Settings → Redirect URIs** contains the same callback and save any changes. Copy it exactly, including `/auth/callback`, with no trailing slash. Spotify permits HTTP for explicit loopback IP addresses and rejects `localhost` as a redirect URI ([redirect rules](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri)). You do not need a domain, HTTPS certificate, or public deployment for this setup.
7. Open **Settings → Users Management** (also called **Users and Access** in some dashboard versions). Check that the Spotify account you will connect is allowed. If it is not listed, use **Add new user**, enter your name and the email address associated with that Spotify account, and save. Add any other test account here before it connects. A user can sometimes complete login without being allowlisted but then receive `403` on API calls ([user access instructions](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)).

## Obtain the Last.fm key and finish configuration

1. Sign into Last.fm and [create an API account/key](https://www.last.fm/api/account/create), using `Playlist Garden` as the application name.
2. After registration, Last.fm displays **Application name**, **API key**, **Shared secret**, and **Registered to**. Use them as follows:

   | Last.fm result | What to do with it |
   | --- | --- |
   | **Application name** | Identifies your registration; no local configuration is needed. |
   | **API key** | Copy the full value into `LASTFM_API_KEY` in the repository-root `.env` file. |
   | **Shared secret** | Not needed by Playlist Garden. Do not add it to `.env` or the README. |
   | **Registered to** | Your Last.fm account name; no local configuration is needed. |

3. Open `.env` (not `.env.example`), replace the `LASTFM_API_KEY` value with your API key, and save. Use this format, substituting your actual key:

   ```dotenv
   LASTFM_API_KEY=your_lastfm_api_key
   ```

4. Restart `pixi run dev` if it is already running so it loads the updated configuration. After connecting Spotify, run `pixi run smoke` as described in [README.md](README.md#run-and-connect) to check both providers.

**You do not need the Last.fm shared secret.** This app sends only the API key for its public similarity and top-track requests; it does not authenticate your Last.fm account or sign requests. There is no `LASTFM_SHARED_SECRET` setting. Spotify and Last.fm issue separate credentials; the Spotify Client ID cannot be used as a Last.fm key. Keep your actual credentials in the ignored `.env` file, rather than copying them into documentation.

Your `.env` should look like this, with your own values:

```dotenv
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8000/auth/callback
LASTFM_API_KEY=your_lastfm_api_key
PLAYLIST_DATA_DIR=data
```

Return to [Run and connect](README.md#run-and-connect) to start the app and authorize Spotify.

## Registration and login troubleshooting

| Symptom | What to check |
| --- | --- |
| Create app reports a required field | Fill both **App name** and **App description**, add the redirect URI, select **Web API**, and review the agreement checkbox. |
| Spotify reports an invalid redirect URI | Compare the registered URI and `.env` value character for character against `http://127.0.0.1:8000/auth/callback`. Save dashboard changes and restart the server after local changes. |
| Spotify reports an invalid client | Copy **Client ID** again from the same dashboard app whose redirect URI you configured. Save `.env` and restart the server. |
| Login works but Spotify requests return `403` | Check the connected account's email in **Users Management / Users and Access** and confirm the app owner has Premium. If the browser used another account, disconnect in Playlist Garden and reconnect with the intended one. |
| Browser cannot reach the callback | Keep `pixi run dev` running during authorization and use `http://127.0.0.1:8000` to open the app. |
| App still reports missing configuration | Edit `.env`, not `.env.example`, in the repository root. Replace the placeholder values, save, and restart `pixi run dev` from that directory. |

