import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Settings:
    spotify_client_id: str = ""
    redirect_uri: str = "http://127.0.0.1:8000/auth/callback"
    lastfm_api_key: str = ""
    data_dir: Path = Path("data")

    @classmethod
    def load(cls):
        load_dotenv()
        return cls(
            spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID", ""),
            redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", cls.redirect_uri),
            lastfm_api_key=os.getenv("LASTFM_API_KEY", ""),
            data_dir=Path(os.getenv("PLAYLIST_DATA_DIR", "data")),
        )
