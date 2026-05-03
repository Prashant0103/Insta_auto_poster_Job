from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from fastmcp import Client

from .exceptions import MCPError, MCPConnectionError, MCPAuthenticationError
from .logging_config import get_logger
from .retry_utils import retry_with_backoff

logger = get_logger(__name__)


class LoginPayload(BaseModel):
    """Payload for Instagram login."""
    url: str = Field(..., description="Instagram login URL")
    username: str = Field(..., description="Instagram username")
    password: str = Field(..., description="Instagram password")
    username_selector: str = Field(..., description="CSS selector for username field")
    password_selector: str = Field(..., description="CSS selector for password field")
    submit_selector: str = Field(..., description="CSS selector for submit button")


class InstagramPostPayload(BaseModel):
    """Payload for creating Instagram post."""
    image_path: str = Field(..., description="Path to media file (image or video)")
    caption: str = Field(..., description="Post caption")
    music_query: str = Field("", description="Music search query")
    allow_without_music: bool = Field(True, description="Allow posting without music")


class MCPAutomationClient:
    """MCP client for Instagram automation with enhanced error handling."""
    
    def __init__(self, server_url: str) -> None:
        self.server_url = server_url
        self._client = Client(server_url)
        logger.info("Initialized MCP client", server_url=server_url)

    async def __aenter__(self) -> 'MCPAutomationClient':
        try:
            await self._client.__aenter__()
            logger.info("Connected to MCP server")
            return self
        except Exception as e:
            logger.error("Failed to connect to MCP server", error=str(e))
            raise MCPConnectionError(f"Failed to connect to MCP server: {e}") from e

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            await self._client.__aexit__(exc_type, exc, tb)
            logger.info("Disconnected from MCP server")
        except Exception as e:
            logger.warning("Error during MCP client cleanup", error=str(e))

    async def login(self, payload: LoginPayload | dict[str, Any]) -> Any:
        """
        Perform Instagram login via MCP.
        
        Args:
            payload: Login credentials and selectors
            
        Returns:
            MCP response
            
        Raises:
            MCPAuthenticationError: If login fails
            MCPError: For other MCP-related errors
        """
        if isinstance(payload, dict):
            payload = LoginPayload(**payload)
        
        logger.info("Attempting Instagram login", username=payload.username)
        
        async def _login():
            try:
                result = await self._client.call_tool('login', payload.model_dump())
                logger.info("Instagram login successful")
                return result
            except Exception as e:
                logger.error("Instagram login failed", error=str(e))
                if "authentication" in str(e).lower() or "login" in str(e).lower():
                    raise MCPAuthenticationError(f"Instagram login failed: {e}") from e
                raise MCPError(f"MCP login call failed: {e}") from e
        
        return await retry_with_backoff(
            _login,
            max_attempts=2,  # Only retry once for login
            base_delay=2.0,
            exceptions=(MCPError,)
        )

    async def create_instagram_post(self, payload: InstagramPostPayload | dict[str, Any]) -> Any:
        """
        Create Instagram post via MCP.
        
        Args:
            payload: Post content and configuration
            
        Returns:
            MCP response
            
        Raises:
            MCPError: For MCP-related errors
        """
        if isinstance(payload, dict):
            payload = InstagramPostPayload(**payload)
        
        logger.info(
            "Creating Instagram post",
            image_path=payload.image_path,
            caption_length=len(payload.caption),
            music_query=payload.music_query
        )
        
        async def _create_post():
            try:
                result = await self._client.call_tool('create_instagram_post', payload.model_dump())
                logger.info("Instagram post created successfully")
                return result
            except Exception as e:
                logger.error("Instagram post creation failed", error=str(e))
                raise MCPError(f"MCP post creation failed: {e}") from e
        
        return await retry_with_backoff(
            _create_post,
            max_attempts=3,
            base_delay=5.0,
            exceptions=(MCPError,)
        )
