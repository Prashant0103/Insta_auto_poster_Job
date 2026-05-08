from __future__ import annotations

from dataclasses import dataclass
from typing import List

import httpx

from .exceptions import PexelsAPIError, PexelsNoResultsError
from .logging_config import get_logger
from .retry_utils import retry_with_backoff

logger = get_logger(__name__)

PEXELS_API_URL = 'https://api.pexels.com/videos/search'


@dataclass(slots=True)
class PexelsVideo:
    """Represents a video from Pexels API."""
    video_id: str
    source_url: str
    download_url: str
    duration: int
    width: int
    height: int

    @property
    def aspect_ratio(self) -> float:
        """Calculate aspect ratio of the video."""
        if not self.height:
            return 0.0
        return self.width / self.height


class PexelsClient:
    """Async Pexels API client with enhanced error handling."""
    
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            headers={'Authorization': self.api_key},
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )
        logger.info("Initialized Pexels client")

    async def __aenter__(self) -> 'PexelsClient':
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._client.__aexit__(exc_type, exc_val, exc_tb)

    async def search_videos(self, query: str, per_page: int) -> List[PexelsVideo]:
        """
        Search for videos on Pexels.
        
        Args:
            query: Search query string
            per_page: Number of videos to fetch per page
            
        Returns:
            List of PexelsVideo objects
            
        Raises:
            PexelsAPIError: If API request fails
            PexelsNoResultsError: If no videos are found
        """
        logger.info("Searching Pexels videos", query=query, per_page=per_page)
        
        async def _search():
            try:
                response = await self._client.get(
                    PEXELS_API_URL,
                    params={'query': query, 'per_page': per_page}
                )
                response.raise_for_status()
                
                payload = response.json()
                videos = self._parse_videos(payload)
                
                logger.info("Pexels search completed", 
                          videos_found=len(videos), 
                          total_hits=payload.get('total_results', 0))
                
                if not videos:
                    raise PexelsNoResultsError(f"No videos found for query: {query}")
                
                return videos
                
            except httpx.HTTPStatusError as e:
                logger.error("Pexels API HTTP error", 
                           status_code=e.response.status_code,
                           response_text=e.response.text)
                raise PexelsAPIError(f"Pexels API error {e.response.status_code}: {e.response.text}") from e
            except httpx.RequestError as e:
                logger.error("Pexels API request error", error=str(e))
                raise PexelsAPIError(f"Pexels API request failed: {e}") from e
            except Exception as e:
                logger.error("Unexpected error in Pexels search", error=str(e))
                raise PexelsAPIError(f"Unexpected Pexels API error: {e}") from e
        
        return await retry_with_backoff(
            _search,
            max_attempts=3,
            base_delay=1.0,
            exceptions=(PexelsAPIError, httpx.RequestError)
        )

    def _parse_videos(self, payload: dict) -> List[PexelsVideo]:
        """
        Parse videos from Pexels API response.
        
        Args:
            payload: JSON response from Pexels API
            
        Returns:
            List of parsed PexelsVideo objects
        """
        videos: List[PexelsVideo] = []
        
        for item in payload.get('videos', []):
            try:
                file_info = self._pick_video_file(item.get('video_files', []))
                if not file_info:
                    logger.debug("Skipping video without suitable MP4 file", video_id=item.get('id'))
                    continue
                
                video = PexelsVideo(
                    video_id=f"pexels-{item['id']}",
                    source_url=item.get('url', ''),
                    download_url=file_info['link'],
                    duration=item.get('duration', 0),
                    width=file_info.get('width') or 0,
                    height=file_info.get('height') or 0,
                )
                videos.append(video)
                
                logger.debug("Parsed Pexels video", 
                           video_id=video.video_id,
                           duration=video.duration,
                           dimensions=f"{video.width}x{video.height}")
                
            except (KeyError, TypeError) as e:
                logger.warning("Failed to parse video from Pexels response", 
                             video_id=item.get('id'), 
                             error=str(e))
                continue
        
        return videos

    @staticmethod
    def _pick_video_file(video_files: List[dict]) -> dict | None:
        """
        Pick the best video file from available options.
        
        Args:
            video_files: List of video file options from Pexels
            
        Returns:
            Best video file dict or None if no suitable file found
        """
        mp4_files = [
            vf for vf in video_files 
            if vf.get('file_type') == 'video/mp4' and vf.get('link')
        ]
        
        if not mp4_files:
            return None
        
        # Sort by resolution (smallest first for faster downloads)
        mp4_files.sort(key=lambda item: (
            (item.get('width') or 0), 
            (item.get('height') or 0)
        ))
        
        return mp4_files[0]
