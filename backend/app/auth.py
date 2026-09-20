import hashlib
import sqlite3

from fastapi import Header, HTTPException


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_install(conn: sqlite3.Connection, install_id: str, token: str, created_at: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO installs(install_id, token_hash, created_at) VALUES(?,?,?)",
        (install_id, hash_token(token), created_at),
    )
    conn.commit()


def require_install(authorization: str | None = Header(default=None)) -> str:
    """Validate Bearer <installToken>, return install_id."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    from app.db import get_conn

    row = get_conn().execute(
        "SELECT install_id FROM installs WHERE token_hash = ?", (hash_token(token),)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="invalid install token")
    return row["install_id"]
