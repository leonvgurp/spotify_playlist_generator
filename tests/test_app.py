import re
import time

from fastapi.testclient import TestClient

from playlist_garden.app import create_app
from playlist_garden.config import Settings
from playlist_garden.recommendations import document


def client_for(tmp_path):
    return TestClient(create_app(Settings(data_dir=tmp_path)), base_url="http://127.0.0.1:8000")


def test_local_security_and_missing_credentials(tmp_path):
    with client_for(tmp_path) as client:
        home = client.get("/")
        assert home.status_code == 200 and "Playlist Garden" in home.text
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/api/status").json()["connected"] is False
        assert client.post("/api/connect").status_code == 403
        csrf = re.search(r'name="csrf-token" content="([^"]+)"', home.text)[1]
        assert client.post("/api/connect", headers={"X-CSRF-Token": csrf}).status_code == 502
        assert (
            client.post(
                "/api/disconnect", headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert client.get("/auth/callback?code=x&state=wrong").status_code == 400
        assert client.get("/", headers={"Host": "evil.example"}).status_code == 400


def test_replay_edit_download_and_offline_snapshot(tmp_path, fixture_profile):
    with client_for(tmp_path) as client:
        client.headers["X-CSRF-Token"] = client.app.state.csrf
        saved = client.app.state.store.save(document(*fixture_profile))
        path = f"/api/generations/{saved['id']}"
        replay = client.post(path + "/reproduce", json=None).json()
        assert replay["tracks"] == saved["tracks"] and replay["id"] != saved["id"]
        assert replay["snapshot"] == saved["snapshot"]
        spec = saved["request"] | {"title": "A new title", "ordering": "band"}
        changed = client.post(path + "/reproduce", json=spec).json()
        assert {r["track"]["id"] for r in changed["tracks"]} == {
            r["track"]["id"] for r in saved["tracks"]
        }
        locked = next(r for r in saved["tracks"] if r["locked"])
        assert (
            client.post(
                path + "/edit", json={"track_id": locked["track"]["id"], "action": "remove"}
            ).status_code
            == 422
        )
        unlocked = next(r for r in saved["tracks"] if not r["locked"])
        replaced = client.post(
            path + "/edit", json={"track_id": unlocked["track"]["id"], "action": "replace"}
        ).json()
        assert len(replaced["tracks"]) == 50
        assert unlocked["track"]["id"] not in [r["track"]["id"] for r in replaced["tracks"]]
        assert sum(r["locked"] for r in replaced["tracks"]) == 23
        another = next(r for r in replaced["tracks"] if not r["locked"])
        removed = client.post(
            path + "/edit", json={"track_id": another["track"]["id"], "action": "remove"}
        ).json()
        assert len(removed["tracks"]) == removed["request"]["count"] == 49
        assert client.post(path + "/reproduce", json=None).json()["tracks"] == removed["tracks"]
        assert client.get(path + "/download/csv").text.startswith("position,band,song")
        assert client.get(path + "/download/json").json()["snapshot"] == saved["snapshot"]
        assert client.get("/api/generations").json()
        assert client.get("/api/generations/missing").status_code == 404


def test_generation_job_and_shortage_snapshot(tmp_path, fixture_profile, monkeypatch):
    spec, snapshot = fixture_profile

    class FakeSpotify:
        async def call(self, method, path, **kwargs):
            for b in spec.bands:
                if path == f"/artists/{b.artist.id}":
                    return b.artist.model_dump()
                for t in b.tracks:
                    if path == f"/tracks/{t.id}":
                        return t.model_dump() | {
                            "external_ids": {"isrc": t.isrc},
                            "album": {"name": t.album},
                        }
            raise AssertionError(path)

    async def collect(self, request, progress):
        progress("Mock discovery")
        return snapshot

    monkeypatch.setattr("playlist_garden.app.Discovery.collect", collect)
    with client_for(tmp_path) as client:
        client.headers["X-CSRF-Token"] = client.app.state.csrf
        client.app.state.spotify = FakeSpotify()
        request = spec.model_copy(update={"count": 200, "include_inputs": False})
        response = client.post("/api/generations", json=request.model_dump())
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        for _ in range(100):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] != "running":
                break
            time.sleep(0.01)
        assert job["status"] == "complete", job
        doc = client.get(f"/api/generations/{job['generation_id']}").json()
        assert doc["status"] == "shortage" and doc["snapshot"]
        fixed = doc["request"] | {"count": 50}
        rebuilt = client.post(f"/api/generations/{doc['id']}/reproduce", json=fixed)
        assert rebuilt.status_code == 200 and len(rebuilt.json()["tracks"]) == 50
