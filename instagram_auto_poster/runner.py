from __future__ import annotations

import asyncio
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from .caption_builder import build_caption
from .config import load_config, AppConfig
from .downloader import DownloadedVideo, VideoDownloader
from .mcp_client import MCPAutomationClient, LoginPayload, InstagramPostPayload
from .pexels_client import PexelsClient, PexelsVideo
from .state_store import PostedStateStore, VideoRecord
from .health_check import HealthChecker
from .logging_config import setup_logging, get_logger, log_error
from .exceptions import (
    ConfigurationError, PexelsNoResultsError, MCPError, 
    MediaProcessingError, AutoPosterError
)

logger = get_logger(__name__)


def _build_downloaded_video(record: VideoRecord) -> DownloadedVideo:
    """Build DownloadedVideo from VideoRecord."""
    return DownloadedVideo(
        video_id=record.video_id,
        file_path=Path(record.file_path),
        source_url=record.source_url,
        download_url='',
    )


def _is_instagram_friendly(
    video: PexelsVideo, 
    max_duration: int, 
    min_ratio: float, 
    max_ratio: float
) -> bool:
    """Check if video meets Instagram requirements."""
    if video.duration <= 0 or video.duration > max_duration:
        logger.debug("Video rejected for duration", 
                    video_id=video.video_id,
                    duration=video.duration,
                    max_duration=max_duration)
        return False
    
    ratio = video.aspect_ratio
    if ratio < min_ratio or ratio > max_ratio:
        logger.debug("Video rejected for aspect ratio", 
                    video_id=video.video_id,
                    aspect_ratio=ratio,
                    min_ratio=min_ratio,
                    max_ratio=max_ratio)
        return False
    
    if video.width <= 0 or video.height <= 0:
        logger.debug("Video rejected for invalid dimensions", 
                    video_id=video.video_id,
                    width=video.width,
                    height=video.height)
        return False
    
    return True


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
                   mcp_reachable=status.mcp_server_reachable,
                   pexels_accessible=status.pexels_api_accessible,
                   pending_downloads=status.pending_downloads,
                   recent_failures=status.failed_attempts_last_24h)
        
        if not status.overall_healthy:
            logger.warning("System health issues detected", issues=status.issues)
        
        return status.overall_healthy
        
    except Exception as e:
        log_error(e, {"context": "health_check"})
        return False


async def run_once() -> None:
    """
    Run one iteration of the Instagram auto-poster.
    
    Raises:
        ConfigurationError: If configuration is invalid
        PexelsNoResultsError: If no suitable videos found
        MCPError: If MCP operations fail
        MediaProcessingError: If media processing fails
    """
    # Load configuration and setup logging
    try:
        config = load_config()
        setup_logging(config.log_level, config.log_file_path)
        logger.info("Starting Instagram auto-poster run")
    except Exception as e:
        print(f"Failed to load configuration: {e}")
        raise ConfigurationError(f"Configuration error: {e}") from e
    
    # Run health check first
    if not await run_health_check(config):
        logger.warning("Health check failed, but continuing with execution")
    
    # Initialize components
    store = PostedStateStore(config.posted_state_file_path)
    
    # First, check for pending download (downloaded but not posted)
    pending_record = store.get_pending_download()
    logger.info("Checked for pending downloads", found=pending_record is not None)
    
    # If no pending download, check for failed posts that can be retried
    if pending_record is None:
        failed_records = store.get_failed_records(max_attempts=3)
        logger.info("Checked for failed records", count=len(failed_records))
        
        if failed_records:
            # Find a failed record with existing file
            for record in failed_records:
                file_exists = Path(record.file_path).exists()
                logger.info("Checking failed record", 
                          video_id=record.video_id,
                          attempts=record.attempts,
                          file_exists=file_exists)
                          
                if file_exists:
                    pending_record = record
                    logger.info("Retrying failed post", 
                              video_id=record.video_id,
                              attempts=record.attempts,
                              file_path=record.file_path,
                              last_error=record.last_error[:100] + "..." if len(record.last_error) > 100 else record.last_error)
                    break
                else:
                    logger.warning("Failed record file missing", 
                                 video_id=record.video_id,
                                 file_path=record.file_path)
    
    # Check for pending download to resume or retry
    if pending_record is not None:
        downloaded = _build_downloaded_video(pending_record)
        caption = pending_record.caption or build_caption(
            theme=config.caption_theme,
            hashtags=config.default_hashtags_list,
            query=pending_record.query,
        )
        music_query = pending_record.music_query or (
            random.choice(config.instagram_music_queries_list) 
            if config.instagram_music_queries_list else ''
        )
        query = pending_record.query
        source_url = pending_record.source_url
        downloaded_at = pending_record.downloaded_at
        attempts = pending_record.attempts
        
        logger.info("Resuming with previously downloaded video", 
                   video_id=downloaded.video_id,
                   file_path=str(downloaded.file_path),
                   attempts=attempts)
    else:
        # Search and download new video
        logger.info("Searching for new video", query=config.pexels_query)
        
        async with PexelsClient(config.pexels_api_key) as pexels:
            try:
                videos = await pexels.search_videos(config.pexels_query, config.pexels_per_page)
            except Exception as e:
                log_error(e, {"context": "pexels_search", "query": config.pexels_query})
                raise
        
        if not videos:
            raise PexelsNoResultsError(f'No Pexels videos returned for query: {config.pexels_query}')

        # Filter videos
        used_ids = store.used_ids()
        candidates = [
            video for video in videos
            if video.video_id not in used_ids
            and _is_instagram_friendly(
                video,
                max_duration=config.max_video_duration_seconds,
                min_ratio=config.min_aspect_ratio,
                max_ratio=config.max_aspect_ratio,
            )
        ]
        
        logger.info("Filtered video candidates", 
                   total_videos=len(videos),
                   used_videos=len(used_ids),
                   candidates=len(candidates))
        
        if not candidates:
            raise PexelsNoResultsError(
                'No Instagram-friendly unposted Pexels videos found in the fetched set.'
            )

        # Download chosen video
        chosen_video = random.choice(candidates)
        logger.info("Selected video for download", 
                   video_id=chosen_video.video_id,
                   duration=chosen_video.duration,
                   dimensions=f"{chosen_video.width}x{chosen_video.height}")
        
        async with VideoDownloader(config.download_dir_path) as downloader:
            try:
                downloaded = await downloader.download(chosen_video)
            except Exception as e:
                log_error(e, {"context": "video_download", "video_id": chosen_video.video_id})
                raise
        
        # Generate content
        caption = build_caption(
            theme=config.caption_theme,
            hashtags=config.default_hashtags_list,
            query=config.pexels_query,
        )
        music_query = (
            random.choice(config.instagram_music_queries_list) 
            if config.instagram_music_queries_list else ''
        )
        query = config.pexels_query
        source_url = downloaded.source_url
        downloaded_at = datetime.now().isoformat(timespec='seconds')
        attempts = 0

        # Save download record
        store.upsert_record(
            VideoRecord(
                video_id=downloaded.video_id,
                query=query,
                file_path=str(downloaded.file_path),
                source_url=source_url,
                downloaded_at=downloaded_at,
                posted_at='',
                caption=caption,
                music_query=music_query,
                status='downloaded',
                attempts=attempts,
                last_error='',
            )
        )
        
        logger.info("Video downloaded and recorded", 
                   video_id=downloaded.video_id,
                   file_path=str(downloaded.file_path))

    # Post to Instagram via MCP
    try:
        async with MCPAutomationClient(config.mcp_server_url) as client:
            # Login
            login_payload = LoginPayload(
                url=config.instagram_login_url,
                username=config.instagram_username,
                password=config.instagram_password,
                username_selector=config.instagram_username_selector,
                password_selector=config.instagram_password_selector,
                submit_selector=config.instagram_submit_selector,
            )
            
            login_result = await client.login(login_payload)
            logger.info("Instagram login completed", result=login_result)

            # Create post
            post_payload = InstagramPostPayload(
                media_path=str(downloaded.file_path),
                caption=caption,
                music_query=music_query,
                allow_without_music=config.allow_post_without_music,
            )
            
            post_result = await client.create_instagram_post(post_payload)
            logger.info("Instagram post created", result=post_result)
            
    except Exception as exc:
        # Record failure
        error_msg = str(exc)
        log_error(exc, {
            "context": "instagram_posting",
            "video_id": downloaded.video_id,
            "attempts": attempts + 1
        })
        
        store.upsert_record(
            VideoRecord(
                video_id=downloaded.video_id,
                query=query,
                file_path=str(downloaded.file_path),
                source_url=source_url,
                downloaded_at=downloaded_at,
                posted_at='',
                caption=caption,
                music_query=music_query,
                status='failed',
                attempts=attempts + 1,
                last_error=error_msg,
            )
        )
        raise

    # Record success
    store.upsert_record(
        VideoRecord(
            video_id=downloaded.video_id,
            query=query,
            file_path=str(downloaded.file_path),
            source_url=source_url,
            downloaded_at=downloaded_at,
            posted_at=datetime.now().isoformat(timespec='seconds'),
            caption=caption,
            music_query=music_query,
            status='posted',
            attempts=attempts + 1,
            last_error='',
        )
    )
    
    logger.info("Instagram post completed successfully", 
               video_id=downloaded.video_id,
               total_attempts=attempts + 1)


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