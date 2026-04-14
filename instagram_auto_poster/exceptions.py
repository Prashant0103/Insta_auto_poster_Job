"""Custom exceptions for Instagram Auto Poster."""

from __future__ import annotations


class AutoPosterError(Exception):
    """Base exception for Instagram Auto Poster."""
    pass


class ConfigurationError(AutoPosterError):
    """Configuration validation or loading errors."""
    pass


class MCPError(AutoPosterError):
    """Base MCP error."""
    pass


class MCPConnectionError(MCPError):
    """MCP server connection issues."""
    pass


class MCPAuthenticationError(MCPError):
    """MCP authentication failures."""
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


class StateStoreError(AutoPosterError):
    """State management errors."""
    pass


class RetryExhaustedError(AutoPosterError):
    """Maximum retry attempts exceeded."""
    pass