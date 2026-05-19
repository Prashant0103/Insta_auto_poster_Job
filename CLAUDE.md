# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

A Python async CLI tool that runs on a daily cron schedule (Railway/GitHub Actions) and:

1. Pulls persistent state from a GitHub Gist (for stateless deployments)
2. Searches YouTube (or Pexels) for suitable short videos via their APIs
3. Downloads the chosen video locally via yt-dlp
4. Uploads it to a public HTTPS host (Google Drive → transfer.sh → 0x0.st → catbox.moe → filebin.net)
5. Publishes it as an Instagram Reel via the Instagram Graph API v19.0
6. Pushes updated state back to the GitHub Gist

Entry point: `main.py` → `instagram_auto_poster/runner.py:main()`

---

## Running Locally

```powershell
# First-time setup
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then fill in credentials

# One-off post
python main.py

# Health check only (validates API tokens, disk, state — no post)
python main.py --health-check

# Debug output
$env:LOG_LEVEL = "DEBUG"; python main.py

# Smoke tests — 6 checks covering imports, config validation, logging,
# state store, health check, and API client instantiation (no external calls)
python test_setup.py
```

---

## CI/CD Schedule

GitHub Actions workflow (`.github/workflows/post.yml`):
- Runs daily at **03:30 UTC (09:00 IST)** + `workflow_dispatch` for manual trigger
- Requires **Node.js 20** (yt-dlp n-challenge solving) alongside Python 3.11
- Workflow steps write credential files directly (`/tmp/yt_cookies.txt`, `/tmp/gdrive_token.json`) before running `python main.py` — runner's `_write_credentials_from_env()` skips writing if those files already exist

---

## Architecture: Request Flow

```
runner.run_once()
  │
  ├─ _write_credentials_from_env()      # decode GOOGLE_DRIVE_TOKEN_B64 / YOUTUBE_COOKIES_B64
  ├─ pull_state_from_gist()             # gist_sync.py — fetch posted_videos.json from Gist
  ├─ store.get_pending_download()       # resume interrupted run if file already exists
  ├─ store.get_failed_records()         # retry up to 3× for failed posts
  │
  └─ for each query in YOUTUBE_QUERY:
       find_and_download_video()         # video_sources.py
         ├─ YouTubeVideoSource.search()  # YouTube Data API v3
         ├─ filter candidates           # duration, aspect ratio, like count, not used before
         └─ YouTubeVideoSource.download() → YouTubeClient._download_sync()
              ├─ yt-dlp with android_vr/android/ios clients
              └─ on bot detection → _download_via_invidious() fallback
       │
       upload_to_transfer_sh()           # transfer_sh_uploader.py
         ├─ GoogleDriveUploader (if GOOGLE_DRIVE_FOLDER_ID set)
         └─ fallback chain: transfer.sh → 0x0.st → catbox.moe → filebin.net
       │
       InstagramAPIClient.create_and_publish()  # instagram_api_client.py
         ├─ POST /media (REELS, video_url=public URL)
         ├─ poll status until FINISHED (30 × 10s = 5 min max)
         └─ POST /media_publish
       │
       store.upsert_record(status='posted')
       downloaded.file_path.unlink()     # delete local temp file
       push_state_to_gist()             # gist_sync.py
```

---

## Module Map

| Module | Responsibility |
|--------|---------------|
| `config.py` | `AppConfig` (pydantic-settings) — all env var loading |
| `runner.py` | Pipeline orchestrator, credential injection, retry/resume logic |
| `video_sources.py` | `find_and_download_video()` — source selection, filtering, download retry |
| `youtube_client.py` | YouTube Data API search + yt-dlp download + Invidious fallback |
| `pexels_client.py` | Pexels REST API search |
| `downloader.py` | Generic async httpx downloader for Pexels videos |
| `instagram_api_client.py` | Graph API: media container → poll → publish |
| `transfer_sh_uploader.py` | Upload to public host; Google Drive primary, 4 free services as fallback |
| `google_drive_client.py` | Google Drive upload via OAuth user credentials (token.json) |
| `gist_sync.py` | Pull/push `posted_videos.json` to a GitHub Gist for stateless deployments |
| `state_store.py` | `PostedStateStore` — filelock-protected JSON state |
| `video_id_store.py` | `VideoIdStore` — SQLite-backed global dedup (persisted at `/data/videos.db` on Railway) |
| `music_client.py` | `MusicClient` — Jamendo API search + download of royalty-free CC-licensed tracks |
| `video_processor.py` | `merge_video_with_music()` — ffmpeg: replace video audio with background music + fade-out |
| `caption_builder.py` | Caption and hashtag generation |
| `health_check.py` | `HealthChecker.check_health()` — pre-run system checks |
| `retry_utils.py` | `retry_with_backoff()` — exponential backoff helper |
| `logging_config.py` | structlog setup |
| `exceptions.py` | Custom exception hierarchy |

---

## Key Environment Variables

All loaded via `AppConfig(BaseSettings)` in `config.py`. Never read `os.environ` directly in other modules.

| Variable | Purpose |
|----------|---------|
| `PEXELS_YN` / `YOUTUBE_YN` | `Y`/`N` flags to enable each source |
| `PEXELS_API_KEY` | Pexels REST API key (required if `PEXELS_YN=Y`) |
| `PEXELS_QUERY` | Pexels search query |
| `PEXELS_PER_PAGE` | Results per page for Pexels (1–80, default 20) |
| `YOUTUBE_API_KEY` | YouTube Data API v3 key (required if `YOUTUBE_YN=Y`) |
| `YOUTUBE_QUERY` | Single query string or bracket list `[query1,query2]` — one post per query per run |
| `YOUTUBE_MAX_RESULTS` | Number of YouTube results to fetch per search (1–50, default 8) |
| `YOUTUBE_MAX_DURATION_SECONDS` | Filter out videos longer than this |
| `YOUTUBE_MIN_LIKE_COUNT` | Filter out low-engagement videos |
| `YOUTUBE_FORMAT` | yt-dlp quality: `0`=best, `720`, `1080`, etc. |
| `YOUTUBE_COOKIES_FILE` | Path to Netscape cookies.txt for yt-dlp bot bypass |
| `YOUTUBE_COOKIES_B64` | Base64-encoded cookies.txt — written to `YOUTUBE_COOKIES_FILE` at startup (Railway/CI) |
| `CHECK_PUBLISHED_DATE` | Only include YouTube videos published on or after this date (`DD-MM-YYYY`) |
| `VIDEO_ID` | YouTube video ID to post directly — bypasses search entirely |
| `IG_USER_ID` | Instagram Business/Creator account ID (numeric) |
| `IG_ACCESS_TOKEN` | Long-lived Instagram Graph API token |
| `DOWNLOAD_DIR` | Local directory for temp video files |
| `POSTED_STATE_FILE` | Path to `posted_videos.json` |
| `VIDEO_ID_DB` | SQLite DB path for global video ID dedup (default `/data/videos.db` — use Railway Volume) |
| `CAPTION_THEME` | Theme string passed to `build_caption()` |
| `DEFAULT_HASHTAGS` | Comma-separated hashtags appended to every caption |
| `MAX_VIDEO_DURATION_SECONDS` | Instagram-side filter (separate from YouTube filter) |
| `MIN_ASPECT_RATIO` / `MAX_ASPECT_RATIO` | Aspect ratio filter for Instagram compatibility |
| `GH_PAT` | GitHub PAT with `gist` scope for state sync |
| `STATE_GIST_ID` | GitHub Gist ID containing `posted_videos.json` |
| `GOOGLE_DRIVE_FOLDER_ID` | Drive folder for video hosting (primary uploader when set) |
| `GOOGLE_DRIVE_TOKEN_FILE` | Path to OAuth `token.json` (default: `token.json`) |
| `GOOGLE_DRIVE_TOKEN_B64` | Base64-encoded `token.json` — written at startup (Railway/CI) |
| `LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `LOG_FILE` | Optional file path for log output |

---

## Video Source Selection

`AppConfig.video_source_order` returns the enabled sources in order based on `PEXELS_YN`/`YOUTUBE_YN` flags. `video_sources.py:find_and_download_video()` tries each source in order and falls back to the next on failure.

`YOUTUBE_QUERY` supports bracket list format: `[taarak mehta funny shorts,bhabhi ji ghar par hai funny shorts]` — runner posts one video per query per run.

When `VIDEO_ID` is set, `runner._post_direct_video_id()` is called instead — it downloads that specific YouTube video ID without searching and posts it directly.

---

## Instagram Graph API Flow

```
POST /{ig_user_id}/media          → creation_id
GET  /{creation_id}?fields=status_code   (poll every 10s, max 30 polls)
POST /{ig_user_id}/media_publish  → media_id
```

- Base URL: `https://graph.facebook.com/v19.0`
- `video_url` must be a publicly accessible HTTPS URL — this is why a video hosting step is needed
- All three steps retry 3× with 5 s base delay via `retry_with_backoff`

---

## State Store

Two complementary dedup mechanisms:

- **`PostedStateStore`** (`state_store.py`) — filelock-protected JSON; tracks per-record status with retry logic. Synced to/from GitHub Gist for stateless deployments.
- **`VideoIdStore`** (`video_id_store.py`) — SQLite (`VIDEO_ID_DB`); stores only `(video_id, posted_at)`. On Railway, mount a Volume at `/data` so this persists across deploys.

`VideoRecord` fields: `video_id`, `query`, `file_path`, `source_url`, `download_url`, `downloaded_at`, `posted_at`, `caption`, `music_query`, `status`, `attempts`, `last_error`

Status lifecycle: `downloaded` → `posted` (success) or `failed` (error)

- `get_pending_download()` — resumes a run that downloaded but didn't post
- `get_failed_records(max_attempts=3)` — eligible for retry; records without `download_url` are deleted (ID freed for reuse)
- `upsert_record()` — insert or replace by `video_id`; uses filelock with stale-lock cleanup

---

## Credential Injection at Startup

`runner._write_credentials_from_env()` decodes base64 env vars and writes credential files before the pipeline starts. This is how Railway/CI deployments inject secrets that yt-dlp and Google Drive SDK expect as files:

- `GOOGLE_DRIVE_TOKEN_B64` → `GOOGLE_DRIVE_TOKEN_FILE` (default `token.json`)
- `YOUTUBE_COOKIES_B64` → `YOUTUBE_COOKIES_FILE` (default `/tmp/yt_cookies.txt`)

It skips writing if the file already exists (so a pre-written file in the workflow takes precedence).

---

## Exception Hierarchy

```
AutoPosterError
├── ConfigurationError
├── InstagramAPIError
├── InstagramError
│   └── InstagramAuthError      ← 401 / token error codes 190, 200, 102
├── MediaProcessingError        ← upload failure, empty file, transcoding ERROR
├── PexelsError
│   ├── PexelsAPIError
│   └── PexelsNoResultsError
├── YouTubeError
│   ├── YouTubeAPIError
│   └── YouTubeNoResultsError
├── StateStoreError
└── RetryExhaustedError
```

---

## Adding a New Feature — Checklist

1. **New config field**: Add to `AppConfig` in `config.py` with `Field(...)`. Add to `.env.example`.
2. **New exception type**: Extend the hierarchy in `exceptions.py`.
3. **New API call**: Follow the `_raise_for_api_error` + `retry_with_backoff` pattern in `instagram_api_client.py`.
4. **New state field**: Update `VideoRecord` in `state_store.py`; add a default in the `normalized` dict in `get_pending_download()` and `get_failed_records()` for backwards compatibility.
5. **New health check**: Add a private `_check_*` method in `HealthChecker` and wire into `check_health()`.
6. **New credential file**: Add a decode block in `_write_credentials_from_env()` in `runner.py`.
7. **Logging in a new module**: `from .logging_config import get_logger; logger = get_logger(__name__)` — use `logger.info("msg", key=value)` key-value style throughout.

---

## Common Pitfalls

- **YouTube bot detection**: Cloud IPs (GitHub Actions, Railway, Render) are blocked by YouTube. Fix: export cookies from a logged-in browser, base64-encode, set `YOUTUBE_COOKIES_B64`. Cookies expire after ~6–12 months or if you log out.
- **Invidious fallback**: All public Invidious instances are frequently down. It's a last resort, not a reliable primary fallback.
- **`video_url` must be public HTTPS**: The Graph API downloads the video server-side. Local paths don't work — always upload to a public host first.
- **Google Drive token**: Must be OAuth user credentials (`token.json` with `refresh_token`), NOT a service account key. Generate via the `google_driveapi_setup` companion project.
- **`GH_PAT` not `GITHUB_TOKEN`**: GitHub Actions reserves `GITHUB_TOKEN` and overrides it with a repo-scoped token that cannot write to Gists.
- **Container status polling**: Instagram transcoding takes 1–5 minutes. Don't reduce `max_polls` below 18 (3 min) for 60 s videos.
- **`extra = 'ignore'` in `AppConfig.Config`**: Unknown env vars are silently dropped — safe to have scheduler-only vars in the environment.
- **Pydantic env var casing**: `pydantic_settings` maps env vars case-insensitively — `IG_USER_ID` in the environment becomes field `ig_user_id` in `AppConfig`. Always access config via field name, not the env var name string.
- **SQLite dedup on Railway**: `VideoIdStore` defaults to `/data/videos.db`. Without a Railway Volume mounted at `/data`, the SQLite file is lost on every redeploy and videos can repeat.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `httpx` | Async HTTP client (all API calls) |
| `yt-dlp` | YouTube video download |
| `pydantic` / `pydantic-settings` | Config models and env var loading |
| `python-dotenv` | `.env` file loading |
| `structlog` | Structured key-value logging |
| `filelock` | Thread-safe state file locking |
| `google-api-python-client` | Google Drive upload |
| `google-auth-oauthlib` / `google-auth-httplib2` | OAuth credential refresh |
| `imageio-ffmpeg` | Bundled ffmpeg for yt-dlp merging |
