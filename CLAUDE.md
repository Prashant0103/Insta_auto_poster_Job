# CLAUDE.md — Project Skills & Conventions

This file documents the architecture, coding patterns, and key decisions for the
**Instagram Auto Poster** project so that AI assistants (and new contributors) can
work effectively without re-reading every source file.

---

## Project Overview

A Python async CLI tool that:
1. Searches [Pexels](https://www.pexels.com/api/) for suitable short videos
2. Downloads the chosen video locally
3. Publishes it as an Instagram Reel via the **Instagram Graph API v19.0**
4. Persists posting state to a JSON file to prevent duplicates and support resume

Entry point: `main.py` → `instagram_auto_poster/runner.py:main()`

---

## Directory Structure

```
Insta_auto_poster_Job/
├── main.py                         # Thin CLI entry point
├── requirements.txt                # Runtime dependencies (no fastmcp)
├── .env.example                    # Template for required env vars
├── test_setup.py                   # Manual integration/smoke tests
├── register_daily_task.ps1         # Registers Windows Task Scheduler job
├── run_daily.ps1                   # Called by Task Scheduler
├── run.bat                         # Simple wrapper for run_daily.ps1
└── instagram_auto_poster/
    ├── __init__.py
    ├── config.py                   # Pydantic settings (AppConfig)
    ├── runner.py                   # Main pipeline orchestrator
    ├── instagram_api_client.py     # Graph API client (create + publish)
    ├── pexels_client.py            # Pexels video search
    ├── downloader.py               # Async video downloader
    ├── caption_builder.py          # Caption / hashtag generation
    ├── state_store.py              # Thread-safe JSON state (filelock)
    ├── health_check.py             # System health checks
    ├── retry_utils.py              # Exponential-backoff retry helper
    ├── logging_config.py           # structlog setup
    └── exceptions.py              # Custom exception hierarchy
```

---

## Key Environment Variables

All loaded via `pydantic_settings.BaseSettings` from `.env`:

| Variable | Type | Purpose |
|----------|------|---------|
| `PEXELS_API_KEY` | str | Pexels REST API key |
| `PEXELS_QUERY` | str | Video search query |
| `PEXELS_PER_PAGE` | int (1–80) | Results per search call |
| `IG_USER_ID` | str (numeric) | Instagram Business/Creator account ID |
| `IG_ACCESS_TOKEN` | str | Long-lived or System-User Graph API token |
| `DOWNLOAD_DIR` | str | Local directory for downloaded videos |
| `POSTED_STATE_FILE` | str | JSON state file path |
| `CAPTION_THEME` | str | Theme passed to `build_caption()` |
| `DEFAULT_HASHTAGS` | str | Comma-separated hashtag string |
| `INSTAGRAM_MUSIC_QUERIES` | str | Comma-separated music search terms |
| `ALLOW_POST_WITHOUT_MUSIC` | bool | Don't fail if music unavailable |
| `MAX_VIDEO_DURATION_SECONDS` | int | Filter out long videos |
| `MIN_ASPECT_RATIO` | float | Filter out too-wide videos |
| `MAX_ASPECT_RATIO` | float | Filter out too-tall videos |
| `LOG_LEVEL` | str | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `LOG_FILE` | str | Optional file path for log output |

> `AppConfig` lives in `config.py`. Always go through `load_config()` — never read
> env vars directly in other modules.

---

## Instagram Graph API Flow

Implemented in `instagram_api_client.py → InstagramAPIClient`.

```
Step 1  POST /{ig_user_id}/media
        params: media_type=REELS, video_url=<public URL>, caption=..., access_token=...
        → returns { "id": "<creation_id>" }

Step 2  GET  /{creation_id}?fields=status_code,status
        Poll every 10 s until status_code == "FINISHED" (or "ERROR")
        Timeout: 30 polls × 10 s = 300 s

Step 3  POST /{ig_user_id}/media_publish
        params: creation_id=<creation_id>, access_token=...
        → returns { "id": "<media_id>" }
```

- **Base URL**: `https://graph.facebook.com/v19.0`
- **video_url** must be a **publicly accessible HTTPS URL** — the Pexels CDN URL
  from `DownloadedVideo.source_url` is used directly (no local file upload needed).
- All three steps retry up to 3× with 5 s base delay via `retry_with_backoff`.

---

## Exception Hierarchy

```
AutoPosterError
├── ConfigurationError
├── InstagramAPIError          ← generic Graph API failure
├── InstagramError
│   └── InstagramAuthError    ← 401 / invalid token (codes 190, 200, 102)
├── MediaProcessingError      ← container stuck in ERROR or timeout
├── PexelsError
│   ├── PexelsAPIError
│   └── PexelsNoResultsError
├── StateStoreError
└── RetryExhaustedError
```

> When adding new error conditions, extend the existing hierarchy rather than
> raising bare `Exception`.

---

## Retry Utility

`retry_utils.py → retry_with_backoff(coro_factory, max_attempts, base_delay, exceptions)`

- Retries `max_attempts` times with `base_delay * 2^attempt` seconds between tries
- Only catches exception types listed in `exceptions` tuple
- Used in `InstagramAPIClient` (3 attempts, 5 s base) and historically in MCP (removed)

---

## State Store

`state_store.py → PostedStateStore`

- Persists a list of `VideoRecord` objects to a JSON file
- Uses `filelock.FileLock` to prevent concurrent writes
- Key methods:
  - `get_pending_download()` → first record with `status == "downloaded"`
  - `get_failed_records(max_attempts)` → records with `status == "failed"` below retry cap
  - `used_ids()` → set of all video IDs ever processed
  - `upsert_record(VideoRecord)` → insert or replace by `video_id`

---

## Health Check

`health_check.py → HealthChecker.check_health()` returns `HealthStatus`:

| Field | Source |
|-------|--------|
| `instagram_api_reachable` | `GET /v19.0/me` with `ig_access_token` |
| `pexels_api_accessible` | `GET api.pexels.com/videos/search?query=test&per_page=1` |
| `last_successful_post` | Scans state file for latest `status == "posted"` |
| `pending_downloads` | Count of `status == "downloaded"` records |
| `failed_attempts_last_24h` | Count of `status == "failed"` records in last 24 h |
| `disk_space_mb` | Write-access test to `download_dir` |
| `config_valid` | Creates / cleans a `.health_check` sentinel file |

Run standalone: `python main.py --health-check`

---

## Logging

`logging_config.py` configures [structlog](https://www.structlog.org/) with:
- Key-value structured output
- Configurable level via `LOG_LEVEL`
- Optional file sink via `LOG_FILE`

Usage pattern across all modules:
```python
from .logging_config import get_logger
logger = get_logger(__name__)
logger.info("Message", key=value, ...)
```

---

## Adding a New Feature — Checklist

1. **New config field**: Add to `AppConfig` in `config.py` with a `Field(...)` and validator if needed. Add to `.env.example`.
2. **New exception type**: Extend the hierarchy in `exceptions.py`.
3. **New API call**: Follow the `_raise_for_api_error` + `retry_with_backoff` pattern in `instagram_api_client.py`.
4. **New state field**: Update `VideoRecord` in `state_store.py` (and migration logic if the field is required).
5. **New health check**: Add a private `_check_*` method in `HealthChecker` and wire it into `check_health()`.

---

## Common Pitfalls

- **Token expiry**: Long-lived tokens last 60 days. The health check catches an expired token. For production, use a non-expiring System User Token.
- **video_url must be public**: The Graph API fetches the video from the URL you supply. Local file paths will not work.
- **Container status polling**: Instagram transcoding can take 1–5 minutes. Do not reduce `max_polls` below 18 (3 min) for videos up to 60 s long.
- **Config field names are lowercased**: `pydantic_settings` maps `IG_USER_ID` env var → `ig_user_id` field (case-insensitive by default via `case_sensitive = False`).
- **`extra = 'ignore'` in `AppConfig.Config`**: Unknown env vars are silently dropped. This allows storing scheduler vars (`SCHEDULED_TASK_NAME`, `DAILY_RUN_TIME`) without validation errors.

---

## Running Locally

```powershell
# One-off post
python main.py

# Health check only
python main.py --health-check

# Debug output
$env:LOG_LEVEL = "DEBUG"; python main.py
```

## Dependencies (requirements.txt)

| Package | Purpose |
|---------|---------|
| `httpx` | Async HTTP client (Pexels, Graph API, health checks) |
| `pydantic` | Data models and validation |
| `pydantic-settings` | Environment variable loading into `AppConfig` |
| `python-dotenv` | `.env` file loading |
| `structlog` | Structured logging |
| `filelock` | Thread-safe state file locking |
