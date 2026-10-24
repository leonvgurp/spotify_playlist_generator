import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "playlist.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS generations (
                    id TEXT PRIMARY KEY, document TEXT NOT NULL
                );
            """)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        with sqlite3.connect(self.path) as db:
            yield db

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (key, json.dumps(value)))

    def delete(self, key):
        with self.connect() as db:
            db.execute("DELETE FROM kv WHERE key=?", (key,))

    def save(self, document):
        document.setdefault("id", uuid4().hex)
        document.setdefault("created_at", datetime.now(UTC).isoformat())
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO generations VALUES (?, ?)",
                (document["id"], json.dumps(document)),
            )
        return document

    def generation(self, generation_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT document FROM generations WHERE id=?", (generation_id,)
            ).fetchone()
        if not row:
            raise KeyError(generation_id)
        return json.loads(row[0])

    def recent(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT document FROM generations ORDER BY rowid DESC LIMIT 30"
            ).fetchall()
        return [
            {k: d[k] for k in ("id", "created_at", "request", "status")}
            for (raw,) in rows
            if (d := json.loads(raw))
        ]
