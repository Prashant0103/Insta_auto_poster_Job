from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from .caption_builder import build_caption
from .config import load_config, AppConfig
from .downloader import DownloadedVideo
from .instagram_api_client import InstagramAPIClient
from .gist_sync import pull_state_from_gist, push_state_to_gist
from .video_sources import find_and_download_video
from .state_store import PostedStateStore, VideoRecord
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
        downloaded, query = await find_and_download_video(config, store.used_ids(), query=query)

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
                video_url = await upload_to_transfer_sh(downloaded.file_path)
                logger.info("Local video hosted at public host", url=video_url)
            else:
                video_url = downloaded.download_url

            logger.info("Posting video to Instagram via Graph API",
                        video_url=video_url, caption_length=len(caption))

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

    store.upsert_record(VideoRecord(
        video_id=downloaded.video_id,
        query=query,
        file_path=str(downloaded.file_path),
        source_url=source_url,
        download_url=download_url,
        downloaded_at=downloaded_at,
        posted_at=datetime.now().isoformat(timespec='seconds'),
        caption=caption,
        status='posted',
        attempts=attempts + 1,
        last_error='',
    ))

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


async def run_once() -> None:
    """Run one iteration of the Instagram auto-poster."""
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

    # Retry any pending/failed record first (one per run)
    pending = _find_pending_or_retry(store)
    if pending:
        await _post_single(config, store, query=pending.query, pending_record=pending)
        return

    # Post one video per configured query
    queries = config.youtube_queries_list
    logger.info("Starting run", query_count=len(queries), queries=queries)
    for query in queries:
        logger.info("Processing query", query=query)
        await _post_single(config, store, query=query, pending_record=None)


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
