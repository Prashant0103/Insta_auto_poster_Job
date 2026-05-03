"""GitHub Gist-based remote state sync for Render free tier.

On Render's free plan there is no persistent disk. This module
pulls posted_videos.json from a GitHub Gist at startup and pushes
the updated file back after each successful run, giving us free,
permanent state storage with no extra dependencies (httpx is already used).

Setup:
  1. Create a secret GitHub Gist with a single file called
     'posted_videos.json' containing: {"posted_videos": []}
  2. Generate a GitHub PAT with the 'gist' scope.
  3. Set GITHUB_TOKEN and STATE_GIST_ID in Render env vars.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from .logging_config import get_logger

logger = get_logger(__name__)

_GIST_FILENAME = "posted_videos.json"
_GITHUB_API = "https://api.github.com"


async def pull_state_from_gist(
    gist_id: str,
    github_token: str,
    local_path: Path,
) -> bool:
    """
    Download state JSON from a GitHub Gist to a local file.

    Args:
        gist_id:      ID of the secret GitHub Gist.
        github_token: Personal Access Token with 'gist' scope.
        local_path:   Where to write the state file locally.

    Returns:
        True if the file was pulled successfully, False otherwise.
        On failure the caller should proceed with an empty state.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{_GITHUB_API}/gists/{gist_id}",
                headers={
                    "Authorization": f"token {github_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            response.raise_for_status()
            data = response.json()

        files = data.get("files", {})
        if _GIST_FILENAME not in files:
            logger.warning(
                "State file not found in gist — starting with empty state",
                gist_id=gist_id,
                filename=_GIST_FILENAME,
            )
            return False

        content = files[_GIST_FILENAME].get("content", '{"posted_videos": []}')

        # Validate it is valid JSON before writing
        parsed = json.loads(content)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(content, encoding="utf-8")

        record_count = len(parsed.get("posted_videos", []))
        logger.info(
            "Pulled state from GitHub Gist",
            gist_id=gist_id,
            records=record_count,
        )
        return True

    except json.JSONDecodeError as e:
        logger.error("Gist state file contains invalid JSON", error=str(e))
        return False
    except httpx.HTTPStatusError as e:
        logger.error(
            "HTTP error pulling gist state",
            status=e.response.status_code,
            error=e.response.text[:200],
        )
        return False
    except Exception as e:
        logger.warning("Failed to pull state from gist", error=str(e))
        return False


async def push_state_to_gist(
    gist_id: str,
    github_token: str,
    local_path: Path,
) -> bool:
    """
    Upload the local state file to a GitHub Gist.

    Args:
        gist_id:      ID of the secret GitHub Gist.
        github_token: Personal Access Token with 'gist' scope.
        local_path:   Local state file to read and upload.

    Returns:
        True if pushed successfully, False otherwise.
    """
    if not local_path.exists():
        logger.warning("Local state file not found, nothing to push", path=str(local_path))
        return False

    try:
        content = local_path.read_text(encoding="utf-8")
        # Sanity-check before pushing
        parsed = json.loads(content)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.patch(
                f"{_GITHUB_API}/gists/{gist_id}",
                headers={
                    "Authorization": f"token {github_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                json={"files": {_GIST_FILENAME: {"content": content}}},
            )
            response.raise_for_status()

        record_count = len(parsed.get("posted_videos", []))
        logger.info(
            "Pushed state to GitHub Gist",
            gist_id=gist_id,
            records=record_count,
        )
        return True

    except json.JSONDecodeError as e:
        logger.error("Local state file contains invalid JSON, not pushing", error=str(e))
        return False
    except httpx.HTTPStatusError as e:
        logger.error(
            "HTTP error pushing gist state",
            status=e.response.status_code,
            error=e.response.text[:200],
        )
        return False
    except Exception as e:
        logger.error("Failed to push state to gist", error=str(e))
        return False
