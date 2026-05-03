# Instagram Auto Poster

Automated Instagram Reels poster that sources videos from Pexels and publishes them via the **Instagram Graph API** — no browser automation required.

## 🚀 Features

- **Smart Video Selection**: Fetches random unposted videos from Pexels with Instagram-friendly filtering (duration, aspect ratio)
- **Graph API Publishing**: Two-step container-create + publish flow via the official Instagram Graph API (v19.0)
- **Robust Error Handling**: Custom exceptions and retry mechanisms with exponential backoff
- **Container Status Polling**: Waits for Instagram's server-side transcoding to finish before publishing
- **Comprehensive Logging**: Structured logging with configurable levels and optional file output
- **Health Monitoring**: Built-in health checks for the Graph API token, Pexels API, disk space, and state
- **Thread-Safe State Management**: File locking prevents corruption from concurrent runs
- **Configuration Validation**: Pydantic-based config with comprehensive field validation
- **Async Performance**: Modern async/await architecture with `httpx` for fast, non-blocking I/O
- **Resume Capability**: Automatically retries failed posts from previously downloaded videos

---

## 🛠️ Setup

### 1. Prerequisites

- Python 3.10+
- An **Instagram Business or Creator** account connected to a Facebook Page
- A **Facebook Developer App** with `instagram_basic`, `instagram_content_publish`, and `pages_read_engagement` permissions
- A [Pexels API key](https://www.pexels.com/api/)

### 2. Install Dependencies

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Configure Environment

```powershell
copy .env.example .env
```

Edit `.env` with your credentials:

```env
# Required: Pexels API key — https://www.pexels.com/api/
PEXELS_API_KEY=your_pexels_api_key_here

# Required: Instagram Graph API credentials
# IG_USER_ID  → numeric Instagram account ID (found in Graph API Explorer)
# IG_ACCESS_TOKEN → long-lived Page/System-User token
IG_USER_ID=17841480739282588
IG_ACCESS_TOKEN=your_long_lived_access_token_here

# Optional: Customize content
PEXELS_QUERY=nature,landscape,travel
CAPTION_THEME=inspirational
DEFAULT_HASHTAGS=#nature,#beautiful,#photography
```

> **Getting a long-lived access token**
> 1. Create a Facebook App at [developers.facebook.com](https://developers.facebook.com)
> 2. Add the **Instagram Graph API** product
> 3. Generate a short-lived token in the Graph API Explorer
> 4. Exchange it for a long-lived token (60-day expiry) via:
>    ```
>    GET https://graph.facebook.com/v19.0/oauth/access_token
>      ?grant_type=fb_exchange_token
>      &client_id={app-id}
>      &client_secret={app-secret}
>      &fb_exchange_token={short-lived-token}
>    ```
> 5. For production, generate a **System User Token** (never expires) in Facebook Business Manager.

### 4. Verify Setup

```powershell
python test_setup.py
```

---

## 📋 Usage

### Basic Run

```powershell
python main.py
```

### Health Check Only

```powershell
python main.py --health-check
```

### Debug Logging

Set `LOG_LEVEL=DEBUG` in `.env` (optionally with `LOG_FILE=debug.log`) for verbose output.

---

## 🔧 Configuration Reference

| Variable | Description | Default | Required |
|----------|-------------|---------|:--------:|
| `PEXELS_API_KEY` | Pexels API key | — | ✅ |
| `PEXELS_QUERY` | Video search query | — | ✅ |
| `PEXELS_PER_PAGE` | Results per Pexels search | `20` | ❌ |
| `IG_USER_ID` | Numeric Instagram account ID | — | ✅ |
| `IG_ACCESS_TOKEN` | Instagram Graph API access token | — | ✅ |
| `DOWNLOAD_DIR` | Local video download directory | `downloads` | ❌ |
| `POSTED_STATE_FILE` | State-tracking JSON file | `posted_videos.json` | ❌ |
| `CAPTION_THEME` | Theme used for caption generation | `inspirational` | ✅ |
| `DEFAULT_HASHTAGS` | Comma-separated hashtags | — | ✅ |
| `INSTAGRAM_MUSIC_QUERIES` | Comma-separated music search terms | — | ❌ |
| `ALLOW_POST_WITHOUT_MUSIC` | Continue if no music found | `true` | ❌ |
| `MAX_VIDEO_DURATION_SECONDS` | Maximum accepted video length | `60` | ❌ |
| `MIN_ASPECT_RATIO` | Minimum accepted aspect ratio | `0.5` | ❌ |
| `MAX_ASPECT_RATIO` | Maximum accepted aspect ratio | `2.0` | ❌ |
| `LOG_LEVEL` | Logging level (`DEBUG`/`INFO`/…) | `INFO` | ❌ |
| `LOG_FILE` | Optional log file path | — | ❌ |
| `SCHEDULED_TASK_NAME` | Windows Task Scheduler task name | `InstagramAutoPoster` | ❌ |
| `DAILY_RUN_TIME` | Daily run time for scheduler | `09:00` | ❌ |

---

## 📊 Health Monitoring

Run the built-in health check at any time:

```powershell
python main.py --health-check
```

Checks performed:

| Check | What it verifies |
|-------|-----------------|
| **Instagram Graph API** | Hits `GET /v19.0/me` to confirm the access token is valid |
| **Pexels API** | Sends a test search request to confirm connectivity |
| **Recent Activity** | Warns if no successful post in the last 48 h |
| **Pending Downloads** | Flags if > 5 downloads are stuck un-posted |
| **Failure Rate** | Warns if > 10 failures in the last 24 h |
| **Disk Space** | Checks write access to the download directory |
| **Configuration** | Validates all required environment variables |

---

## 🔄 Posting Flow

```
Health Check
    │
    ▼
Resume Check ──(pending download exists)──▶ Skip to Publish
    │
    ▼ (no pending)
Pexels Search
    │
    ▼
Filter (duration, aspect ratio, dedup)
    │
    ▼
Download video → save state (status: downloaded)
    │
    ▼
Graph API: POST /{ig_user_id}/media        ← create container
    │                                         (video_url = Pexels CDN URL)
    ▼
Poll container status until FINISHED
    │
    ▼
Graph API: POST /{ig_user_id}/media_publish ← publish
    │
    ▼
Save state (status: posted) ✅
```

---

## 🔄 Error Handling & Recovery

### Automatic Retry
- All Graph API calls retry up to 3× with exponential backoff
- Container polling waits up to 5 minutes for Instagram transcoding

### Resume Capability
- If a run fails after download but before publishing, the next run picks up the downloaded video and retries the post
- State is persisted in `posted_videos.json` between runs

### Error Categories

| Exception | Cause |
|-----------|-------|
| `ConfigurationError` | Missing or invalid `.env` values |
| `PexelsAPIError` | Pexels API request failure |
| `PexelsNoResultsError` | No suitable videos returned |
| `InstagramError` | Instagram Graph API error |
| `InstagramAuthError` | Invalid or expired access token |
| `MediaProcessingError` | Container transcoding failed or timed out |
| `StateStoreError` | State file lock / read / write failure |

---

## 📅 Scheduling

### Windows Task Scheduler (recommended)

Register a daily task automatically:

```powershell
.\register_daily_task.ps1
```

Configure timing in `.env`:
```env
SCHEDULED_TASK_NAME=InstagramAutoPoster
DAILY_RUN_TIME=09:00
```

### Other schedulers

The app is stateless between runs — any scheduler that can invoke `python main.py` works:

- **Cron** (Linux/macOS/WSL)
- **GitHub Actions** (scheduled workflow)
- **Cloud Scheduler** (GCP / AWS EventBridge)
- **Windows Task Scheduler** (via `run_daily.ps1`)

---

## 🏗️ Architecture

### Module Map

```
instagram_auto_poster/
├── config.py               # Pydantic settings, env loading & validation
├── runner.py               # Orchestrates the full posting pipeline
├── instagram_api_client.py # Instagram Graph API: create container + publish
├── pexels_client.py        # Pexels video search & filtering
├── downloader.py           # Async streaming video downloader
├── caption_builder.py      # Caption and hashtag generation
├── state_store.py          # Thread-safe JSON state persistence
├── health_check.py         # System health checks
├── retry_utils.py          # Exponential-backoff retry decorator
├── logging_config.py       # Structured logging setup (structlog)
└── exceptions.py           # Custom exception hierarchy
```

---

## 🔒 Security

- **Never commit `.env`** — it is in `.gitignore`
- Keep `IG_ACCESS_TOKEN` secret; rotate it via Facebook Business Manager if compromised
- Use a **System User Token** in production to avoid 60-day expiry
- State files contain video metadata only — no credentials

---

## 🐛 Troubleshooting

**Missing required config**
```
ConfigurationError: Failed to load configuration: ...
```
→ Copy `.env.example` → `.env` and fill in all required fields.

**Invalid or expired access token**
```
InstagramAuthError: Instagram API authentication error [create media container]: ...
```
→ Refresh your token in the Graph API Explorer or generate a new System User Token.

**No suitable videos found**
```
PexelsNoResultsError: No Instagram-friendly unposted videos found
```
→ Broaden `PEXELS_QUERY` or increase `PEXELS_PER_PAGE`.

**Container stuck / transcoding timeout**
```
MediaProcessingError: Container did not finish processing after 300s
```
→ The video may be too long or an unsupported codec. Try a shorter clip or re-run.

**State file locked**
```
StateStoreError: Failed to acquire file lock
```
→ Another instance may be running. Kill it, or delete the `.lock` file.

**Debug everything**
```env
LOG_LEVEL=DEBUG
LOG_FILE=debug.log
```

---

## 📈 Maintenance

- **Access Token Renewal**: Long-lived tokens expire in 60 days. Renew before expiry or switch to a non-expiring System User Token.
- **State File Backup**: Back up `posted_videos.json` periodically.
- **Video Cleanup**: Delete old files from `downloads/` to reclaim disk space.
- **Log Rotation**: For long-running deployments, configure log rotation or use `LOG_FILE` with an external log manager.

---

## ⚠️ Disclaimer

This tool automates Instagram content publishing via the official Instagram Graph API. Ensure compliance with:

- [Instagram's Terms of Service](https://help.instagram.com/581066165581870)
- [Pexels License](https://www.pexels.com/license/)
- [Facebook Platform Policy](https://developers.facebook.com/policy/)
- Applicable privacy laws in your jurisdiction

Use responsibly and at your own risk.