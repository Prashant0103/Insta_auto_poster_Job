from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, List

from filelock import FileLock

from .exceptions import StateStoreError
from .logging_config import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class VideoRecord:
    """Represents a video record in the state store."""
    video_id: int
    query: str
    file_path: str
    source_url: str
    downloaded_at: str
    posted_at: str
    caption: str
    music_query: str
    status: str  # 'downloaded', 'posted', 'failed'
    attempts: int
    last_error: str


class PostedStateStore:
    """Thread-safe state store for tracking posted videos."""
    
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_file = path.with_suffix('.lock')
        logger.info("Initialized state store", path=str(path))

    def _with_lock(self, func):
        """Execute function with file lock."""
        with FileLock(str(self._lock_file), timeout=30):
            return func()

    def load(self) -> dict[str, Any]:
        """
        Load state data from file.
        
        Returns:
            State data dictionary
        """
        def _load():
            try:
                if not self.path.exists():
                    logger.debug("State file does not exist, returning empty state")
                    return {'posted_videos': []}
                
                content = self.path.read_text(encoding='utf-8')
                data = json.loads(content)
                
                logger.debug("Loaded state data", 
                           video_count=len(data.get('posted_videos', [])))
                return data
                
            except (json.JSONDecodeError, OSError) as e:
                logger.error("Failed to load state file", error=str(e))
                raise StateStoreError(f"Failed to load state file: {e}") from e
        
        return self._with_lock(_load)

    def used_ids(self) -> set[int]:
        """
        Get set of video IDs that have been used (downloaded, posted, or failed).
        
        Returns:
            Set of used video IDs
        """
        payload = self.load()
        used = {
            int(item['video_id'])
            for item in payload.get('posted_videos', [])
            if item.get('status') in {'posted', 'downloaded', 'failed'}
        }
        
        logger.debug("Retrieved used video IDs", count=len(used))
        return used

    def get_pending_download(self) -> VideoRecord | None:
        """
        Get a video record that was downloaded but not yet posted.
        
        Returns:
            VideoRecord if found, None otherwise
        """
        payload = self.load()
        
        for item in payload.get('posted_videos', []):
            if item.get('status') != 'downloaded':
                continue
                
            file_path = Path(item.get('file_path', ''))
            if not file_path.exists():
                logger.warning("Downloaded file no longer exists", 
                             video_id=item.get('video_id'),
                             file_path=str(file_path))
                continue
            
            try:
                # Ensure all required fields are present with defaults
                normalized = {
                    'attempts': item.get('attempts', 0),
                    'last_error': item.get('last_error', ''),
                    **item,
                }
                record = VideoRecord(**normalized)
                
                logger.info("Found pending download", 
                           video_id=record.video_id,
                           file_path=record.file_path,
                           attempts=record.attempts)
                return record
                
            except (TypeError, ValueError) as e:
                logger.error("Failed to parse video record", 
                           video_id=item.get('video_id'),
                           error=str(e))
                continue
        
        logger.debug("No pending downloads found")
        return None

    def get_failed_records(self, max_attempts: int = 3) -> List[VideoRecord]:
        """
        Get failed records that haven't exceeded max attempts.
        
        Args:
            max_attempts: Maximum number of attempts allowed
            
        Returns:
            List of failed VideoRecord objects eligible for retry
        """
        payload = self.load()
        failed_records = []
        
        for item in payload.get('posted_videos', []):
            if (item.get('status') == 'failed' and 
                item.get('attempts', 0) < max_attempts):
                
                try:
                    record = VideoRecord(**item)
                    failed_records.append(record)
                except (TypeError, ValueError) as e:
                    logger.error("Failed to parse failed record", 
                               video_id=item.get('video_id'),
                               error=str(e))
                    continue
        
        logger.debug("Retrieved failed records", count=len(failed_records))
        return failed_records

    def upsert_record(self, record: VideoRecord) -> None:
        """
        Insert or update a video record.
        
        Args:
            record: VideoRecord to upsert
        """
        def _upsert():
            try:
                payload = self.load()
                records = payload.setdefault('posted_videos', [])
                
                # Find existing record
                updated = False
                for index, item in enumerate(records):
                    if int(item['video_id']) == int(record.video_id):
                        records[index] = asdict(record)
                        updated = True
                        logger.debug("Updated existing record", video_id=record.video_id)
                        break
                
                # Add new record if not found
                if not updated:
                    records.append(asdict(record))
                    logger.debug("Added new record", video_id=record.video_id)
                
                # Write back to file
                self.path.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False), 
                    encoding='utf-8'
                )
                
                logger.info("Upserted video record", 
                           video_id=record.video_id,
                           status=record.status,
                           attempts=record.attempts)
                
            except (OSError, json.JSONEncodeError) as e:
                logger.error("Failed to upsert record", 
                           video_id=record.video_id,
                           error=str(e))
                raise StateStoreError(f"Failed to upsert record: {e}") from e
        
        self._with_lock(_upsert)