from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import validator, Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

from .exceptions import ConfigurationError


class AppConfig(BaseSettings):
    """Application configuration with validation."""
    
    # Pexels Configuration
    pexels_api_key: str = Field(..., description="Pexels API key")
    pexels_query: str = Field(..., description="Search query for Pexels videos")
    pexels_per_page: int = Field(20, ge=1, le=80, description="Number of videos per page")
    
    # Instagram Graph API Configuration
    ig_user_id: str = Field(..., description="Instagram Business/Creator account user ID")
    ig_access_token: str = Field(..., description="Instagram Graph API access token")
    
    # File Paths
    download_dir: str = Field("downloads", description="Directory for downloaded videos")
    posted_state_file: str = Field("posted_videos.json", description="State file path")
    
    # Content Configuration
    caption_theme: str = Field(..., description="Theme for generated captions")
    default_hashtags: str = Field(..., description="Comma-separated default hashtags")
    instagram_music_queries: str = Field("", description="Comma-separated music queries")
    
    # Posting Configuration
    allow_post_without_music: bool = Field(True, description="Allow posting without music")
    max_video_duration_seconds: int = Field(60, ge=1, le=300, description="Maximum video duration")
    min_aspect_ratio: float = Field(0.5, ge=0.1, le=10.0, description="Minimum aspect ratio")
    max_aspect_ratio: float = Field(2.0, ge=0.1, le=10.0, description="Maximum aspect ratio")
    
    # Logging Configuration
    log_level: str = Field("INFO", description="Logging level")
    log_file: str = Field("", description="Optional log file path")

    # Remote State Sync (GitHub Gist) — for GitHub Actions / Render free tier
    # When both are set the state file is pulled from the Gist at startup
    # and pushed back after every run, giving free persistent storage.
    gh_pat: Optional[str] = Field(None, description="GitHub PAT with gist scope (env var: GH_PAT)")
    state_gist_id: Optional[str] = Field(None, description="GitHub Gist ID for state storage")
    
    class Config:
        env_file = '.env'
        case_sensitive = False
        extra = 'ignore'  # Ignore extra fields in .env
        
    @validator('ig_access_token')
    def validate_ig_access_token(cls, v: str) -> str:
        """Validate Instagram access token is present."""
        if not v or len(v) < 10:
            raise ValueError('IG_ACCESS_TOKEN must be a valid Instagram Graph API token')
        return v

    @validator('ig_user_id')
    def validate_ig_user_id(cls, v: str) -> str:
        """Validate Instagram user ID is numeric."""
        if not v or not v.strip().isdigit():
            raise ValueError('IG_USER_ID must be a numeric Instagram account ID')
        return v.strip()
    
    @validator('min_aspect_ratio', 'max_aspect_ratio')
    def validate_aspect_ratios(cls, v: float, values: dict) -> float:
        """Validate aspect ratio values."""
        if 'min_aspect_ratio' in values and v < values['min_aspect_ratio']:
            raise ValueError('max_aspect_ratio must be greater than min_aspect_ratio')
        return v
    
    @validator('pexels_api_key')
    def validate_pexels_api_key(cls, v: str) -> str:
        """Validate Pexels API key format."""
        if not v or len(v) < 10:
            raise ValueError('Pexels API key must be at least 10 characters long')
        return v
    
    @validator('log_level')
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
        if v.upper() not in valid_levels:
            raise ValueError(f'Log level must be one of: {", ".join(valid_levels)}')
        return v.upper()
    
    @property
    def download_dir_path(self) -> Path:
        """Get download directory as Path object (absolute or cwd-relative)."""
        p = Path(self.download_dir)
        return p if p.is_absolute() else Path.cwd() / p

    @property
    def posted_state_file_path(self) -> Path:
        """Get posted state file as Path object (absolute or cwd-relative)."""
        p = Path(self.posted_state_file)
        return p if p.is_absolute() else Path.cwd() / p

    @property
    def log_file_path(self) -> Path | None:
        """Get log file as Path object if specified (absolute or cwd-relative)."""
        if self.log_file:
            p = Path(self.log_file)
            return p if p.is_absolute() else Path.cwd() / p
        return None
    
    @property
    def default_hashtags_list(self) -> List[str]:
        """Parse default hashtags from comma-separated string."""
        return [tag.strip() for tag in self.default_hashtags.split(',') if tag.strip()]
    
    @property
    def instagram_music_queries_list(self) -> List[str]:
        """Parse music queries from comma-separated string."""
        if not self.instagram_music_queries:
            return []
        return [query.strip() for query in self.instagram_music_queries.split(',') if query.strip()]


def load_config() -> AppConfig:
    """
    Load and validate application configuration.
    
    Returns:
        Validated AppConfig instance
        
    Raises:
        ConfigurationError: If configuration is invalid or missing
    """
    try:
        load_dotenv()
        return AppConfig()
    except Exception as e:
        raise ConfigurationError(f"Failed to load configuration: {e}") from e