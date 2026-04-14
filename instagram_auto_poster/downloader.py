from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

from .pexels_client import PexelsVideo
from .exceptions import MediaProcessingError
from .logging_config import get_logger
from .retry_utils import retry_with_backoff

logger = get_logger(__name__)


@dataclass(slots=True)
class DownloadedVideo:
    """Represents a downloaded video file."""
    video_id: int
    file_path: Path
    source_url: str
    download_url: str


class VideoDownloader:
    """Async video downloader with enhanced error handling."""
    
    def __init__(self, download_dir: Path) -> None:
        self.download_dir = download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            limits=httpx.Limits(max_keepalive_connections=2, max_connections=5)
        )
        logger.info("Initialized video downloader", download_dir=str(download_dir))

    async def __aenter__(self) -> 'VideoDownloader':
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._client.__aexit__(exc_type, exc_val, exc_tb)

    async def download(self, video: PexelsVideo) -> DownloadedVideo:
        """
        Download a video from Pexels.
        
        Args:
            video: PexelsVideo object to download
            
        Returns:
            DownloadedVideo object with local file path
            
        Raises:
            MediaProcessingError: If download fails
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_path = self.download_dir / f'{timestamp}_{video.video_id}.mp4'
        
        logger.info("Starting video download", 
                   video_id=video.video_id,
                   download_url=video.download_url,
                   file_path=str(file_path))
        
        async def _download():
            try:
                async with self._client.stream('GET', video.download_url) as response:
                    response.raise_for_status()
                    
                    total_size = int(response.headers.get('content-length', 0))
                    downloaded_size = 0
                    
                    with file_path.open('wb') as handle:
                        async for chunk in response.aiter_bytes(chunk_size=1024 * 512):
                            if chunk:
                                handle.write(chunk)
                                downloaded_size += len(chunk)
                                
                                # Log progress for large files
                                if total_size > 0 and downloaded_size % (1024 * 1024 * 5) == 0:  # Every 5MB
                                    progress = (downloaded_size / total_size) * 100
                                    logger.debug("Download progress", 
                                               video_id=video.video_id,
                                               progress_percent=f"{progress:.1f}%")
                
                # Verify file was created and has content
                if not file_path.exists() or file_path.stat().st_size == 0:
                    raise MediaProcessingError(f"Downloaded file is empty or missing: {file_path}")
                
                logger.info("Video download completed", 
                           video_id=video.video_id,
                           file_size_mb=f"{file_path.stat().st_size / (1024*1024):.2f}")
                
                return DownloadedVideo(
                    video_id=video.video_id,
                    file_path=file_path,
                    source_url=video.source_url,
                    download_url=video.download_url,
                )
                
            except httpx.HTTPStatusError as e:
                logger.error("HTTP error during download", 
                           video_id=video.video_id,
                           status_code=e.response.status_code,
                           response_text=e.response.text)
                raise MediaProcessingError(f"Download failed with HTTP {e.response.status_code}: {e.response.text}") from e
            except httpx.RequestError as e:
                logger.error("Request error during download", 
                           video_id=video.video_id,
                           error=str(e))
                raise MediaProcessingError(f"Download request failed: {e}") from e
            except OSError as e:
                logger.error("File system error during download", 
                           video_id=video.video_id,
                           file_path=str(file_path),
                           error=str(e))
                raise MediaProcessingError(f"File system error: {e}") from e
            except Exception as e:
                logger.error("Unexpected error during download", 
                           video_id=video.video_id,
                           error=str(e))
                raise MediaProcessingError(f"Unexpected download error: {e}") from e
        
        return await retry_with_backoff(
            _download,
            max_attempts=3,
            base_delay=2.0,
            exceptions=(MediaProcessingError, httpx.RequestError)
        )
