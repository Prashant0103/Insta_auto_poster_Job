from __future__ import annotations

import sqlite3
from pathlib import Path

from .logging_config import get_logger

logger = get_logger(__name__)


class VideoIdStore:
    """SQLite-backed store for tracking posted video IDs across deployments."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS posted_videos (
                    video_id TEXT PRIMARY KEY,
                    posted_at TEXT NOT NULL
                )
                """
            )
        logger.info("VideoIdStore initialized", db_path=str(db_path))

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path))

    def add(self, video_id: str, posted_at: str) -> None:
        """Record a video ID as posted. Silently ignores duplicates."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO posted_videos (video_id, posted_at) VALUES (?, ?)",
                (video_id, posted_at),
            )
        logger.debug("Recorded posted video ID", video_id=video_id)

    def all_ids(self) -> set[str]:
        """Return all video IDs that have been posted."""
        with self._connect() as conn:
            rows = conn.execute("SELECT video_id FROM posted_videos").fetchall()
        return {row[0] for row in rows}
