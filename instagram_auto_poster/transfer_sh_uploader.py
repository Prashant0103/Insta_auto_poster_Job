"""Temporary public file hosting via transfer.sh — no account or API key required.

The Instagram Graph API requires a public HTTPS URL to download and transcode
the video. The locally merged (music-added) video has no public URL, so we
upload it to transfer.sh, get a temporary URL, pass it to the Graph API,
then the file auto-expires after 14 days (or we delete it immediately).

transfer.sh is a free, open-source, no-signup service.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from .exceptions import MediaProcessingError
from .logging_config import get_logger

logger = get_logger(__name__)

_TRANSFER_SH_URL = "https://transfer.sh"


async def upload_to_transfer_sh(file_path: Path) -> str:
    """
    Upload a file to transfer.sh and return its public HTTPS URL.

    Args:
        file_path: Local path to the file to upload.

    Returns:
        Public HTTPS URL valid for 14 days.

    Raises:
        MediaProcessingError: If upload fails.
    """
    upload_url = f"{_TRANSFER_SH_URL}/{file_path.name}"

    logger.info("Uploading merged video to transfer.sh", path=str(file_path))

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            with file_path.open("rb") as fh:
                response = await client.put(
                    upload_url,
                    content=fh,
                    headers={"Max-Days": "1"},   # expire after 1 day — minimum needed
                )
            response.raise_for_status()
            public_url = response.text.strip()

    except httpx.HTTPStatusError as e:
        raise MediaProcessingError(
            f"transfer.sh upload failed (HTTP {e.response.status_code})"
        ) from e
    except Exception as e:
        raise MediaProcessingError(f"transfer.sh upload error: {e}") from e

    if not public_url.startswith("https://"):
        raise MediaProcessingError(f"transfer.sh returned unexpected response: {public_url[:200]}")

    logger.info("transfer.sh upload successful", url=public_url)
    return public_url
