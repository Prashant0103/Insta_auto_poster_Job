"""Instagram Graph API client for publishing Reels/videos."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from .exceptions import InstagramError, InstagramAuthError, MediaProcessingError
from .logging_config import get_logger
from .retry_utils import retry_with_backoff

logger = get_logger(__name__)

# Graph API base URL
GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class InstagramAPIClient:
    """
    Client for posting videos to Instagram via the Instagram Graph API.

    Two-step flow:
      1. POST  /{ig_user_id}/media          – create a media container (returns creation_id)
      2. POST  /{ig_user_id}/media_publish  – publish the container
    """

    def __init__(self, ig_user_id: str, access_token: str) -> None:
        self.ig_user_id = ig_user_id
        self.access_token = access_token
        self._http: httpx.AsyncClient | None = None
        logger.info("Initialized Instagram API client", ig_user_id=ig_user_id)

    # ------------------------------------------------------------------ #
    # Context manager                                                       #
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "InstagramAPIClient":
        self._http = httpx.AsyncClient(timeout=120.0)
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def create_and_publish(
        self,
        video_url: str,
        caption: str,
        media_type: str = "REELS",
        share_to_feed: bool = True,
    ) -> str:
        """
        Create a media container and immediately publish it.

        Args:
            video_url:    Publicly accessible URL of the video file.
            caption:      Post caption (may include hashtags).
            media_type:   "REELS" (default) or "VIDEO".
            share_to_feed: Whether to share Reels to the main feed.

        Returns:
            The published media ID as a string.

        Raises:
            InstagramAuthError:    On 401 / invalid token responses.
            MediaProcessingError:  If the container stays in ERROR state.
            InstagramError:        For other API failures.
        """
        creation_id = await self._create_media_container(
            video_url=video_url,
            caption=caption,
            media_type=media_type,
            share_to_feed=share_to_feed,
        )

        await self._wait_for_container_ready(creation_id)

        media_id = await self._publish_container(creation_id)
        logger.info(
            "Instagram post published successfully",
            media_id=media_id,
            creation_id=creation_id,
        )
        return media_id

    # ------------------------------------------------------------------ #
    # Private helpers                                                       #
    # ------------------------------------------------------------------ #

    async def _create_media_container(
        self,
        video_url: str,
        caption: str,
        media_type: str,
        share_to_feed: bool,
    ) -> str:
        """
        POST /{ig_user_id}/media

        Returns the creation_id (container ID).
        """
        url = f"{GRAPH_API_BASE}/{self.ig_user_id}/media"
        params: dict[str, Any] = {
            "media_type": media_type,
            "video_url": video_url,
            "caption": caption,
            "access_token": self.access_token,
        }
        if media_type == "REELS":
            params["share_to_feed"] = str(share_to_feed).lower()

        logger.info(
            "Creating Instagram media container",
            media_type=media_type,
            video_url=video_url,
            caption_length=len(caption),
        )

        async def _call() -> str:
            assert self._http is not None, "Client not started; use async with"
            response = await self._http.post(url, params=params)
            self._raise_for_api_error(response, "create media container")
            data = response.json()
            creation_id: str = data["id"]
            logger.info("Media container created", creation_id=creation_id)
            return creation_id

        return await retry_with_backoff(
            _call,
            max_attempts=3,
            base_delay=5.0,
            exceptions=(InstagramError,),
        )

    async def _wait_for_container_ready(
        self,
        creation_id: str,
        poll_interval: float = 10.0,
        max_polls: int = 30,
    ) -> None:
        """
        Poll GET /{creation_id}?fields=status_code until FINISHED or ERROR.

        Instagram video containers take time to transcode server-side.
        """
        url = f"{GRAPH_API_BASE}/{creation_id}"
        params = {
            "fields": "status_code,status",
            "access_token": self.access_token,
        }

        assert self._http is not None, "Client not started; use async with"

        for attempt in range(1, max_polls + 1):
            response = await self._http.get(url, params=params)
            self._raise_for_api_error(response, "poll container status")
            data = response.json()
            status_code: str = data.get("status_code", "")

            logger.debug(
                "Container status poll",
                creation_id=creation_id,
                status_code=status_code,
                attempt=attempt,
            )

            if status_code == "FINISHED":
                logger.info("Container ready for publishing", creation_id=creation_id)
                return
            elif status_code == "ERROR":
                detail = data.get("status", "unknown error")
                raise MediaProcessingError(
                    f"Instagram media container entered ERROR state: {detail}"
                )
            # IN_PROGRESS or IN_PROGRESS_OPTIMIZING – keep waiting
            await asyncio.sleep(poll_interval)

        raise MediaProcessingError(
            f"Container {creation_id} did not finish processing after "
            f"{max_polls * poll_interval:.0f}s"
        )

    async def _publish_container(self, creation_id: str) -> str:
        """
        POST /{ig_user_id}/media_publish?creation_id=<id>

        Returns the published media ID.
        """
        url = f"{GRAPH_API_BASE}/{self.ig_user_id}/media_publish"
        params = {
            "creation_id": creation_id,
            "access_token": self.access_token,
        }

        logger.info("Publishing media container", creation_id=creation_id)

        async def _call() -> str:
            assert self._http is not None, "Client not started; use async with"
            response = await self._http.post(url, params=params)
            self._raise_for_api_error(response, "publish container")
            data = response.json()
            media_id: str = data["id"]
            logger.info("Media published", media_id=media_id)
            return media_id

        return await retry_with_backoff(
            _call,
            max_attempts=3,
            base_delay=5.0,
            exceptions=(InstagramError,),
        )

    # ------------------------------------------------------------------ #
    # Error handling                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _raise_for_api_error(response: httpx.Response, context: str) -> None:
        """Inspect the Graph API response and raise appropriate exceptions."""
        if response.status_code == 200:
            return  # fast path

        try:
            body = response.json()
            err = body.get("error", {})
            code = err.get("code", response.status_code)
            msg = err.get("message", response.text)
            err_type = err.get("type", "")
        except Exception:
            code = response.status_code
            msg = response.text
            err_type = ""

        logger.error(
            "Instagram API error",
            context=context,
            http_status=response.status_code,
            api_code=code,
            api_type=err_type,
            message=msg,
        )

        if response.status_code in (401, 403) or code in (190, 200, 102):
            raise InstagramAuthError(
                f"Instagram API authentication error [{context}]: {msg}"
            )

        raise InstagramError(
            f"Instagram API error [{context}] (HTTP {response.status_code}, "
            f"code={code}): {msg}"
        )
