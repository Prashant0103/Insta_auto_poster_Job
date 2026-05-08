"""Custom exceptions for Instagram Auto Poster."""

from __future__ import annotations


class AutoPosterError(Exception):
    """Base exception for Instagram Auto Poster."""
    pass


class ConfigurationError(AutoPosterError):
    """Configuration validation or loading errors."""
    pass


class InstagramAPIError(AutoPosterError):
    """Instagram Graph API errors (replaces the former MCP-based errors)."""
    pass


class InstagramError(AutoPosterError):
    """Instagram-related errors."""
    pass


class InstagramAuthError(InstagramError):
    """Instagram authentication failures."""
    pass


class MediaProcessingError(AutoPosterError):
    """Media upload/processing issues."""
    pass


class PexelsError(AutoPosterError):
    """Pexels API errors."""
    pass


class PexelsAPIError(PexelsError):
    """Pexels API request failures."""
    pass


class PexelsNoResultsError(PexelsError):
    """No suitable videos found from Pexels."""
    pass


class YouTubeError(AutoPosterError):
    """YouTube search or download errors."""
    pass


class YouTubeAPIError(YouTubeError):
    """YouTube Data API request failures."""
    pass


class YouTubeNoResultsError(YouTubeError):
    """No suitable videos found from YouTube."""
    pass


class StateStoreError(AutoPosterError):
    """State management errors."""
    pass


class RetryExhaustedError(AutoPosterError):
    """Maximum retry attempts exceeded."""
    pass
