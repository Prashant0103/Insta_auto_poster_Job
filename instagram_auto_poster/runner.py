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
from .instagram_api_client import InstagramAPIClient
from .gist_sync import pull_state_from_gist, push_state_to_gist
from .music_client import MusicClient
from .video_processor import merge_video_with_music
from .pexels_client import PexelsClient, PexelsVideo
from .state_store import PostedStateStore, VideoRecord
from .health_check import HealthChecker
from .logging_config import setup_logging, get_logger, log_error
from .exceptions import (
    ConfigurationError, PexelsNoResultsError, InstagramError,
    MediaProcessingError, AutoPosterError
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


async def run_once() -> None:
    """
    Run one iteration of the Instagram auto-poster.
    
    Raises:
        ConfigurationError: If configuration is invalid
        PexelsNoResultsError: If no suitable videos found
        InstagramError: If Instagram Graph API operations fail
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

    # Pull remote state from GitHub Gist (Render free tier — no persistent disk)
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
        download_url = pending_record.download_url
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
        download_url = downloaded.download_url
        downloaded_at = datetime.now().isoformat(timespec='seconds')
        attempts = 0

        # Save download record
        store.upsert_record(
            VideoRecord(
                video_id=downloaded.video_id,
                query=query,
                file_path=str(downloaded.file_path),
                source_url=source_url,
                download_url=download_url,
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

    # ── Add background music ───────────────────────────────────────────
    # Search Pixabay for a music track matching the music_query, download
    # it, and let ffmpeg bake it into the video before uploading.
    # If anything fails the original silent video is used as a fallback.
    upload_file_path = downloaded.file_path   # may be replaced below
    music_file: Path | None = None

    try:
        async with MusicClient(config.pixabay_api_key) as music:
            track = await music.get_random_track(config.music_query)

        if track:
            music_file = downloaded.file_path.with_suffix(".music.mp3")
            async with MusicClient(config.pixabay_api_key) as music:
                await music.download_track(track, music_file)

            merged_path = downloaded.file_path.with_suffix(".merged.mp4")
            merge_video_with_music(
                video_path=downloaded.file_path,
                music_path=music_file,
                output_path=merged_path,
                music_volume=config.music_volume,
            )
            upload_file_path = merged_path
            logger.info("Using music-merged video for upload",
                        track=track.title,
                        path=str(merged_path))
        else:
            logger.warning("No music track found — uploading original video")

    except Exception as e:
        logger.warning(
            "Music step failed — falling back to original video",
            error=str(e),
        )
        # Clean up any partial music file
        if music_file and music_file.exists():
            music_file.unlink(missing_ok=True)

    # Post to Instagram via Graph API
    # The Graph API needs a public HTTPS URL. If music was merged, upload
    # the local file to transfer.sh (free, no account) to get one.
    # If no music was added, use the original Pexels CDN URL directly.
    try:
        async with InstagramAPIClient(
            ig_user_id=config.ig_user_id,
            access_token=config.ig_access_token,
        ) as client:
            if upload_file_path != downloaded.file_path:
                # Upload merged video to transfer.sh — returns a public URL
                from .transfer_sh_uploader import upload_to_transfer_sh
                video_url = await upload_to_transfer_sh(upload_file_path)
                logger.info("Merged video hosted at transfer.sh", url=video_url)
            else:
                video_url = downloaded.download_url

            logger.info(
                "Posting video to Instagram via Graph API",
                video_url=video_url,
                caption_length=len(caption),
            )

            media_id = await client.create_and_publish(
                video_url=video_url,
                caption=caption,
                media_type="REELS",
                share_to_feed=True,
            )
            logger.info("Instagram post created", media_id=media_id)
            # transfer.sh link expires automatically after 1 day — no cleanup needed
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
                download_url=download_url,
                downloaded_at=downloaded_at,
                posted_at='',
                caption=caption,
                music_query=music_query,
                status='failed',
                attempts=attempts + 1,
                last_error=error_msg,
            )
        )
        # Push failure state so next run knows this video already failed
        if _gist_enabled:
            await push_state_to_gist(
                gist_id=config.state_gist_id,
                github_token=config.gh_pat,
                local_path=config.posted_state_file_path,
            )
        raise

    # Record success
    store.upsert_record(
        VideoRecord(
            video_id=downloaded.video_id,
            query=query,
            file_path=str(downloaded.file_path),
            source_url=source_url,
            download_url=download_url,
            downloaded_at=downloaded_at,
            posted_at=datetime.now().isoformat(timespec='seconds'),
            caption=caption,
            music_query=music_query,
            status='posted',
            attempts=attempts + 1,
            last_error='',
        )
    )

    # Delete all local temp files now that the post is published
    try:
        downloaded.file_path.unlink(missing_ok=True)       # original video
        if music_file:
            music_file.unlink(missing_ok=True)              # music MP3
        if upload_file_path != downloaded.file_path:
            upload_file_path.unlink(missing_ok=True)        # merged video
        logger.info("Deleted local temp files after successful post",
                    video_id=downloaded.video_id)
    except OSError as e:
        logger.warning("Failed to delete local temp files",
                       video_id=downloaded.video_id,
                       error=str(e))

    logger.info("Instagram post completed successfully",
               video_id=downloaded.video_id,
               total_attempts=attempts + 1)

    # Push updated state to GitHub Gist so next run sees this video as posted
    if _gist_enabled:
        await push_state_to_gist(
            gist_id=config.state_gist_id,
            github_token=config.gh_pat,
            local_path=config.posted_state_file_path,
        )


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
