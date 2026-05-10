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

async def _try_transfer_sh(client: httpx.AsyncClient, file_path: Path) -> str:
    response = await client.put(
        f"https://transfer.sh/{file_path.name}",
        content=file_path.read_bytes(),
        headers={"Max-Days": "1"},
    )
    response.raise_for_status()
    url = response.text.strip()
    if not url.startswith("https://"):
        raise ValueError(f"unexpected response: {url[:200]}")
    return url


async def _try_0x0(client: httpx.AsyncClient, file_path: Path) -> str:
    with file_path.open("rb") as fh:
        response = await client.post(
            "https://0x0.st",
            files={"file": (file_path.name, fh, "video/mp4")},
        )
    response.raise_for_status()
    url = response.text.strip()
    if not url.startswith("https://"):
        raise ValueError(f"unexpected response: {url[:200]}")
    return url


async def _try_catbox(client: httpx.AsyncClient, file_path: Path) -> str:
    with file_path.open("rb") as fh:
        response = await client.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": (file_path.name, fh, "video/mp4")},
        )
    response.raise_for_status()
    url = response.text.strip()
    if not url.startswith("https://"):
        raise ValueError(f"unexpected response: {url[:200]}")
    return url


async def _try_filebin(client: httpx.AsyncClient, file_path: Path) -> str:
    import time
    bin_id = f"igposter{int(time.time())}"
    response = await client.post(
        f"https://filebin.net/{bin_id}/{file_path.name}",
        content=file_path.read_bytes(),
        headers={"Content-Type": "video/mp4"},
    )
    response.raise_for_status()
    url = f"https://filebin.net/{bin_id}/{file_path.name}"
    return url


_UPLOAD_SERVICES = [
    ("transfer.sh", _try_transfer_sh),
    ("0x0.st", _try_0x0),
    ("catbox.moe", _try_catbox),
    ("filebin.net", _try_filebin),
]


async def _try_google_drive(file_path: Path, config) -> str:
    from .google_drive_client import GoogleDriveUploader
    uploader = GoogleDriveUploader(
        token_file=config.google_drive_token_file,
        folder_id=config.google_drive_folder_id,
    )
    return await uploader.upload(file_path)


async def upload_to_transfer_sh(file_path: Path, config=None) -> str:
    """
    Upload a file to a public host and return its HTTPS URL.
    Tries Google Drive first (when configured), then falls back to free services.

    Raises:
        MediaProcessingError: If all upload attempts fail.
    """
    logger.info("Uploading video to public host", path=str(file_path))

    if config is not None and (config.google_drive_folder_id or "").strip():
        try:
            url = await _try_google_drive(file_path, config)
            logger.info("Upload successful", service="google_drive", url=url)
            return url
        except Exception as e:
            logger.warning("Google Drive upload failed, falling back to public services",
                           error=str(e))

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        for name, attempt in _UPLOAD_SERVICES:
            try:
                url = await attempt(client, file_path)
                logger.info("Upload successful", service=name, url=url)
                return url
            except Exception as e:
                logger.warning("Upload service failed, trying next", service=name, error=str(e))

    raise MediaProcessingError(
        f"All upload services failed (google_drive, {', '.join(n for n, _ in _UPLOAD_SERVICES)})"
    )
