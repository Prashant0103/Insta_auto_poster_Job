from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

import httpx

from .downloader import DownloadedVideo
from .exceptions import MediaProcessingError, YouTubeAPIError, YouTubeNoResultsError
from .logging_config import get_logger

logger = get_logger(__name__)

FORMAT_MAP: dict[str, str] = {
    "0":    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[acodec!=none]/best",
    "2160": "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160][acodec!=none]/best[height<=2160]",
    "1440": "bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/best[height<=1440][acodec!=none]/best[height<=1440]",
    "1080": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][acodec!=none]/best[height<=1080]",
    "720":  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][acodec!=none]/best[height<=720]",
    "480":  "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][acodec!=none]/best[height<=480]",
    "360":  "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][acodec!=none]/best[height<=360]",
    "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[acodec!=none]/best",
}
DOWNLOAD_CLIENTS = ["android_vr", "android", "ios", "tv_embedded", "mweb", "web"]
YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
_INVIDIOUS_FALLBACK_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.privacyredirect.com",
    "https://iv.datura.network",
    "https://invidious.nerdvpn.de",
    "https://yt.artemislena.eu",
    "https://invidious.materialio.us",
    "https://invidious.protokolla.fi",
    "https://invidious.drgns.space",
    "https://inv.tux.pizza",
]


def _build_js_runtimes() -> dict:
    runtimes: dict = {}
    if shutil.which("deno"):
        runtimes["deno"] = {}
    node_path = shutil.which("node")
    if node_path:
        runtimes["node"] = {"path": node_path}
    return runtimes


@dataclass(slots=True)
class YouTubeVideo:
    """Represents a YouTube video candidate."""

    video_id: str
    source_url: str
    download_url: str
    duration: int
    width: int = 1080
    height: int = 1920
    title: str = ""
    channel: str = ""
    published_at: str = ""
    like_count: int = 0

    @property
    def aspect_ratio(self) -> float:
        if not self.height:
            return 0.0
        return self.width / self.height


class YouTubeClient:
    """YouTube search and download client using the YT_Downloader approach."""

    def __init__(self, api_key: str, download_dir: Path, format_id: str = "720", cookies_file: str = "") -> None:
        self.api_key = api_key
        self.download_dir = download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.format_id = format_id if format_id in FORMAT_MAP else "720"
        self.cookies_file = cookies_file

    async def search_shorts(
        self,
        query: str,
        max_results: int,
        max_duration_seconds: int,
        min_like_count: int,
    ) -> List[YouTubeVideo]:
        """Search and filter YouTube videos that qualify as Shorts."""
        filtered_json = await self.search_shorts_json(
            query=query,
            max_results=max_results,
            max_duration_seconds=max_duration_seconds,
            min_like_count=min_like_count,
        )
        return [
            YouTubeVideo(
                video_id=f"youtube-{item['videoId']}",
                source_url=item["url"],
                download_url="",
                duration=item["durationSeconds"],
                title=item["title"],
                channel=item["channelTitle"],
                published_at=item["publishedAt"],
                like_count=item["likeCount"],
            )
            for item in filtered_json
        ]

    async def search_shorts_json(
        self,
        query: str,
        max_results: int,
        max_duration_seconds: int,
        min_like_count: int,
    ) -> list[dict]:
        """
        Return filtered YouTube Shorts candidates sorted by likeCount desc.

        YouTube has no direct Shorts API filter, so this treats videos with
        duration <= max_duration_seconds as Shorts candidates.
        """
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                search_items = await self._search_videos(client, query, max_results)

                if not search_items:
                    raise YouTubeNoResultsError(f"No YouTube videos returned for query: {query}")

                video_ids = [
                    item.get("id", {}).get("videoId", "")
                    for item in search_items
                    if item.get("id", {}).get("videoId")
                ]
                details_by_id = await self._fetch_video_details(client, video_ids)

            filtered = []
            for item in search_items:
                raw_id = item.get("id", {}).get("videoId", "")
                details = details_by_id.get(raw_id)
                if not details:
                    continue

                snippet = item.get("snippet", {})
                detail_snippet = details.get("snippet", {})
                content_details = details.get("contentDetails", {})
                statistics = details.get("statistics", {})
                duration_seconds = _parse_iso_duration_seconds(
                    content_details.get("duration", "")
                )
                like_count = _parse_int(statistics.get("likeCount"))

                if duration_seconds <= 0 or duration_seconds > max_duration_seconds:
                    continue
                if like_count < min_like_count:
                    continue

                filtered.append(
                    {
                        "videoId": raw_id,
                        "title": detail_snippet.get("title") or snippet.get("title", ""),
                        "channelTitle": (
                            detail_snippet.get("channelTitle")
                            or snippet.get("channelTitle", "")
                        ),
                        "publishedAt": (
                            detail_snippet.get("publishedAt")
                            or snippet.get("publishedAt", "")
                        ),
                        "durationSeconds": duration_seconds,
                        "likeCount": like_count,
                        "url": f"https://www.youtube.com/shorts/{raw_id}",
                    }
                )

            filtered.sort(key=lambda item: item["likeCount"], reverse=True)
            logger.info(
                "YouTube Shorts filtering completed",
                query=query,
                discovered=len(search_items),
                filtered=len(filtered),
                max_duration_seconds=max_duration_seconds,
                min_like_count=min_like_count,
            )
            return filtered
        except YouTubeNoResultsError:
            raise
        except httpx.HTTPStatusError as exc:
            logger.error(
                "YouTube API HTTP error",
                status_code=exc.response.status_code,
                response_text=exc.response.text[:300],
            )
            raise YouTubeAPIError(
                f"YouTube API error {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("YouTube API request failed", error=str(exc))
            raise YouTubeAPIError(f"YouTube API request failed: {exc}") from exc
        except Exception as exc:
            logger.error("YouTube API search failed", query=query, error=str(exc))
            raise YouTubeAPIError(f"YouTube API search failed: {exc}") from exc

    async def download(self, video: YouTubeVideo) -> DownloadedVideo:
        """Download a YouTube video locally with yt-dlp."""
        return await asyncio.to_thread(self._download_sync, video)

    async def _search_videos(
        self,
        client: httpx.AsyncClient,
        query: str,
        max_results: int,
    ) -> list[dict]:
        response = await client.get(
            f"{YOUTUBE_API_BASE_URL}/search",
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": max_results,
                "key": self.api_key,
            },
        )
        response.raise_for_status()
        return response.json().get("items", [])

    async def _fetch_video_details(
        self,
        client: httpx.AsyncClient,
        video_ids: list[str],
    ) -> dict[str, dict]:
        if not video_ids:
            return {}

        response = await client.get(
            f"{YOUTUBE_API_BASE_URL}/videos",
            params={
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(video_ids),
                "key": self.api_key,
            },
        )
        response.raise_for_status()
        return {item["id"]: item for item in response.json().get("items", [])}

    def _download_sync(self, video: YouTubeVideo) -> DownloadedVideo:
        yt_dlp = _import_yt_dlp()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_id = _safe_filename(video.video_id)
        output_template = str(self.download_dir / f"{timestamp}_{safe_id}.%(ext)s")

        opts = _base_yt_dlp_opts()
        opts.update(
            {
                "outtmpl": output_template,
                "format": FORMAT_MAP[self.format_id],
                "merge_output_format": "mp4",
                "restrictfilenames": True,
                "concurrent_fragment_downloads": 4,
            }
        )
        if self.cookies_file and Path(self.cookies_file).exists():
            opts["cookiefile"] = self.cookies_file
            logger.info("Using cookies file for YouTube download", path=self.cookies_file)

        logger.info(
            "Starting YouTube download",
            video_id=video.video_id,
            source_url=video.source_url,
            format_id=self.format_id,
        )

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video.source_url, download=True)
                file_path = _resolve_filepath(ydl, info)

            path = Path(file_path)
            if not path.exists() or path.stat().st_size == 0:
                raise MediaProcessingError(f"YouTube download created an empty file: {path}")

            logger.info(
                "YouTube download completed",
                video_id=video.video_id,
                file_size_mb=f"{path.stat().st_size / (1024 * 1024):.2f}",
            )
            return DownloadedVideo(
                video_id=video.video_id,
                file_path=path,
                source_url=video.source_url,
                download_url="",
                title=video.title,
            )
        except Exception as exc:
            message = str(exc).removeprefix("ERROR: ").strip()
            if _is_bot_detection_error(message):
                logger.warning(
                    "Bot detection triggered, trying Invidious fallback",
                    video_id=video.video_id,
                )
                raw_id = video.video_id.replace("youtube-", "")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_id = _safe_filename(video.video_id)
                dest_path = self.download_dir / f"{timestamp}_{safe_id}.mp4"
                invidious_path = _download_via_invidious(raw_id, dest_path)
                if invidious_path:
                    logger.info(
                        "Invidious fallback download completed",
                        video_id=video.video_id,
                        file_size_mb=f"{invidious_path.stat().st_size / (1024 * 1024):.2f}",
                    )
                    return DownloadedVideo(
                        video_id=video.video_id,
                        file_path=invidious_path,
                        source_url=video.source_url,
                        download_url="",
                        title=video.title,
                    )
            logger.error("YouTube download failed", video_id=video.video_id, error=message)
            raise MediaProcessingError(f"YouTube download failed: {message}") from exc


def _base_yt_dlp_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": False,
        "extractor_args": {"youtube": {"player_client": DOWNLOAD_CLIENTS}},
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        },
        "sleep_interval_requests": 0.25,
        "max_sleep_interval": 1,
        "retries": 3,
        "fragment_retries": 3,
        "buffersize": 1024 * 1024,
        "http_chunk_size": 10 * 1024 * 1024,
    }

    js_runtimes = _build_js_runtimes()
    if js_runtimes:
        opts["js_runtimes"] = js_runtimes

    ffmpeg_path = _ffmpeg_path()
    if ffmpeg_path:
        opts["ffmpeg_location"] = ffmpeg_path
    return opts


def _ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg") or ""


def _resolve_filepath(ydl, info: dict) -> str:
    requested = info.get("requested_downloads") or []
    if requested:
        entry = requested[0]
        filepath = entry.get("filepath") or entry.get("filename")
        if filepath:
            return filepath
    return str(Path(ydl.prepare_filename(info)).with_suffix(".mp4"))


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9_.-]+', "_", value).strip("._ ")
    return cleaned or "video"


def _parse_iso_duration_seconds(iso: str) -> int:
    if not iso or not iso.startswith("PT"):
        return 0
    hours = int((re.search(r"(\d+)H", iso) or [None, 0])[1])
    minutes = int((re.search(r"(\d+)M", iso) or [None, 0])[1])
    seconds = int((re.search(r"(\d+)S", iso) or [None, 0])[1])
    return hours * 3600 + minutes * 60 + seconds


def _parse_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _import_yt_dlp():
    try:
        import yt_dlp

        return yt_dlp
    except ImportError as exc:
        raise MediaProcessingError(
            "yt-dlp is not installed. Run: pip install -r requirements.txt"
        ) from exc


def _is_bot_detection_error(message: str) -> bool:
    return "sign in to confirm" in message.lower() or "bot" in message.lower()


def _fetch_invidious_instances() -> list[str]:
    """Fetch live API-enabled Invidious instances from the public registry."""
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get("https://api.invidious.io/instances.json")
            if resp.status_code != 200:
                return _INVIDIOUS_FALLBACK_INSTANCES
            instances = []
            for entry in resp.json():
                if not isinstance(entry, list) or len(entry) < 2:
                    continue
                info = entry[1]
                if (
                    isinstance(info, dict)
                    and info.get("api") is True
                    and info.get("type") == "https"
                ):
                    uri = info.get("uri", "").rstrip("/")
                    if uri:
                        instances.append(uri)
            logger.info("Fetched Invidious instances from registry", count=len(instances))
            return instances if instances else _INVIDIOUS_FALLBACK_INSTANCES
    except Exception as e:
        logger.warning("Failed to fetch Invidious registry, using fallback list", error=str(e))
        return _INVIDIOUS_FALLBACK_INSTANCES


def _download_via_invidious(raw_video_id: str, dest_path: Path) -> Path | None:
    """Try Invidious instances (live registry + fallback) to get a proxied MP4 stream."""
    instances = _fetch_invidious_instances()

    for instance in instances:
        try:
            logger.info("Trying Invidious instance", instance=instance, video_id=raw_video_id)
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                resp = client.get(f"{instance}/api/v1/videos/{raw_video_id}")
                if resp.status_code != 200:
                    logger.warning("Invidious instance returned non-200",
                                   instance=instance, status=resp.status_code)
                    continue
                data = resp.json()

            # formatStreams = progressive mp4 (video+audio combined, no ffmpeg needed)
            streams = [
                s for s in data.get("formatStreams", [])
                if "mp4" in s.get("container", "") or "mp4" in s.get("type", "")
            ]
            if not streams:
                logger.warning("No MP4 streams from Invidious instance", instance=instance)
                continue

            def _quality_rank(s: dict) -> int:
                label = s.get("qualityLabel", "")
                for res in ("1080", "720", "480", "360"):
                    if res in label:
                        return int(res)
                return 0

            streams.sort(key=_quality_rank, reverse=True)
            stream_url = streams[0]["url"]

            logger.info("Downloading via Invidious", instance=instance, url=stream_url[:80])
            with httpx.Client(timeout=httpx.Timeout(120.0), follow_redirects=True) as client:
                with client.stream("GET", stream_url) as r:
                    r.raise_for_status()
                    with dest_path.open("wb") as f:
                        for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                            f.write(chunk)

            if dest_path.exists() and dest_path.stat().st_size > 0:
                return dest_path

        except Exception as e:
            logger.warning("Invidious instance failed", instance=instance, error=str(e))
            if dest_path.exists():
                dest_path.unlink(missing_ok=True)

    return None

