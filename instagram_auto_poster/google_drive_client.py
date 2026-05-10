from __future__ import annotations

import asyncio
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .exceptions import MediaProcessingError
from .logging_config import get_logger

logger = get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]


class GoogleDriveUploader:
    def __init__(self, token_file: str, folder_id: str) -> None:
        self.token_file = token_file
        self.folder_id = folder_id

    def _get_service(self):
        token_path = Path(self.token_file)
        if not token_path.exists():
            raise MediaProcessingError(
                f"Google Drive token file not found: {self.token_file}. "
                "Run the auth flow from the google_driveapi_setup project to generate token.json, "
                "then copy it here."
            )

        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token_path.write_text(creds.to_json())
                logger.info("Google Drive token refreshed")
            else:
                raise MediaProcessingError(
                    "Google Drive token is invalid and cannot be refreshed. "
                    "Re-run the auth flow in google_driveapi_setup to generate a fresh token.json."
                )

        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def _upload_sync(self, file_path: Path) -> str:
        service = self._get_service()

        file_metadata = {
            "name": file_path.name,
            "parents": [self.folder_id],
        }
        media = MediaFileUpload(str(file_path), mimetype="video/mp4", resumable=True)

        logger.info("Uploading to Google Drive",
                    file=file_path.name, folder=self.folder_id)

        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id",
        ).execute()

        file_id = uploaded["id"]

        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

        url = (
            f"https://drive.usercontent.google.com/download"
            f"?id={file_id}&export=download&confirm=t"
        )
        logger.info("Google Drive upload successful", file_id=file_id, url=url)
        return url

    async def upload(self, file_path: Path) -> str:
        return await asyncio.to_thread(self._upload_sync, file_path)
