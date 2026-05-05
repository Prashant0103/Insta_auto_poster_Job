"""Pixabay Music API client — search and download royalty-free background music."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import httpx

from .exceptions import MediaProcessingError
from .logging_config import get_logger
from .retry_utils import retry_with_backoff

logger = get_logger(__name__)

_PIXABAY_MUSIC_API = "https://pixabay.com/api/music/"


@dataclass(slots=True)
class MusicTrack:
    """Represents a Pixabay music track."""
    track_id: int
    title: str
    duration: int    # seconds
    audio_url: str   # direct MP3 download URL


class MusicClient:
    """Async client for the Pixabay Music API."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            limits=httpx.Limits(max_keepalive_connections=2, max_connections=5),
        )
        logger.info("Initialized Pixabay music client")

    async def __aenter__(self) -> "MusicClient":
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *args) -> None:
        await self._client.__aexit__(*args)

    async def search_tracks(self, query: str, per_page: int = 20) -> list[MusicTrack]:
        """
        Search for music tracks on Pixabay.

        Args:
            query:    Search keywords (e.g. 'ambient nature relaxing')
            per_page: Max results to fetch (1–200)

        Returns:
            List of MusicTrack objects with direct download URLs.
        """
        async def _search():
            response = await self._client.get(
                _PIXABAY_MUSIC_API,
                params={
                    "key": self._api_key,
                    "q": query,
                    "per_page": min(per_page, 200),
                },
            )
            response.raise_for_status()
            data = response.json()

            tracks: list[MusicTrack] = []
            for hit in data.get("hits", []):
                # Pixabay music API returns the download URL in one of these fields
                audio_url = (
                    hit.get("audio", {}).get("url", "")
                    or hit.get("previewURL", "")
                    or hit.get("audioURL", "")
                )
                if not audio_url:
                    continue

                tracks.append(
                    MusicTrack(
                        track_id=hit.get("id", 0),
                        title=hit.get("title", "Unknown"),
                        duration=int(hit.get("duration", 0)),
                        audio_url=audio_url,
                    )
                )

            logger.info(
                "Pixabay music search completed",
                query=query,
                total_hits=data.get("totalHits", 0),
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
                "Pixabay API error",
                status=e.response.status_code,
                body=e.response.text[:300],
            )
            raise MediaProcessingError(
                f"Pixabay music search failed (HTTP {e.response.status_code})"
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
            async with self._client.stream("GET", track.audio_url) as response:
                response.raise_for_status()
                with output_path.open("wb") as fh:
                    async for chunk in response.aiter_bytes(1024 * 256):
                        if chunk:
                            fh.write(chunk)

            if not output_path.exists() or output_path.stat().st_size == 0:
                raise MediaProcessingError("Downloaded music file is empty")

            logger.info(
                "Music track downloaded",
                title=track.title,
                duration_s=track.duration,
                size_kb=f"{output_path.stat().st_size / 1024:.1f}",
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
            query:        Search keywords.
            max_duration: Skip tracks longer than this (seconds).

        Returns:
            A random MusicTrack, or None if nothing was found.
        """
        tracks = await self.search_tracks(query)
        eligible = [t for t in tracks if t.audio_url and (t.duration == 0 or t.duration <= max_duration)]

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
