"""Cloudinary upload/delete helpers for hosting merged videos temporarily.

The Instagram Graph API requires a public HTTPS URL for video uploads.
Since the merged (music-added) video is a local file, we upload it to
Cloudinary, get a public URL, pass it to the Graph API, then delete it
from Cloudinary once the post is published.

Free Cloudinary tier: 25 credits/month (~500 uploads of a 60s video).
"""

from __future__ import annotations

import base64
import hashlib
import time
from pathlib import Path

import httpx

from .exceptions import MediaProcessingError
from .logging_config import get_logger

logger = get_logger(__name__)

_CLOUDINARY_UPLOAD_URL = "https://api.cloudinary.com/v1_1/{cloud_name}/video/upload"
_CLOUDINARY_DELETE_URL = "https://api.cloudinary.com/v1_1/{cloud_name}/video/destroy"


async def upload_to_cloudinary(
    file_path: Path,
    cloud_name: str,
    api_key: str,
    api_secret: str,
) -> tuple[str, str]:
    """
    Upload a video file to Cloudinary.

    Args:
        file_path:   Local path to the .mp4 file.
        cloud_name:  Your Cloudinary cloud name.
        api_key:     Cloudinary API key.
        api_secret:  Cloudinary API secret.

    Returns:
        (public_url, public_id) — use public_url for the Graph API,
        then pass public_id to delete_from_cloudinary afterwards.

    Raises:
        MediaProcessingError: On upload failure.
    """
    timestamp = str(int(time.time()))
    folder = "insta_auto_poster"

    # Build the signed upload signature
    params_to_sign = f"folder={folder}&timestamp={timestamp}"
    signature = hashlib.sha1(
        f"{params_to_sign}{api_secret}".encode()
    ).hexdigest()

    upload_url = _CLOUDINARY_UPLOAD_URL.format(cloud_name=cloud_name)

    logger.info("Uploading merged video to Cloudinary", path=str(file_path))

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            with file_path.open("rb") as fh:
                response = await client.post(
                    upload_url,
                    data={
                        "api_key": api_key,
                        "timestamp": timestamp,
                        "folder": folder,
                        "signature": signature,
                    },
                    files={"file": (file_path.name, fh, "video/mp4")},
                )
            response.raise_for_status()
            data = response.json()

    except httpx.HTTPStatusError as e:
        raise MediaProcessingError(
            f"Cloudinary upload failed (HTTP {e.response.status_code}): {e.response.text[:300]}"
        ) from e
    except Exception as e:
        raise MediaProcessingError(f"Cloudinary upload error: {e}") from e

    public_url = data.get("secure_url", "")
    public_id = data.get("public_id", "")

    if not public_url:
        raise MediaProcessingError(f"Cloudinary returned no URL: {data}")

    logger.info(
        "Cloudinary upload successful",
        public_id=public_id,
        url=public_url,
    )
    return public_url, public_id


async def delete_from_cloudinary(
    public_id: str,
    cloud_name: str,
    api_key: str,
    api_secret: str,
) -> None:
    """
    Delete a video from Cloudinary after it has been published to Instagram.

    Args:
        public_id:   The public_id returned by upload_to_cloudinary.
        cloud_name:  Your Cloudinary cloud name.
        api_key:     Cloudinary API key.
        api_secret:  Cloudinary API secret.
    """
    timestamp = str(int(time.time()))
    params_to_sign = f"public_id={public_id}&timestamp={timestamp}"
    signature = hashlib.sha1(
        f"{params_to_sign}{api_secret}".encode()
    ).hexdigest()

    delete_url = _CLOUDINARY_DELETE_URL.format(cloud_name=cloud_name)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                delete_url,
                data={
                    "public_id": public_id,
                    "api_key": api_key,
                    "timestamp": timestamp,
                    "signature": signature,
                },
            )
            response.raise_for_status()

        logger.info("Deleted video from Cloudinary", public_id=public_id)

    except Exception as e:
        # Non-fatal — the video will expire automatically anyway
        logger.warning(
            "Failed to delete from Cloudinary (non-fatal)",
            public_id=public_id,
            error=str(e),
        )
