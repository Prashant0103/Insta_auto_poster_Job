# Instagram Auto Poster

Enhanced Instagram automation tool with robust error handling, retry mechanisms, and comprehensive monitoring.

## 🚀 Features

- **Smart Video Selection**: Fetches random unposted videos from Pexels with Instagram-friendly filtering
- **Robust Error Handling**: Custom exceptions, retry mechanisms with exponential backoff
- **Comprehensive Logging**: Structured logging with configurable levels and file output
- **Health Monitoring**: Built-in health checks for all system components
- **Thread-Safe State Management**: File locking prevents corruption from concurrent runs
- **Configuration Validation**: Pydantic-based config with comprehensive validation
- **Async Performance**: Modern async/await architecture with httpx for better performance
- **Resume Capability**: Automatically resumes failed posts from downloaded videos

## 🛠️ Setup

### 1. Install Dependencies

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Configure Environment

Copy the example configuration and customize:

```powershell
copy .env.example .env
```

Edit `.env` with your credentials:

```env
# Required: Pexels API key from https://www.pexels.com/api/
PEXELS_API_KEY=your_pexels_api_key_here

# Required: MCP server URL (must be running)
MCP_SERVER_URL=http://127.0.0.1:8000/mcp

# Required: Instagram credentials
INSTAGRAM_USERNAME=your_instagram_username
INSTAGRAM_PASSWORD=your_instagram_password

# Optional: Customize content and behavior
PEXELS_QUERY=nature,landscape,travel
CAPTION_THEME=inspirational
DEFAULT_HASHTAGS=#nature,#beautiful,#photography
```

### 3. Test Setup

Verify your installation:

```powershell
python test_setup.py
```

## 📋 Usage

### Basic Run

```powershell
python main.py
```

### Health Check Only

```powershell
python main.py --health-check
```

### With Custom Log Level

Set `LOG_LEVEL=DEBUG` in `.env` for detailed logging.

## 🔧 Configuration Options

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `PEXELS_API_KEY` | Pexels API key | - | ✅ |
| `PEXELS_QUERY` | Video search query | nature | ✅ |
| `PEXELS_PER_PAGE` | Videos per search | 20 | ❌ |
| `MCP_SERVER_URL` | MCP server endpoint | - | ✅ |
| `INSTAGRAM_USERNAME` | Instagram username | - | ✅ |
| `INSTAGRAM_PASSWORD` | Instagram password | - | ✅ |
| `DOWNLOAD_DIR` | Download directory | downloads | ❌ |
| `POSTED_STATE_FILE` | State tracking file | posted_videos.json | ❌ |
| `CAPTION_THEME` | Caption style | inspirational | ✅ |
| `DEFAULT_HASHTAGS` | Comma-separated hashtags | - | ✅ |
| `INSTAGRAM_MUSIC_QUERIES` | Music search terms | - | ❌ |
| `ALLOW_POST_WITHOUT_MUSIC` | Allow posts without music | true | ❌ |
| `MAX_VIDEO_DURATION_SECONDS` | Max video length | 60 | ❌ |
| `MIN_ASPECT_RATIO` | Min aspect ratio | 0.5 | ❌ |
| `MAX_ASPECT_RATIO` | Max aspect ratio | 2.0 | ❌ |
| `LOG_LEVEL` | Logging level | INFO | ❌ |
| `LOG_FILE` | Log file path | - | ❌ |

## 📊 Health Monitoring

The system includes comprehensive health checks:

- **MCP Server Connectivity**: Verifies MCP server is reachable
- **Pexels API Access**: Tests API authentication and connectivity
- **Recent Activity**: Monitors posting frequency and failure rates
- **System Resources**: Checks disk space and file permissions
- **Configuration Validation**: Ensures all settings are valid

Run health checks independently:

```powershell
python main.py --health-check
```

## 🔄 Error Handling & Recovery

### Automatic Retry
- **Network Failures**: Automatic retry with exponential backoff
- **API Rate Limits**: Intelligent retry with appropriate delays
- **Temporary Failures**: Distinguishes between retryable and permanent errors

### Resume Capability
- **Failed Posts**: Automatically resumes from downloaded videos
- **State Persistence**: Tracks all attempts and errors
- **Duplicate Prevention**: Ensures same video isn't posted twice

### Error Categories
- `ConfigurationError`: Invalid or missing configuration
- `PexelsAPIError`: Pexels API issues
- `MCPError`: MCP server communication problems
- `InstagramError`: Instagram-specific failures
- `MediaProcessingError`: Video download/processing issues

## 📅 Scheduling

### Windows Task Scheduler

Register a daily task:

```powershell
.\register_daily_task.ps1
```

Configure timing in `.env`:
```env
SCHEDULED_TASK_NAME=InstagramAutoPoster
DAILY_RUN_TIME=09:00
```

### Manual Scheduling

The app is designed for single-run execution. Use your preferred scheduler:
- Windows Task Scheduler
- Cron (Linux/macOS)
- GitHub Actions
- Cloud Functions

## 🏗️ Architecture

### Core Components

- **Configuration**: Pydantic-based validation with environment loading
- **Pexels Client**: Async HTTP client for video search and filtering
- **Video Downloader**: Streaming download with progress tracking
- **MCP Client**: Type-safe MCP communication with retry logic
- **State Store**: Thread-safe JSON-based state management
- **Health Checker**: Comprehensive system monitoring

### Data Flow

1. **Health Check**: Verify system components
2. **Resume Check**: Look for pending downloads
3. **Video Search**: Query Pexels for suitable content
4. **Content Filter**: Apply Instagram-friendly criteria
5. **Download**: Stream video to local storage
6. **State Update**: Record download completion
7. **Instagram Login**: Authenticate via MCP
8. **Post Creation**: Upload and publish content
9. **Success Recording**: Update state with completion

## 🔒 Security Considerations

- **Credential Storage**: Use environment variables, never commit credentials
- **MCP Communication**: Ensure MCP server runs on trusted network
- **File Permissions**: State files use appropriate access controls
- **Error Logging**: Sensitive data is not logged in error messages

## 🐛 Troubleshooting

### Common Issues

**Configuration Errors**
```
ConfigurationError: Missing required environment variable: PEXELS_API_KEY
```
→ Ensure all required variables are set in `.env`

**MCP Connection Failed**
```
MCPConnectionError: Failed to connect to MCP server
```
→ Verify MCP server is running and accessible

**No Suitable Videos**
```
PexelsNoResultsError: No Instagram-friendly unposted videos found
```
→ Adjust search query or video criteria in configuration

**File Lock Timeout**
```
StateStoreError: Failed to acquire file lock
```
→ Another instance may be running, or check file permissions

### Debug Mode

Enable detailed logging:
```env
LOG_LEVEL=DEBUG
LOG_FILE=debug.log
```

### Health Check

Diagnose system issues:
```powershell
python main.py --health-check
```

## 📈 Monitoring & Maintenance

### State File Management
- Location: `posted_videos.json` (configurable)
- Backup: Regularly backup state file
- Cleanup: Periodically review failed records

### Log Management
- Rotation: Implement log rotation for production
- Monitoring: Set up alerts for error patterns
- Analysis: Review logs for optimization opportunities

### Performance Optimization
- **Concurrent Limits**: Adjust httpx connection limits
- **Retry Settings**: Tune retry parameters for your network
- **Cache Strategy**: Consider caching Pexels results
- **Cleanup**: Remove old downloaded videos

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass: `python test_setup.py`
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## ⚠️ Disclaimer

This tool automates Instagram posting. Ensure compliance with:
- Instagram's Terms of Service
- Pexels License Requirements
- Applicable Privacy Laws
- Platform Rate Limits

Use responsibly and at your own risk.