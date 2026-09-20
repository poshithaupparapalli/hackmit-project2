import os
import sqlite3
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = BASE_DIR / "data" / "mia.db"

_conn: sqlite3.Connection | None = None
_lock = threading.RLock()


def db_path() -> str:
    return os.environ.get("MIA_DB_PATH", str(DEFAULT_DB))


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = db_path()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        init_schema(_conn)
    return _conn


def reset_conn(path: str | None = None) -> sqlite3.Connection:
    """Swap the connection (used by tests / demo seeding)."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        if path is not None:
            os.environ["MIA_DB_PATH"] = path
    return get_conn()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS installs (
            install_id  TEXT PRIMARY KEY,
            token_hash  TEXT NOT NULL,
            created_at  INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events (
            id          TEXT NOT NULL,
            install_id  TEXT NOT NULL,
            session_id  TEXT,
            timestamp   INTEGER,
            sequence    INTEGER,
            tab_id      INTEGER,
            frame_id    INTEGER,
            type        TEXT,
            host        TEXT,
            path        TEXT,
            title       TEXT,
            detail_json TEXT,
            context_json TEXT,
            received_at INTEGER NOT NULL,
            UNIQUE(install_id, id)
        );
        CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(install_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_host ON events(host);

        CREATE TABLE IF NOT EXISTS suggestions (
            id          TEXT PRIMARY KEY,
            install_id  TEXT,
            kind        TEXT NOT NULL,
            title       TEXT NOT NULL,
            summary     TEXT,
            evidence_json   TEXT,
            steps_json      TEXT,
            trigger     TEXT,
            action      TEXT,
            build_prompt TEXT,
            workflow_key TEXT,
            confidence  REAL,
            time_saved_per_week_minutes REAL,
            status      TEXT NOT NULL,
            created_at  INTEGER NOT NULL,
            updated_at  INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS suggestion_feedback (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            suggestion_id TEXT NOT NULL,
            decision      TEXT NOT NULL,
            user_edits    TEXT,
            created_at    INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    conn.commit()


def meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def now_ms() -> int:
    import time

    return int(time.time() * 1000)
