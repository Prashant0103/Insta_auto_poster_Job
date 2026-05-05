"""Jamendo Music API client — search and download royalty-free background music.

Jamendo is a free music platform with a proper REST API.
All tracks are Creative Commons licensed — free to use.

API docs: https://developer.jamendo.com/v3.0/tracks
Register for a free client_id at: https://devportal.jamendo.com
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import httpx

from .exceptions import MediaProcessingError
from .logging_config import get_logger
from .retry_utils import retry_with_backoff

logger = get_logger(__name__)

_JAMENDO_API = "https://api.jamendo.com/v3.0/tracks/"


@dataclass(slots=True)
class MusicTrack:
    """Represents a Jamendo music track."""
    track_id: str
    title: str
    duration: int    # seconds (0 if unknown)
    audio_url: str   # direct MP3 streaming/download URL


class MusicClient:
    """Async client for the Jamendo Music API."""

    def __init__(self, client_id: str) -> None:
        self._client_id = client_id
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            limits=httpx.Limits(max_keepalive_connections=2, max_connections=5),
        )
        logger.info("Initialized Jamendo music client")

    async def __aenter__(self) -> "MusicClient":
        await self._http.__aenter__()
        return self

    async def __aexit__(self, *args) -> None:
        await self._http.__aexit__(*args)

    async def search_tracks(self, query: str, limit: int = 20) -> list[MusicTrack]:
        """
        Search for music tracks on Jamendo by tags/keywords.

        Args:
            query: Space-separated tags (e.g. 'ambient relaxing nature')
            limit: Max results to return (1–200)

        Returns:
            List of MusicTrack objects.
        """
        async def _search():
            response = await self._http.get(
                _JAMENDO_API,
                params={
                    "client_id": self._client_id,
                    "format": "json",
                    "limit": min(limit, 200),
                    "tags": query,          # space-separated tags
                    "audioformat": "mp31",  # 128 kbps MP3 — small enough to download fast
                    "include": "musicinfo", # includes genre/mood info in response
                },
            )
            response.raise_for_status()
            data = response.json()

            tracks: list[MusicTrack] = []
            for hit in data.get("results", []):
                # Jamendo returns 'audio' (streaming) and 'audiodownload' (download)
                audio_url = hit.get("audiodownload") or hit.get("audio", "")
                if not audio_url:
                    continue

                tracks.append(
                    MusicTrack(
                        track_id=str(hit.get("id", "")),
                        title=hit.get("name", "Unknown"),
                        duration=int(hit.get("duration", 0)),
                        audio_url=audio_url,
                    )
                )

            logger.info(
                "Jamendo search completed",
                query=query,
                results_total=data.get("headers", {}).get("results_count", "?"),
                tracks_with_url=len(tracks),
            )
            return tracks

        try:
            return await retry_with_backoff(
                _search,
                max_attempts=3,
                base_delay=2.0,
                exceptions=(httpx.RequestError,),
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                "Jamendo API error",
                status=e.response.status_code,
                body=e.response.text[:300],
            )
            raise MediaProcessingError(
                f"Jamendo music search failed (HTTP {e.response.status_code})"
            ) from e

    async def download_track(self, track: MusicTrack, output_path: Path) -> Path:
        """
        Download a music track MP3 to a local file.

        Args:
            track:       The MusicTrack to download.
            output_path: Where to save the MP3.

        Returns:
            Path to the downloaded file.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        async def _download():
            async with self._http.stream("GET", track.audio_url) as response:
                response.raise_for_status()
                with output_path.open("wb") as fh:
                    async for chunk in response.aiter_bytes(1024 * 256):
                        if chunk:
                            fh.write(chunk)

            if not output_path.exists() or output_path.stat().st_size == 0:
                raise MediaProcessingError("Downloaded music file is empty")

            size_kb = output_path.stat().st_size / 1024
            logger.info(
                "Music track downloaded",
                title=track.title,
                duration_s=track.duration,
                size_kb=f"{size_kb:.1f}",
                path=str(output_path),
            )
            return output_path

        return await retry_with_backoff(
            _download,
            max_attempts=3,
            base_delay=2.0,
            exceptions=(httpx.RequestError, MediaProcessingError),
        )

    async def get_random_track(
        self,
        query: str,
        max_duration: int = 600,
    ) -> MusicTrack | None:
        """
        Return a random eligible track for the given query.

        Args:
            query:        Space-separated tags to search Jamendo.
            max_duration: Skip tracks longer than this many seconds.

        Returns:
            A random MusicTrack, or None if nothing was found.
        """
        tracks = await self.search_tracks(query)
        eligible = [
            t for t in tracks
            if t.audio_url and (t.duration == 0 or t.duration <= max_duration)
        ]

        if not eligible:
            logger.warning("No eligible music tracks found", query=query)
            return None

        chosen = random.choice(eligible)
        logger.info(
            "Selected music track",
            title=chosen.title,
            duration_s=chosen.duration,
            track_id=chosen.track_id,
        )
        return chosen
