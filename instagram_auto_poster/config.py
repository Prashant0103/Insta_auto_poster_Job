from __future__ import annotations

from pathlib import Path
from typing import List

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
    
    # MCP Server Configuration
    mcp_server_url: str = Field(..., description="MCP server URL")
    
    # Instagram Configuration
    instagram_login_url: str = Field(..., description="Instagram login URL")
    instagram_username: str = Field(..., description="Instagram username")
    instagram_password: str = Field(..., description="Instagram password")
    instagram_username_selector: str = Field(..., description="CSS selector for username field")
    instagram_password_selector: str = Field(..., description="CSS selector for password field")
    instagram_submit_selector: str = Field(..., description="CSS selector for submit button")
    
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
    min_file_size_mb: float = Field(1.0, ge=0.1, le=100.0, description="Minimum file size in MB")
    max_file_size_mb: float = Field(50.0, ge=1.0, le=500.0, description="Maximum file size in MB")
    
    # Logging Configuration
    log_level: str = Field("INFO", description="Logging level")
    log_file: str = Field("", description="Optional log file path")
    
    class Config:
        env_file = '.env'
        case_sensitive = False
        extra = 'ignore'  # Ignore extra fields in .env
        
    @validator('mcp_server_url')
    def validate_mcp_url(cls, v: str) -> str:
        """Validate MCP server URL format."""
        if not v.startswith(('http://', 'https://')):
            raise ValueError('MCP server URL must start with http:// or https://')
        return v
    
    @validator('instagram_login_url')
    def validate_instagram_url(cls, v: str) -> str:
        """Validate Instagram URL format."""
        if not v.startswith(('http://', 'https://')):
            raise ValueError('Instagram URL must start with http:// or https://')
        return v
    
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
        """Get download directory as Path object."""
        return Path.cwd() / self.download_dir
    
    @property
    def posted_state_file_path(self) -> Path:
        """Get posted state file as Path object."""
        return Path.cwd() / self.posted_state_file
    
    @property
    def log_file_path(self) -> Path | None:
        """Get log file as Path object if specified."""
        if self.log_file:
            return Path.cwd() / self.log_file
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