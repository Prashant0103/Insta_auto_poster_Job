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
        from instagram_auto_poster.instagram_api_client import InstagramAPIClient
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

        # Test invalid config — short pexels key + non-numeric ig_user_id should fail
        try:
            config = AppConfig(
                pexels_api_key="short",       # Too short — should fail validation
                pexels_query="test",
                ig_user_id="not-a-number",    # Non-numeric — should fail validation
                ig_access_token="a" * 15,
                caption_theme="test",
                default_hashtags="test,hashtags",
            )
            print("[FAIL] Config validation should have failed")
            return False
        except (ValidationError, Exception):
            pass  # Expected

        # Test valid config object (not loading from .env — just direct construction)
        try:
            config = AppConfig(
                pexels_api_key="a" * 12,
                pexels_query="nature",
                ig_user_id="17841480739282588",
                ig_access_token="a" * 20,
                caption_theme="inspirational",
                default_hashtags="#nature,#travel",
            )
            print("[OK] Config validation working correctly")
            return True
        except Exception as e:
            print(f"[FAIL] Valid config rejected: {e}")
            return False

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

            # Create a real dummy file so get_pending_download file-existence check passes
            dummy_video = Path(temp_dir) / "test_video.mp4"
            dummy_video.write_bytes(b"dummy")

            record = VideoRecord(
                video_id=12345,
                query="test",
                file_path=str(dummy_video),   # real path on disk
                source_url="https://example.com/video.mp4",
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

            if 12345 not in used_ids:
                print("[FAIL] State store not saving records correctly")
                return False

            # get_pending_download checks file existence — should now succeed
            pending = store.get_pending_download()
            if pending and pending.video_id == 12345:
                print("[OK] State store working correctly")
                return True
            else:
                print("[FAIL] get_pending_download did not return expected record")
                return False

    except Exception as e:
        print(f"[FAIL] State store test failed: {e}")
        return False


async def test_health_check():
    """Test health check structures (no external calls)."""
    print("Testing health check structures...")

    try:
        from instagram_auto_poster.health_check import HealthStatus

        # Test HealthStatus creation with the new field name
        status = HealthStatus(
            instagram_api_reachable=True,
            pexels_api_accessible=True,
            last_successful_post=None,
            pending_downloads=0,
            failed_attempts_last_24h=0,
            disk_space_mb=1000.0,
            config_valid=True,
            overall_healthy=True,
            issues=[]
        )

        if status.overall_healthy and status.instagram_api_reachable:
            print("[OK] Health check structures working correctly")
            return True
        else:
            print("[FAIL] Health check structure test failed")
            return False

    except Exception as e:
        print(f"[FAIL] Health check test failed: {e}")
        return False


async def test_instagram_api_client():
    """Test InstagramAPIClient can be instantiated."""
    print("Testing InstagramAPIClient instantiation...")

    try:
        from instagram_auto_poster.instagram_api_client import InstagramAPIClient

        client = InstagramAPIClient(
            ig_user_id="17841480739282588",
            access_token="test_token_placeholder",
        )

        if client.ig_user_id == "17841480739282588":
            print("[OK] InstagramAPIClient instantiation successful")
            return True
        else:
            print("[FAIL] InstagramAPIClient property mismatch")
            return False

    except Exception as e:
        print(f"[FAIL] InstagramAPIClient test failed: {e}")
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
        ("Instagram API Client Test", test_instagram_api_client),
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
        print(f"{test_name:.<35} {status}")
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