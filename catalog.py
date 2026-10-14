import json
import random
import re
import sqlite3
import time
import unicodedata
from contextlib import closing
from pathlib import Path




CATALOG = Path(__file__).with_name("catalog.json")
COOLDOWN = 7 * 24 * 60 * 60


def song_key(song):
    title = unicodedata.normalize("NFKC", song.get("base_title") or song["title"])
    title = re.sub(r"\s*[(（][^()（）]*(?:remix|live|ver\.|version|rearranged)[^()（）]*[)）]", "", title, flags=re.I)
    artists = " / ".join(sorted(song["artist"].split(" / ")))
    return artists + ":" + re.sub(r"\s+", "", title).casefold()


class Catalog:
    def __init__(self, catalog_path=CATALOG, db_path=None):
        self.songs = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS history (session TEXT, song_key TEXT, sent_at REAL, PRIMARY KEY(session, song_key))")

    def connect(self):
        return sqlite3.connect(self.db_path)

    def recommend(self, session, now=None):
        now = time.time() if now is None else now
        with closing(self.connect()) as conn:
            recent = {row[0] for row in conn.execute("SELECT song_key FROM history WHERE session=? AND sent_at>?", (session, now - COOLDOWN))}
        by_artist = {}
        for song in self.songs:
            if song.get('disabled', False):
                continue
            if song_key(song) not in recent:
                for artist in song["artist"].split(" / "):
                    by_artist.setdefault(artist, {}).setdefault(song_key(song), []).append(song)
        if not by_artist:
            return None
        artist = random.choice(list(by_artist))
        versions = random.choice(list(by_artist[artist].values()))
        return random.choice(versions)

    def record(self, session, song, now=None):
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO history VALUES (?,?,?)", (session, song_key(song), time.time() if now is None else now))
