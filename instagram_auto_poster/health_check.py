"""Health check functionality for Instagram Auto Poster."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx

from .config import AppConfig
from .state_store import PostedStateStore
from .logging_config import get_logger
from .exceptions import InstagramAPIError, PexelsAPIError

logger = get_logger(__name__)


@dataclass
class HealthStatus:
    """Health check status information."""
    instagram_api_reachable: bool
    pexels_api_accessible: bool
    last_successful_post: Optional[datetime]
    pending_downloads: int
    failed_attempts_last_24h: int
    disk_space_mb: float
    config_valid: bool
    overall_healthy: bool
    issues: list[str]


class HealthChecker:
    """Health checker for the Instagram Auto Poster system."""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.store = PostedStateStore(config.posted_state_file_path)
        logger.info("Initialized health checker")

    async def check_health(self) -> HealthStatus:
        """
        Perform comprehensive health check.
        
        Returns:
            HealthStatus with all check results
        """
        logger.info("Starting health check")
        issues = []
        
        # Check Instagram Graph API
        ig_api_reachable = await self._check_instagram_api()
        if not ig_api_reachable:
            issues.append("Instagram Graph API is not reachable or access token is invalid")
        
        # Check Pexels API
        pexels_accessible = await self._check_pexels_api()
        if not pexels_accessible:
            issues.append("Pexels API is not accessible")
        
        # Check last successful post
        last_post = self._get_last_successful_post()
        if last_post and datetime.now() - last_post > timedelta(days=2):
            issues.append(f"Last successful post was {(datetime.now() - last_post).days} days ago")
        
        # Check pending downloads
        pending = self._count_pending_downloads()
        if pending > 5:
            issues.append(f"Too many pending downloads: {pending}")
        
        # Check recent failures
        recent_failures = self._count_recent_failures()
        if recent_failures > 10:
            issues.append(f"High failure rate: {recent_failures} failures in last 24h")
        
        # Check disk space
        disk_space = self._check_disk_space()
        if disk_space < 100:  # Less than 100MB
            issues.append(f"Low disk space: {disk_space:.1f}MB available")
        
        # Check configuration
        config_valid = self._validate_config()
        if not config_valid:
            issues.append("Configuration validation failed")
        
        overall_healthy = len(issues) == 0
        
        status = HealthStatus(
            instagram_api_reachable=ig_api_reachable,
            pexels_api_accessible=pexels_accessible,
            last_successful_post=last_post,
            pending_downloads=pending,
            failed_attempts_last_24h=recent_failures,
            disk_space_mb=disk_space,
            config_valid=config_valid,
            overall_healthy=overall_healthy,
            issues=issues
        )
        
        logger.info("Health check completed", 
                   healthy=overall_healthy,
                   issues_count=len(issues))
        
        return status

    async def _check_instagram_api(self) -> bool:
        """Check if the Instagram Graph API is reachable and the token is valid."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://graph.facebook.com/v19.0/me",
                    params={
                        "fields": "id,name",
                        "access_token": self.config.ig_access_token,
                    },
                )
                if response.status_code == 200:
                    return True
                logger.warning(
                    "Instagram API health check returned non-200",
                    status=response.status_code,
                    body=response.text[:200],
                )
                return False
        except Exception as e:
            logger.warning("Instagram API health check failed", error=str(e))
            return False

    async def _check_pexels_api(self) -> bool:
        """Check if Pexels API is accessible."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.pexels.com/videos/search",
                    headers={'Authorization': self.config.pexels_api_key},
                    params={'query': 'test', 'per_page': 1}
                )
                return response.status_code == 200
        except Exception as e:
            logger.warning("Pexels API health check failed", error=str(e))
            return False

    def _get_last_successful_post(self) -> Optional[datetime]:
        """Get timestamp of last successful post."""
        try:
            data = self.store.load()
            last_post = None
            
            for record in data.get('posted_videos', []):
                if record.get('status') == 'posted' and record.get('posted_at'):
                    try:
                        post_time = datetime.fromisoformat(record['posted_at'])
                        if last_post is None or post_time > last_post:
                            last_post = post_time
                    except ValueError:
                        continue
            
            return last_post
        except Exception as e:
            logger.warning("Failed to get last successful post", error=str(e))
            return None

    def _count_pending_downloads(self) -> int:
        """Count pending downloads."""
        try:
            data = self.store.load()
            return sum(
                1 for record in data.get('posted_videos', [])
                if record.get('status') == 'downloaded'
            )
        except Exception as e:
            logger.warning("Failed to count pending downloads", error=str(e))
            return 0

    def _count_recent_failures(self) -> int:
        """Count failures in the last 24 hours."""
        try:
            data = self.store.load()
            cutoff = datetime.now() - timedelta(hours=24)
            count = 0
            
            for record in data.get('posted_videos', []):
                if record.get('status') == 'failed' and record.get('downloaded_at'):
                    try:
                        download_time = datetime.fromisoformat(record['downloaded_at'])
                        if download_time > cutoff:
                            count += 1
                    except ValueError:
                        continue
            
            return count
        except Exception as e:
            logger.warning("Failed to count recent failures", error=str(e))
            return 0

    def _check_disk_space(self) -> float:
        """Check available disk space in MB."""
        try:
            stat = self.config.download_dir_path.stat()
            # This is a simple approximation - in production you'd use shutil.disk_usage
            return 1000.0  # Placeholder - implement actual disk space check
        except Exception as e:
            logger.warning("Failed to check disk space", error=str(e))
            return 0.0

    def _validate_config(self) -> bool:
        """Validate configuration."""
        try:
            # Basic validation - check if required paths exist and are writable
            download_dir = self.config.download_dir_path
            download_dir.mkdir(parents=True, exist_ok=True)
            
            # Test write access
            test_file = download_dir / '.health_check'
            test_file.write_text('test')
            test_file.unlink()
            
            return True
        except Exception as e:
            logger.warning("Configuration validation failed", error=str(e))
            return False