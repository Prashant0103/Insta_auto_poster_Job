"""Retry utilities with exponential backoff."""

from __future__ import annotations

import asyncio
import logging
from typing import TypeVar, Callable, Any, Type
from functools import wraps

from .exceptions import RetryExhaustedError

T = TypeVar('T')

logger = logging.getLogger(__name__)


async def retry_with_backoff(
    func: Callable[[], T],
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
) -> T:
    """
    Retry a function with exponential backoff.
    
    Args:
        func: The async function to retry
        max_attempts: Maximum number of attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        backoff_factor: Multiplier for delay between attempts
        exceptions: Tuple of exceptions to catch and retry on
        
    Returns:
        The result of the function call
        
    Raises:
        RetryExhaustedError: If all attempts are exhausted
    """
    last_exception = None
    
    for attempt in range(max_attempts):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func()
            else:
                return func()
        except exceptions as e:
            last_exception = e
            
            if attempt == max_attempts - 1:
                logger.error(
                    "All retry attempts exhausted",
                    extra={
                        "attempts": max_attempts,
                        "last_error": str(e),
                        "function": func.__name__ if hasattr(func, '__name__') else str(func)
                    }
                )
                raise RetryExhaustedError(
                    f"Failed after {max_attempts} attempts. Last error: {e}"
                ) from e
            
            delay = min(base_delay * (backoff_factor ** attempt), max_delay)
            logger.warning(
                "Function call failed, retrying",
                extra={
                    "attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "delay": delay,
                    "error": str(e),
                    "function": func.__name__ if hasattr(func, '__name__') else str(func)
                }
            )
            await asyncio.sleep(delay)
    
    # This should never be reached, but just in case
    raise RetryExhaustedError(f"Unexpected retry loop exit") from last_exception


def retry_on_failure(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
):
    """
    Decorator for retrying functions with exponential backoff.
    
    Args:
        max_attempts: Maximum number of attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        backoff_factor: Multiplier for delay between attempts
        exceptions: Tuple of exceptions to catch and retry on
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            async def retry_func() -> T:
                return await func(*args, **kwargs)
            
            return await retry_with_backoff(
                retry_func,
                max_attempts=max_attempts,
                base_delay=base_delay,
                max_delay=max_delay,
                backoff_factor=backoff_factor,
                exceptions=exceptions,
            )
        return wrapper
    return decorator