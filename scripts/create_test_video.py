"""
ClipForge AI — Local Test Video Generator.
Generates an offline, self-contained 10-second sample MP4 video with color bars,
moving timecode, and clean 440Hz test audio tone using FFmpeg.
Requires zero external network or YouTube access.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import imageio_ffmpeg

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clipforge.test_video")


def generate_local_test_video(output_path: str | Path = "storage/sample_test_video.mp4", duration: int = 10) -> Path:
    """
    Creates a local MP4 test video using FFmpeg testsrc and sine wave audio.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe() or "ffmpeg"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration}:size=1280x720:rate=30",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        str(out),
    ]

    logger.info(f"Generating local test video -> {out}")
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if out.exists() and out.stat().st_size > 0:
        logger.info(f"Test video created successfully: {out} ({out.stat().st_size} bytes)")
        return out
    raise RuntimeError(f"Failed to generate test video at {out}")


if __name__ == "__main__":
    path = generate_local_test_video()
    print(f"Generated test video at: {path.absolute()}")
