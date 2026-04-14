#!/usr/bin/env python3
"""
Test script to verify the Instagram Auto Poster setup.
Run this after installing dependencies to check if everything works.
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

async def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    
    try:
        from instagram_auto_poster.config import load_config, AppConfig
        from instagram_auto_poster.exceptions import AutoPosterError
        from instagram_auto_poster.logging_config import setup_logging, get_logger
        from instagram_auto_poster.mcp_client import MCPAutomationClient
        from instagram_auto_poster.pexels_client import PexelsClient
        from instagram_auto_poster.downloader import VideoDownloader
        from instagram_auto_poster.state_store import PostedStateStore
        from instagram_auto_poster.health_check import HealthChecker
        from instagram_auto_poster.retry_utils import retry_with_backoff
        print("[OK] All imports successful")
        return True
    except ImportError as e:
        print(f"[FAIL] Import failed: {e}")
        return False

async def test_config_validation():
    """Test configuration validation."""
    print("Testing configuration validation...")
    
    try:
        from instagram_auto_poster.config import AppConfig
        from pydantic import ValidationError
        
        # Test invalid config
        try:
            config = AppConfig(
                pexels_api_key="short",  # Too short
                pexels_query="test",
                mcp_server_url="invalid-url",  # Invalid URL
                instagram_login_url="https://instagram.com",
                instagram_username="test",
                instagram_password="test",
                instagram_username_selector="input",
                instagram_password_selector="input",
                instagram_submit_selector="button",
                caption_theme="test",
                default_hashtags="test,hashtags"
            )
            print("[FAIL] Config validation should have failed")
            return False
        except ValidationError:
            print("[OK] Config validation working correctly")
            return True
            
    except Exception as e:
        print(f"[FAIL] Config validation test failed: {e}")
        return False

async def test_logging():
    """Test logging setup."""
    print("Testing logging...")
    
    try:
        from instagram_auto_poster.logging_config import setup_logging, get_logger
        
        setup_logging("INFO")
        logger = get_logger("test")
        logger.info("Test log message", test_param="test_value")
        print("[OK] Logging setup successful")
        return True
    except Exception as e:
        print(f"[FAIL] Logging test failed: {e}")
        return False

async def test_state_store():
    """Test state store functionality."""
    print("Testing state store...")
    
    try:
        from instagram_auto_poster.state_store import PostedStateStore, VideoRecord
        import tempfile
        
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "test_state.json"
            store = PostedStateStore(store_path)
            
            # Test record creation
            record = VideoRecord(
                video_id=12345,
                query="test",
                file_path="/test/path.mp4",
                source_url="https://example.com",
                downloaded_at="2024-01-01T00:00:00",
                posted_at="",
                caption="Test caption",
                music_query="test music",
                status="downloaded",
                attempts=0,
                last_error=""
            )
            
            store.upsert_record(record)
            used_ids = store.used_ids()
            
            if 12345 in used_ids:
                print("[OK] State store working correctly")
                return True
            else:
                print("[FAIL] State store not saving records correctly")
                return False
                
    except Exception as e:
        print(f"[FAIL] State store test failed: {e}")
        return False

async def test_health_check():
    """Test health check without external dependencies."""
    print("Testing health check...")
    
    try:
        from instagram_auto_poster.health_check import HealthStatus
        
        # Test HealthStatus creation
        status = HealthStatus(
            mcp_server_reachable=True,
            pexels_api_accessible=True,
            last_successful_post=None,
            pending_downloads=0,
            failed_attempts_last_24h=0,
            disk_space_mb=1000.0,
            config_valid=True,
            overall_healthy=True,
            issues=[]
        )
        
        if status.overall_healthy:
            print("[OK] Health check structures working correctly")
            return True
        else:
            print("[FAIL] Health check structure test failed")
            return False
            
    except Exception as e:
        print(f"[FAIL] Health check test failed: {e}")
        return False

async def main():
    """Run all tests."""
    print("Instagram Auto Poster Setup Test\n")
    
    tests = [
        ("Import Test", test_imports),
        ("Config Validation Test", test_config_validation),
        ("Logging Test", test_logging),
        ("State Store Test", test_state_store),
        ("Health Check Test", test_health_check),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n--- {test_name} ---")
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"[CRASH] {test_name} crashed: {e}")
            results.append((test_name, False))
    
    print(f"\n{'='*50}")
    print("Test Results Summary:")
    print(f"{'='*50}")
    
    passed = 0
    for test_name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{test_name:.<30} {status}")
        if result:
            passed += 1
    
    print(f"\nPassed: {passed}/{len(results)} tests")
    
    if passed == len(results):
        print("\nAll tests passed! Your setup is ready.")
        return 0
    else:
        print(f"\n{len(results) - passed} test(s) failed. Check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))