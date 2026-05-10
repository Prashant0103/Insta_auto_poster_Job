from __future__ import annotations

import random
from typing import Protocol

from .config import AppConfig
from .downloader import DownloadedVideo, VideoDownloader
from .exceptions import PexelsNoResultsError, YouTubeNoResultsError
from .logging_config import get_logger
from .pexels_client import PexelsClient, PexelsVideo
from .youtube_client import YouTubeClient, YouTubeVideo

logger = get_logger(__name__)


class SourceVideo(Protocol):
    video_id: str
    source_url: str
    download_url: str
    duration: int
    width: int
    height: int

    @property
    def aspect_ratio(self) -> float:
        ...


def is_instagram_friendly(
    video: SourceVideo,
    max_duration: int,
    min_ratio: float,
    max_ratio: float,
) -> bool:
    """Check if video meets Instagram requirements."""
    if video.duration <= 0 or video.duration > max_duration:
        logger.debug(
            "Video rejected for duration",
            video_id=video.video_id,
            duration=video.duration,
            max_duration=max_duration,
        )
        return False

    ratio = video.aspect_ratio
    if ratio < min_ratio or ratio > max_ratio:
        logger.debug(
            "Video rejected for aspect ratio",
            video_id=video.video_id,
            aspect_ratio=ratio,
            min_ratio=min_ratio,
            max_ratio=max_ratio,
        )
        return False

    if video.width <= 0 or video.height <= 0:
        logger.debug(
            "Video rejected for invalid dimensions",
            video_id=video.video_id,
            width=video.width,
            height=video.height,
        )
        return False

    return True


class VideoSourceProvider(Protocol):
    name: str
    query: str

    async def search(self) -> list[SourceVideo]:
        ...

    async def download(self, video: SourceVideo) -> DownloadedVideo:
        ...


class PexelsVideoSource:
    name = "pexels"

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.query = config.pexels_query

    async def search(self) -> list[PexelsVideo]:
        async with PexelsClient(self.config.pexels_api_key) as pexels:
            return await pexels.search_videos(self.config.pexels_query, self.config.pexels_per_page)

    async def download(self, video: SourceVideo) -> DownloadedVideo:
        async with VideoDownloader(self.config.download_dir_path) as downloader:
            return await downloader.download(video)  # type: ignore[arg-type]


class YouTubeVideoSource:
    name = "youtube"

    def __init__(self, config: AppConfig, query: str | None = None) -> None:
        self.config = config
        self.query = query or config.youtube_query_value
        self.client = YouTubeClient(
            api_key=config.youtube_api_key,
            download_dir=config.download_dir_path,
            format_id=config.youtube_format,
            cookies_file=config.youtube_cookies_file,
        )

    async def search(self) -> list[YouTubeVideo]:
        return await self.client.search_shorts(
            query=self.query,
            max_results=self.config.youtube_max_results,
            max_duration_seconds=self.config.youtube_max_duration_seconds,
            min_like_count=self.config.youtube_min_like_count,
        )

    async def download(self, video: SourceVideo) -> DownloadedVideo:
        return await self.client.download(video)  # type: ignore[arg-type]


def build_video_sources(config: AppConfig, query: str | None = None) -> list[VideoSourceProvider]:
    """Build source providers from config flags."""
    sources: list[VideoSourceProvider] = []
    for source_name in config.video_source_order:
        if source_name == "youtube":
            sources.append(YouTubeVideoSource(config, query))
        elif source_name == "pexels":
            sources.append(PexelsVideoSource(config))
    return sources


async def find_and_download_video(
    config: AppConfig,
    used_ids: set[str],
    query: str | None = None,
) -> tuple[DownloadedVideo, str]:
    """Try configured sources in order and return the first downloaded video."""
    source_errors: list[str] = []

    for source in build_video_sources(config, query):
        try:
            logger.info("Searching video source", source=source.name, query=source.query)
            videos = await source.search()
            candidates = [
                video
                for video in videos
                if video.video_id not in used_ids
                and is_instagram_friendly(
                    video,
                    max_duration=config.max_video_duration_seconds,
                    min_ratio=config.min_aspect_ratio,
                    max_ratio=config.max_aspect_ratio,
                )
            ]

            logger.info(
                "Filtered video candidates",
                source=source.name,
                total_videos=len(videos),
                used_videos=len(used_ids),
                candidates=len(candidates),
            )

            if not candidates:
                raise PexelsNoResultsError(
                    f"No Instagram-friendly unposted videos found from {source.name}."
                )

            download_errors: list[str] = []
            ordered = candidates if source.name == "youtube" else [random.choice(candidates)]
            for chosen_video in ordered:
                logger.info(
                    "Selected video for download",
                    source=source.name,
                    video_id=chosen_video.video_id,
                    duration=chosen_video.duration,
                    dimensions=f"{chosen_video.width}x{chosen_video.height}",
                )
                try:
                    return await source.download(chosen_video), source.query
                except Exception as dl_exc:
                    download_errors.append(f"{chosen_video.video_id}: {dl_exc}")
                    logger.warning(
                        "Download failed for candidate, trying next",
                        source=source.name,
                        video_id=chosen_video.video_id,
                        error=str(dl_exc),
                    )

            last_err = download_errors[-1] if download_errors else "no candidates"
            raise Exception(f"All candidates failed. Last error: {last_err}")
        except Exception as exc:
            source_errors.append(f"{source.name}: {exc}")
            logger.warning(
                "Video source failed; trying next configured source",
                source=source.name,
                error=str(exc),
            )

    if not source_errors:
        raise YouTubeNoResultsError("No configured video sources are available.")
    raise YouTubeNoResultsError(
        "All configured video sources failed: " + "; ".join(source_errors)
    )
