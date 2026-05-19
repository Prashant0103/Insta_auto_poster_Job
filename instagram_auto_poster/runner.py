from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from .caption_builder import build_caption, build_caption_from_youtube
from .config import load_config, AppConfig
from .downloader import DownloadedVideo
from .instagram_api_client import InstagramAPIClient
from .gist_sync import pull_state_from_gist, push_state_to_gist
from .video_sources import find_and_download_video
from .state_store import PostedStateStore, VideoRecord
from .video_id_store import VideoIdStore
from .youtube_client import YouTubeClient
from .health_check import HealthChecker
from .logging_config import setup_logging, get_logger, log_error
from .exceptions import (
    ConfigurationError, InstagramError, MediaProcessingError, AutoPosterError
)

logger = get_logger(__name__)


def _build_downloaded_video(record: VideoRecord) -> DownloadedVideo:
    """Build DownloadedVideo from VideoRecord."""
    return DownloadedVideo(
        video_id=record.video_id,
        file_path=Path(record.file_path),
        source_url=record.source_url,
        download_url=record.download_url,
    )


async def run_health_check(config: AppConfig) -> bool:
    """
    Run health check and return True if system is healthy.
    
    Args:
        config: Application configuration
        
    Returns:
        True if system is healthy, False otherwise
    """
    try:
        checker = HealthChecker(config)
        status = await checker.check_health()
        
        logger.info("Health check results",
                   healthy=status.overall_healthy,
                   instagram_api_reachable=status.instagram_api_reachable,
                   pexels_accessible=status.pexels_api_accessible,
                   pending_downloads=status.pending_downloads,
                   recent_failures=status.failed_attempts_last_24h)
        
        if not status.overall_healthy:
            logger.warning("System health issues detected", issues=status.issues)
        
        return status.overall_healthy
        
    except Exception as e:
        log_error(e, {"context": "health_check"})
        return False


async def _push_gist(config: AppConfig) -> None:
    if config.gh_pat and config.state_gist_id:
        await push_state_to_gist(
            gist_id=config.state_gist_id,
            github_token=config.gh_pat,
            local_path=config.posted_state_file_path,
        )


def _find_pending_or_retry(store: PostedStateStore) -> VideoRecord | None:
    """Return a pending download or a retryable failed record, or None."""
    pending = store.get_pending_download()
    if pending is not None:
        logger.info("Checked for pending downloads", found=True)
        return pending

    logger.info("Checked for pending downloads", found=False)
    failed_records = store.get_failed_records(max_attempts=3)
    logger.info("Checked for failed records", count=len(failed_records))

    for record in failed_records:
        file_exists = Path(record.file_path).exists()
        logger.info("Checking failed record",
                    video_id=record.video_id,
                    attempts=record.attempts,
                    file_exists=file_exists)

        if not file_exists:
            logger.warning("Failed record file missing",
                           video_id=record.video_id,
                           file_path=record.file_path)
            continue

        if not record.download_url:
            logger.warning("Removing failed record with no download_url — freeing ID for reuse",
                           video_id=record.video_id)
            store.delete_record(record.video_id)
            continue

        logger.info("Retrying failed post",
                    video_id=record.video_id,
                    attempts=record.attempts,
                    file_path=record.file_path,
                    last_error=record.last_error[:100] + "..." if len(record.last_error) > 100 else record.last_error)
        return record

    return None


async def _post_single(
    config: AppConfig,
    store: PostedStateStore,
    video_id_store: VideoIdStore,
    query: str,
    pending_record: VideoRecord | None,
) -> None:
    """Download (if needed) and post one video for the given query."""

    if pending_record is not None:
        downloaded = _build_downloaded_video(pending_record)
        caption = pending_record.caption or build_caption(
            theme=config.caption_theme,
            hashtags=config.default_hashtags_list,
            query=pending_record.query,
        )
        query = pending_record.query
        source_url = pending_record.source_url
        download_url = pending_record.download_url
        downloaded_at = pending_record.downloaded_at
        attempts = pending_record.attempts
        logger.info("Resuming with previously downloaded video",
                    video_id=downloaded.video_id,
                    file_path=str(downloaded.file_path),
                    attempts=attempts)
    else:
        logger.info("Searching for new video", query=query, source_order=config.video_source_order)
        used_ids = store.used_ids() | video_id_store.all_ids()
        downloaded, query = await find_and_download_video(config, used_ids, query=query)

        if downloaded.video_id.startswith("youtube-"):
            caption = build_caption_from_youtube(
                title=downloaded.title,
                description=downloaded.description,
                hashtags=config.default_hashtags_list,
            )
        else:
            caption = build_caption(
                theme=config.caption_theme,
                hashtags=config.default_hashtags_list,
                query=query,
                title=downloaded.title,
            )
        source_url = downloaded.source_url
        download_url = downloaded.download_url
        downloaded_at = datetime.now().isoformat(timespec='seconds')
        attempts = 0

        store.upsert_record(VideoRecord(
            video_id=downloaded.video_id,
            query=query,
            file_path=str(downloaded.file_path),
            source_url=source_url,
            download_url=download_url,
            downloaded_at=downloaded_at,
            posted_at='',
            caption=caption,
            status='downloaded',
            attempts=attempts,
            last_error='',
        ))
        logger.info("Video downloaded and recorded",
                    video_id=downloaded.video_id,
                    file_path=str(downloaded.file_path))

    # Post to Instagram via Graph API
    try:
        async with InstagramAPIClient(
            ig_user_id=config.ig_user_id,
            access_token=config.ig_access_token,
        ) as client:
            if not downloaded.download_url:
                from .transfer_sh_uploader import upload_to_transfer_sh
                video_url = await upload_to_transfer_sh(downloaded.file_path, config)
                logger.info("Local video hosted at public host", url=video_url)
            else:
                video_url = downloaded.download_url

            logger.info("Posting video to Instagram via Graph API",
                        video_url=video_url,
                        caption_length=len(caption),
                        caption_preview=caption[:120].replace("\n", "\\n"))

            media_id = await client.create_and_publish(
                video_url=video_url,
                caption=caption,
                media_type="REELS",
                share_to_feed=True,
            )
            logger.info("Instagram post created", media_id=media_id)

    except Exception as exc:
        error_msg = str(exc)
        log_error(exc, {
            "context": "instagram_posting",
            "video_id": downloaded.video_id,
            "attempts": attempts + 1,
        })
        store.upsert_record(VideoRecord(
            video_id=downloaded.video_id,
            query=query,
            file_path=str(downloaded.file_path),
            source_url=source_url,
            download_url=download_url,
            downloaded_at=downloaded_at,
            posted_at='',
            caption=caption,
            status='failed',
            attempts=attempts + 1,
            last_error=error_msg,
        ))
        await _push_gist(config)
        raise

    posted_at_ts = datetime.now().isoformat(timespec='seconds')
    store.upsert_record(VideoRecord(
        video_id=downloaded.video_id,
        query=query,
        file_path=str(downloaded.file_path),
        source_url=source_url,
        download_url=download_url,
        downloaded_at=downloaded_at,
        posted_at=posted_at_ts,
        caption=caption,
        status='posted',
        attempts=attempts + 1,
        last_error='',
    ))
    video_id_store.add(downloaded.video_id, posted_at_ts)

    try:
        downloaded.file_path.unlink(missing_ok=True)
        logger.info("Deleted local temp file after successful post",
                    video_id=downloaded.video_id)
    except OSError as e:
        logger.warning("Failed to delete local temp file",
                       video_id=downloaded.video_id, error=str(e))

    logger.info("Instagram post completed successfully",
                video_id=downloaded.video_id, total_attempts=attempts + 1)
    await _push_gist(config)


async def _post_direct_video_id(
    config: AppConfig,
    store: PostedStateStore,
    video_id_store: VideoIdStore,
    raw_video_id: str,
) -> None:
    """Download and post a specific YouTube video ID, bypassing search."""
    logger.info("Direct VIDEO_ID mode — skipping search", raw_video_id=raw_video_id)

    yt_client = YouTubeClient(
        api_key=config.youtube_api_key,
        download_dir=config.download_dir_path,
        format_id=config.youtube_format,
        cookies_file=config.youtube_cookies_file,
    )
    downloaded = await yt_client.download_by_id(raw_video_id)

    caption = build_caption_from_youtube(
        title=downloaded.title,
        description=downloaded.description,
        hashtags=config.default_hashtags_list,
    )
    query = raw_video_id
    source_url = downloaded.source_url
    downloaded_at = datetime.now().isoformat(timespec='seconds')

    store.upsert_record(VideoRecord(
        video_id=downloaded.video_id,
        query=query,
        file_path=str(downloaded.file_path),
        source_url=source_url,
        download_url="",
        downloaded_at=downloaded_at,
        posted_at='',
        caption=caption,
        status='downloaded',
        attempts=0,
        last_error='',
    ))

    async with InstagramAPIClient(
        ig_user_id=config.ig_user_id,
        access_token=config.ig_access_token,
    ) as client:
        from .transfer_sh_uploader import upload_to_transfer_sh
        video_url = await upload_to_transfer_sh(downloaded.file_path, config)
        logger.info("Direct video hosted at public host", url=video_url)

        logger.info("Posting direct video to Instagram",
                    video_url=video_url,
                    caption_length=len(caption),
                    caption_preview=caption[:120].replace("\n", "\\n"))

        media_id = await client.create_and_publish(
            video_url=video_url,
            caption=caption,
            media_type="REELS",
            share_to_feed=True,
        )
        logger.info("Instagram post created (direct VIDEO_ID)", media_id=media_id)

    posted_at_ts = datetime.now().isoformat(timespec='seconds')
    store.upsert_record(VideoRecord(
        video_id=downloaded.video_id,
        query=query,
        file_path=str(downloaded.file_path),
        source_url=source_url,
        download_url=video_url,
        downloaded_at=downloaded_at,
        posted_at=posted_at_ts,
        caption=caption,
        status='posted',
        attempts=1,
        last_error='',
    ))
    video_id_store.add(downloaded.video_id, posted_at_ts)

    try:
        downloaded.file_path.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("Failed to delete local temp file", video_id=downloaded.video_id, error=str(e))

    logger.info("Direct VIDEO_ID post completed", video_id=downloaded.video_id)
    await _push_gist(config)


def _write_credentials_from_env() -> None:
    """Write credential files from base64 env vars if set (Railway/Render/CI use)."""
    import base64
    import os

    token_b64 = os.environ.get("GOOGLE_DRIVE_TOKEN_B64", "").strip()
    token_file = os.environ.get("GOOGLE_DRIVE_TOKEN_FILE", "token.json")
    if token_b64 and not Path(token_file).exists():
        try:
            Path(token_file).write_bytes(base64.b64decode(token_b64))
            print(f"Written Google Drive token to {token_file}")
        except Exception as e:
            print(f"Warning: failed to write Google Drive token: {e}")

    cookies_b64 = os.environ.get("YOUTUBE_COOKIES_B64", "").strip()
    cookies_file = os.environ.get("YOUTUBE_COOKIES_FILE", "/tmp/yt_cookies.txt")
    if cookies_b64 and not Path(cookies_file).exists():
        try:
            Path(cookies_file).parent.mkdir(parents=True, exist_ok=True)
            Path(cookies_file).write_bytes(base64.b64decode(cookies_b64))
            print(f"Written YouTube cookies to {cookies_file}")
        except Exception as e:
            print(f"Warning: failed to write YouTube cookies: {e}")


async def run_once() -> None:
    """Run one iteration of the Instagram auto-poster."""
    _write_credentials_from_env()
    try:
        config = load_config()
        setup_logging(config.log_level, config.log_file_path)
        logger.info("Starting Instagram auto-poster run")
    except Exception as e:
        print(f"Failed to load configuration: {e}")
        raise ConfigurationError(f"Configuration error: {e}") from e

    if not await run_health_check(config):
        logger.warning("Health check failed, but continuing with execution")

    store = PostedStateStore(config.posted_state_file_path)
    video_id_store = VideoIdStore(config.video_id_db_path)

    _gist_enabled = bool(config.gh_pat and config.state_gist_id)
    if _gist_enabled:
        logger.info("Pulling state from GitHub Gist", gist_id=config.state_gist_id)
        await pull_state_from_gist(
            gist_id=config.state_gist_id,
            github_token=config.gh_pat,
            local_path=config.posted_state_file_path,
        )
    else:
        logger.debug("Gist sync not configured — using local state only")

    # Direct video override: YOUTUBE_VIDEO_ID takes priority, then VIDEO_ID
    _direct_id = (config.youtube_video_id or "").strip() or (config.video_id or "").strip()
    if _direct_id:
        await _post_direct_video_id(config, store, video_id_store, _direct_id)
        return

    # Retry any pending/failed record first (one per run)
    pending = _find_pending_or_retry(store)
    if pending:
        await _post_single(config, store, video_id_store, query=pending.query, pending_record=pending)
        return

    # Post one video per configured query
    queries = config.youtube_queries_list
    logger.info("Starting run", query_count=len(queries), queries=queries)
    for query in queries:
        logger.info("Processing query", query=query)
        await _post_single(config, store, video_id_store, query=query, pending_record=None)


async def run_health_check_only() -> None:
    """Run health check only and exit."""
    try:
        config = load_config()
        setup_logging(config.log_level, config.log_file_path)
        
        healthy = await run_health_check(config)
        if healthy:
            logger.info("System is healthy")
            sys.exit(0)
        else:
            logger.error("System health issues detected")
            sys.exit(1)
            
    except Exception as e:
        print(f"Health check failed: {e}")
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    try:
        # Check if health check only mode
        if len(sys.argv) > 1 and sys.argv[1] == '--health-check':
            asyncio.run(run_health_check_only())
        else:
            asyncio.run(run_once())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(1)
    except AutoPosterError as e:
        logger.error("Auto-poster error occurred", error=str(e))
        sys.exit(1)
    except Exception as e:
        logger.error("Unexpected error occurred", error=str(e), error_type=type(e).__name__)
        sys.exit(1)
