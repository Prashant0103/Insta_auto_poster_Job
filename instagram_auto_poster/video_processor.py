"""Video processing using ffmpeg — merges a video file with a background music track."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .exceptions import MediaProcessingError
from .logging_config import get_logger

logger = get_logger(__name__)


def _probe_duration(video_path: Path) -> float:
    """Return video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except FileNotFoundError as e:
        raise MediaProcessingError(
            "ffprobe not found. Install ffmpeg: https://ffmpeg.org/download.html"
        ) from e
    except (subprocess.CalledProcessError, ValueError) as e:
        raise MediaProcessingError(f"Failed to read video duration: {e}") from e


def merge_video_with_music(
    video_path: Path,
    music_path: Path,
    output_path: Path,
    music_volume: float = 0.8,
    fade_out_seconds: float = 2.0,
) -> Path:
    """
    Merge a video file with a background music track using ffmpeg.

    The music is:
    - Trimmed / looped to match the video duration (via -shortest)
    - Set to the specified volume
    - Faded out over the last `fade_out_seconds`

    Any original audio in the video is replaced by the music.

    Args:
        video_path:        Path to the source .mp4 video.
        music_path:        Path to the music .mp3 file.
        output_path:       Where to write the merged .mp4.
        music_volume:      Volume multiplier for the music (0.0–1.0).
        fade_out_seconds:  Duration of the fade-out at the end.

    Returns:
        Path to the merged output file.

    Raises:
        MediaProcessingError: If ffmpeg is not found or returns an error.
    """
    logger.info(
        "Merging video with music",
        video=str(video_path),
        music=str(music_path),
        volume=music_volume,
    )

    duration = _probe_duration(video_path)
    fade_start = max(0.0, duration - fade_out_seconds)

    # Build audio filter: set volume, then fade out near the end
    audio_filter = f"volume={music_volume},afade=t=out:st={fade_start:.3f}:d={fade_out_seconds}"

    cmd = [
        "ffmpeg",
        "-y",                          # overwrite output without asking
        "-i", str(video_path),         # input 0: video
        "-i", str(music_path),         # input 1: music
        "-map", "0:v:0",               # take video stream from input 0
        "-map", "1:a:0",               # take audio stream from input 1 (music)
        "-af", audio_filter,
        "-c:v", "copy",                # no video re-encode — keeps quality & speed
        "-shortest",                   # stop at the shorter of the two streams
        str(output_path),
    ]

    logger.debug("Running ffmpeg", cmd=" ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise MediaProcessingError(
            "ffmpeg not found. Install ffmpeg: https://ffmpeg.org/download.html"
        ) from e

    if result.returncode != 0:
        logger.error("ffmpeg failed", stderr=result.stderr[-500:])
        raise MediaProcessingError(f"ffmpeg exited with code {result.returncode}: {result.stderr[-300:]}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise MediaProcessingError("ffmpeg produced an empty output file")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(
        "Video merged with music successfully",
        output=str(output_path),
        size_mb=f"{size_mb:.2f}",
        video_duration_s=f"{duration:.1f}",
    )
    return output_path
