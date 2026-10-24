import asyncio
import copy
import csv
import io
import json
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .discovery import Discovery
from .export import Exporter
from .matching import recording_key
from .models import ALGORITHM_VERSION, GenerationRequest, Snapshot, Track
from .providers import LastFM, ProviderError, Spotify, artist_from, track_from
from .recommendations import ShortageError, document, select
from .store import Store

ROOT = Path(__file__).parent
logger = logging.getLogger(__name__)


def create_app(settings=None):
    settings = settings or Settings.load()

    @asynccontextmanager
    async def lifespan(app):
        store = Store(settings.data_dir)
        csrf = store.get("csrf") or secrets.token_urlsafe(32)
        store.put("csrf", csrf)
        app.state.store, app.state.csrf = store, csrf
        app.state.jobs, app.state.tasks = {}, set()
        app.state.mutation_lock = asyncio.Lock()
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            app.state.spotify = Spotify(settings, store, client)
            app.state.lastfm = LastFM(settings, client)
            yield
            for task in app.state.tasks:
                task.cancel()
            await asyncio.gather(*app.state.tasks, return_exceptions=True)

    app = FastAPI(title="Playlist Garden", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    templates = Jinja2Templates(directory=ROOT / "templates")

    @app.middleware("http")
    async def local_security(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            token = request.headers.get("X-CSRF-Token", "")
            origin = request.headers.get("origin")
            if not secrets.compare_digest(token, getattr(app.state, "csrf", "missing")) or (
                origin and origin != str(request.base_url).rstrip("/")
            ):
                return JSONResponse({"detail": "Reload this local app before trying again."}, 403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.exception_handler(ValueError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def get_doc(generation_id):
        try:
            return app.state.store.generation(generation_id)
        except KeyError:
            raise HTTPException(404, "Generation not found.") from None

    def ensure_editable(doc):
        if doc["export"].get("status") not in {None, "not_created"}:
            raise ValueError(
                "This preview has an export in progress or completed. Reproduce it to edit a copy."
            )

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "csrf": app.state.csrf,
            },
        )

    @app.get("/api/status")
    async def status():
        return {
            "spotify_configured": bool(settings.spotify_client_id),
            "lastfm_configured": bool(settings.lastfm_api_key),
            "connected": bool(app.state.store.get("token")),
            "algorithm_version": ALGORITHM_VERSION,
        }

    @app.post("/api/connect")
    async def connect():
        url = app.state.spotify.authorization_url()
        pending = app.state.store.get("oauth")
        response = JSONResponse({"url": url})
        response.set_cookie(
            "oauth_state",
            pending["state"],
            httponly=True,
            samesite="lax",
            max_age=600,
            path="/auth/callback",
        )
        return response

    @app.get("/auth/callback")
    async def callback(request: Request, code: str = "", state: str = "", error: str = ""):
        cookie = request.cookies.get("oauth_state", "")
        if error or not code or not cookie or not secrets.compare_digest(cookie, state):
            raise HTTPException(
                400, "Spotify login was cancelled or invalid. Return to the app and reconnect."
            )
        await app.state.spotify.callback(code, state)
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie("oauth_state", path="/auth/callback")
        return response

    @app.post("/api/disconnect")
    async def disconnect():
        app.state.store.delete("token")
        return {"connected": False}

    @app.get("/api/search")
    async def search(q: str, kind: str = "artist", artist_id: str = "", artist_name: str = ""):
        if kind not in {"artist", "track"} or not 1 <= len(q.strip()) <= 300:
            raise HTTPException(422, "Enter an artist/song name or Spotify link.")
        query = q
        if kind == "track" and artist_name and not q.startswith(("https://", "spotify:")):
            query = f'artist:"{artist_name.replace(chr(34), "")}" track:"{q.replace(chr(34), "")}"'
        results = await app.state.spotify.search(query, kind)
        if kind == "track" and artist_id:
            results = [t for t in results if artist_id in {a.id for a in t.artists} and t.playable]
        return [r.model_dump() for r in results]

    async def confirm_inputs(request):
        # Never treat browser-supplied names, availability or IDs as catalogue truth.
        for band in request.bands:
            if not band.artist.id.isalnum() or len(band.artist.id) != 22:
                raise ValueError("Select a valid Spotify artist.")
            band.artist = artist_from(
                await app.state.spotify.call("GET", f"/artists/{band.artist.id}")
            )
            confirmed = []
            for track in band.tracks:
                if not track.id.isalnum() or len(track.id) != 22:
                    raise ValueError("Select a valid Spotify track.")
                confirmed.append(
                    track_from(await app.state.spotify.call("GET", f"/tracks/{track.id}"))
                )
            band.tracks = confirmed
        return GenerationRequest.model_validate(request.model_dump())

    async def build(job_id, spec):
        job = app.state.jobs[job_id]

        def progress(message):
            job["message"] = message

        try:
            progress("Confirming your input recordings…")
            spec = await confirm_inputs(spec)
            # Catch impossible mandatory counts before making discovery requests.
            if spec.include_inputs:
                keys = {recording_key(t) for b in spec.bands for t in b.tracks}
                if len(keys) > spec.count:
                    raise ValueError(
                        f"Choose at least {len(keys)} songs or turn input inclusion off."
                    )
            async with asyncio.timeout(600):
                snapshot = await Discovery(app.state.spotify, app.state.lastfm).collect(
                    spec, progress
                )
            doc = {
                "request": spec.model_dump(),
                "snapshot": snapshot.model_dump(),
                "algorithm_version": ALGORITHM_VERSION,
                "export": {},
                "excluded": [],
                "edited": False,
                "tracks": [],
                "status": "shortage",
            }
            try:
                doc["tracks"] = select(spec, snapshot)
                doc["status"] = "ready"
            except ShortageError as exc:
                doc["shortage"] = {"message": str(exc), "available": exc.available}
            app.state.store.save(doc)
            job.update(status="complete", generation_id=doc["id"], message="Preview ready")
        except TimeoutError:
            job.update(
                status="failed",
                message="Discovery exceeded ten minutes. Try fewer seeds or retry later.",
            )
        except (ProviderError, ValueError) as exc:
            job.update(status="failed", message=str(exc))
        except Exception:
            logger.exception("Generation failed")
            job.update(
                status="failed", message="Generation failed unexpectedly. Check the server log."
            )

    @app.post("/api/generations", status_code=202)
    async def generate(spec: GenerationRequest):
        if any(j["status"] == "running" for j in app.state.jobs.values()):
            raise HTTPException(409, "A generation is already running. Wait for it to finish.")
        job_id = uuid4().hex
        app.state.jobs[job_id] = {"status": "running", "message": "Starting…"}
        task = asyncio.create_task(build(job_id, spec))
        app.state.tasks.add(task)
        task.add_done_callback(app.state.tasks.discard)
        return {"job_id": job_id}

    @app.get("/api/jobs/{job_id}")
    async def job(job_id: str):
        if job_id not in app.state.jobs:
            raise HTTPException(
                404, "Job not found. A server restart cancels unfinished generations."
            )
        return app.state.jobs[job_id]

    @app.get("/api/generations")
    async def history():
        return app.state.store.recent()

    @app.get("/api/generations/{generation_id}")
    async def generation(generation_id: str):
        return get_doc(generation_id)

    @app.post("/api/generations/{generation_id}/reproduce")
    async def reproduce(generation_id: str, spec: GenerationRequest | None = None):
        original = get_doc(generation_id)
        if original["algorithm_version"] != ALGORITHM_VERSION:
            raise HTTPException(409, "This snapshot requires an older algorithm version.")
        if spec is None:
            if original["status"] == "ready" and not original["edited"]:
                doc = document(
                    GenerationRequest.model_validate(original["request"]),
                    Snapshot.model_validate(original["snapshot"]),
                )
            else:
                doc = copy.deepcopy(original)
                for field in ("id", "created_at"):
                    doc.pop(field, None)
                doc["export"] = {}
        else:
            if spec.model_dump()["bands"] != original["request"]["bands"]:
                raise ValueError(
                    "Keep the same input bands and songs when reusing a snapshot. Refresh to change inputs."
                )
            doc = document(spec, Snapshot.model_validate(original["snapshot"]))
        doc["reproduced_from"] = generation_id
        return app.state.store.save(doc)

    @app.post("/api/generations/{generation_id}/edit")
    async def edit(generation_id: str, request: Request):
        payload = await request.json()
        async with app.state.mutation_lock:
            doc = get_doc(generation_id)
            ensure_editable(doc)
            target = next(
                (r for r in doc["tracks"] if r["track"]["id"] == payload.get("track_id")), None
            )
            if target is None or target["locked"]:
                raise ValueError("Choose an unlocked recommendation to edit.")
            action = payload.get("action")
            if action not in {"remove", "replace"}:
                raise ValueError("Choose remove or replace.")
            if action == "remove" and len(doc["tracks"]) == 1:
                raise ValueError("Keep at least one song.")
            excluded = list(dict.fromkeys([*doc["excluded"], target["track"]["id"]]))
            if action == "replace":
                spec = GenerationRequest.model_validate(doc["request"])
                snapshot = Snapshot.model_validate(doc["snapshot"])
                kept = {recording_key(Track.model_validate(r["track"])) for r in doc["tracks"]}
                bands = {b.artist.id for b in spec.bands}
                target_outside = not bands.intersection(a["id"] for a in target["track"]["artists"])
                snapshot.candidates = [
                    c
                    for c in snapshot.candidates
                    if recording_key(c.track) not in kept
                    and c.track.id not in excluded
                    and (
                        spec.discovery_mode == "relevance"
                        or target_outside == (not bands.intersection(a.id for a in c.track.artists))
                    )
                ]
                single = spec.model_copy(
                    update={"count": 1, "include_inputs": False, "discovery_mode": "relevance"}
                )
                replacement = select(single, snapshot, excluded)[0]
                doc["tracks"][doc["tracks"].index(target)] = replacement
            else:
                doc["tracks"].remove(target)
                doc["request"]["count"] -= 1
            doc.update(excluded=excluded, edited=True)
            # Preserve chosen membership, but reapply the specified display order.
            from .recommendations import ordered

            by_id = {r["track"]["id"]: r for r in doc["tracks"]}
            doc["tracks"] = [
                by_id[t.id]
                for t in ordered(
                    [Track.model_validate(r["track"]) for r in doc["tracks"]],
                    GenerationRequest.model_validate(doc["request"]),
                )
            ]
            return app.state.store.save(doc)

    @app.post("/api/generations/{generation_id}/export")
    async def export(generation_id: str):
        async with app.state.mutation_lock:
            return await Exporter(app.state.store, app.state.spotify).save(get_doc(generation_id))

    @app.post("/api/generations/{generation_id}/recover")
    async def recover(generation_id: str, request: Request):
        payload = await request.json()
        async with app.state.mutation_lock:
            await Exporter(app.state.store, app.state.spotify).recover(
                get_doc(generation_id), payload.get("reference", "")
            )
        return {"status": "attached"}

    @app.post("/api/generations/{generation_id}/reset-export")
    async def reset_export(generation_id: str, request: Request):
        payload = await request.json()
        async with app.state.mutation_lock:
            doc = get_doc(generation_id)
            if (
                doc["export"].get("playlist_id")
                or payload.get("confirm_no_playlist") is not True
                or doc["export"].get("status") not in {"creating", "uncertain"}
            ):
                raise ValueError("Confirm that no playlist was created before resetting.")
            doc["export"] = {}
            app.state.store.save(doc)
        return {"status": "reset"}

    @app.get("/api/generations/{generation_id}/download/{format}")
    async def download(generation_id: str, format: str):
        doc = get_doc(generation_id)
        if format == "json":
            content, media_type = json.dumps(doc, indent=2), "application/json"
        elif format == "csv":
            stream = io.StringIO()
            writer = csv.writer(stream)
            writer.writerow(["position", "band", "song", "spotify_uri", "input", "explanation"])
            for i, row in enumerate(doc["tracks"], 1):
                t = row["track"]

                # Prevent spreadsheet formula execution from catalogue names.
                def safe(s):
                    return "'" + s if s.startswith(("=", "+", "-", "@")) else s

                writer.writerow(
                    [
                        i,
                        safe(", ".join(a["name"] for a in t["artists"])),
                        safe(t["name"]),
                        f"spotify:track:{t['id']}",
                        row["input"],
                        safe(row["explanation"]),
                    ]
                )
            content, media_type = stream.getvalue(), "text/csv"
        else:
            raise HTTPException(404, "Choose json or csv.")
        return Response(
            content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="playlist-{generation_id}.{format}"',
            },
        )

    # The callback origin is documented and must remain loopback-only in this personal app.
    if urlparse(settings.redirect_uri).hostname not in {"127.0.0.1", "::1"}:
        raise ValueError("Use a loopback IP address in SPOTIFY_REDIRECT_URI.")
    return app


app = create_app()
