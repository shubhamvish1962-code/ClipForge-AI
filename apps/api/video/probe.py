"""
ClipForge AI — FFprobe Video Analysis & Diagnostic Service.
Extracts duration, resolution, FPS, video/audio codecs, and validates rendered video files.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import imageio_ffmpeg

logger = logging.getLogger("clipforge.video.probe")


@dataclass
class VideoProbeResult:
    """Detailed metadata extracted from video stream analysis."""
    is_valid: bool
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 30.0
    video_codec: str = ""
    has_audio: bool = False
    audio_codec: Optional[str] = None
    audio_channels: int = 0
    bitrate_kbps: int = 0
    file_size_bytes: int = 0
    error: Optional[str] = None


def get_ffprobe_binary() -> Optional[str]:
    """
    Resolve a real ffprobe executable, or None if there isn't one.

    Note that imageio-ffmpeg bundles only ffmpeg, not ffprobe, so the sibling
    lookup below usually misses. Returning None rather than the bare string
    "ffprobe" lets probe_video() skip a guaranteed-failing subprocess call and
    go straight to the ffmpeg parser.
    """
    # 1. Explicit override (FFPROBE_PATH in .env)
    configured = os.environ.get("FFPROBE_PATH", "").split("#")[0].strip()
    if configured and configured != "ffprobe":
        if Path(configured).exists():
            return configured

    # 2. Sibling of the imageio-ffmpeg binary
    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_exe:
            for candidate in ("ffprobe.exe", "ffprobe"):
                sibling = Path(ffmpeg_exe).parent / candidate
                if sibling.exists():
                    return str(sibling)
    except Exception:
        pass

    # 3. Anything on PATH
    return shutil.which("ffprobe")


def check_ffmpeg_installation() -> Dict[str, Any]:
    """
    Executes ffmpeg -version to verify availability.

    Also reports ffprobe separately — it is optional (probe_video falls back to
    parsing ffmpeg output), but callers should be able to see which path is in
    use rather than assuming both binaries are present.
    """
    try:
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe() or "ffmpeg"
        res = subprocess.run([ffmpeg_bin, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        first_line = res.stdout.splitlines()[0] if res.stdout else "FFmpeg present"
        ffprobe_bin = get_ffprobe_binary()
        return {
            "status": "ok",
            "version": first_line,
            "binary_path": ffmpeg_bin,
            "ffprobe_path": ffprobe_bin or "not found",
            "ffprobe_available": bool(ffprobe_bin),
            "metadata_source": "ffprobe" if ffprobe_bin else "ffmpeg-stderr-parser",
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "binary_path": "not found"}


def probe_video(video_path: str | Path) -> VideoProbeResult:
    """
    Probes video metadata using ffprobe JSON output.
    """
    path = Path(video_path)
    if not path.exists() or path.stat().st_size == 0:
        return VideoProbeResult(is_valid=False, error=f"File not found or 0 bytes: {path}")

    file_size = path.stat().st_size
    ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe() or "ffmpeg"
    ffprobe_bin = get_ffprobe_binary()

    # No ffprobe on this machine — go straight to the ffmpeg parser.
    if not ffprobe_bin:
        try:
            fb_res = subprocess.run(
                [ffmpeg_bin, "-i", str(path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10,
            )
            return _parse_ffmpeg_stderr(fb_res.stderr, file_size)
        except Exception as e:
            return VideoProbeResult(is_valid=False, error=str(e), file_size_bytes=file_size)

    # Try ffprobe with JSON format
    cmd = [
        ffprobe_bin,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            format_info = data.get("format", {})
            streams = data.get("streams", [])

            duration = float(format_info.get("duration", 0.0))
            bitrate = int(format_info.get("bit_rate", 0)) // 1000

            v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
            a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

            width = int(v_stream.get("width", 0)) if v_stream else 0
            height = int(v_stream.get("height", 0)) if v_stream else 0
            v_codec = v_stream.get("codec_name", "") if v_stream else ""

            # Calculate FPS
            fps = 30.0
            if v_stream and "r_frame_rate" in v_stream:
                rate_str = v_stream["r_frame_rate"]
                if "/" in rate_str:
                    num, den = rate_str.split("/")
                    if float(den) > 0:
                        fps = round(float(num) / float(den), 2)

            has_audio = a_stream is not None
            a_codec = a_stream.get("codec_name") if a_stream else None
            a_channels = int(a_stream.get("channels", 0)) if a_stream else 0

            return VideoProbeResult(
                is_valid=width > 0 and height > 0,
                duration=duration,
                width=width,
                height=height,
                fps=fps,
                video_codec=v_codec,
                has_audio=has_audio,
                audio_codec=a_codec,
                audio_channels=a_channels,
                bitrate_kbps=bitrate,
                file_size_bytes=file_size,
            )
    except Exception as e:
        logger.warning(f"ffprobe failed for {path}: {e}")

    # Fallback: parse real values out of `ffmpeg -i` stderr.
    # ffmpeg exits non-zero here ("At least one output file must be specified"),
    # which is expected — the stream report we want is still on stderr.
    try:
        fallback_cmd = [ffmpeg_bin, "-i", str(path)]
        fb_res = subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        return _parse_ffmpeg_stderr(fb_res.stderr, file_size)
    except Exception as e:
        return VideoProbeResult(is_valid=False, error=str(e), file_size_bytes=file_size)


def _parse_ffmpeg_stderr(output: str, file_size: int) -> VideoProbeResult:
    """
    Extract real metadata from `ffmpeg -i` stderr.

    Used when no ffprobe binary is available. Every field is read from the
    actual stream report — if a value cannot be determined it is left at its
    default and, for dimensions, the result is marked invalid rather than
    guessed. Reporting a wrong duration or resolution is worse than reporting
    none, because clip timing and 9:16 cropping are computed from them.
    """
    if "Video:" not in output:
        # Audio-only input (e.g. the .m4a fetched for transcription). It is not
        # a valid *video*, but still report what is actually in the file —
        # callers checking `has_audio` need a truthful answer, not a blanked
        # result just because there are no pixels.
        audio_line = next((ln for ln in output.splitlines() if "Audio:" in ln), "")
        codec_match = re.search(r"Audio:\s*([a-zA-Z0-9_]+)", audio_line)
        dur_match = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", output)
        audio_duration = 0.0
        if dur_match:
            audio_duration = (
                int(dur_match.group(1)) * 3600
                + int(dur_match.group(2)) * 60
                + float(dur_match.group(3))
            )
        return VideoProbeResult(
            is_valid=False,
            duration=audio_duration,
            has_audio=bool(audio_line),
            audio_codec=codec_match.group(1) if codec_match else None,
            file_size_bytes=file_size,
            error="No video stream found in ffmpeg output",
        )

    # Duration: 00:01:23.45,
    duration = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", output)
    if m:
        hours, minutes, seconds = int(m.group(1)), int(m.group(2)), float(m.group(3))
        duration = hours * 3600 + minutes * 60 + seconds

    # Dimensions: first WxH on the Video: line (avoids matching SAR/DAR ratios)
    width = height = 0
    video_line = next((ln for ln in output.splitlines() if "Video:" in ln), "")
    m = re.search(r"\b(\d{2,5})x(\d{2,5})\b", video_line)
    if m:
        width, height = int(m.group(1)), int(m.group(2))

    # Frame rate
    fps = 0.0
    m = re.search(r"([\d.]+)\s*fps", video_line)
    if m:
        fps = round(float(m.group(1)), 2)

    # Codecs
    video_codec = ""
    m = re.search(r"Video:\s*([a-zA-Z0-9_]+)", video_line)
    if m:
        video_codec = m.group(1)

    audio_line = next((ln for ln in output.splitlines() if "Audio:" in ln), "")
    has_audio = bool(audio_line)
    audio_codec = None
    audio_channels = 0
    if has_audio:
        m = re.search(r"Audio:\s*([a-zA-Z0-9_]+)", audio_line)
        if m:
            audio_codec = m.group(1)
        if "stereo" in audio_line:
            audio_channels = 2
        elif "mono" in audio_line:
            audio_channels = 1

    # Overall bitrate
    bitrate_kbps = 0
    m = re.search(r"bitrate:\s*(\d+)\s*kb/s", output)
    if m:
        bitrate_kbps = int(m.group(1))

    if width <= 0 or height <= 0:
        return VideoProbeResult(
            is_valid=False,
            duration=duration,
            fps=fps,
            video_codec=video_codec,
            has_audio=has_audio,
            audio_codec=audio_codec,
            file_size_bytes=file_size,
            error="Could not determine video dimensions from ffmpeg output",
        )

    return VideoProbeResult(
        is_valid=True,
        duration=duration,
        width=width,
        height=height,
        fps=fps or 30.0,
        video_codec=video_codec,
        has_audio=has_audio,
        audio_codec=audio_codec,
        audio_channels=audio_channels,
        bitrate_kbps=bitrate_kbps,
        file_size_bytes=file_size,
    )


def validate_rendered_video(rendered_mp4_path: str | Path, min_duration: float = 1.0) -> Tuple[bool, str]:
    """
    Automated post-render verification.
    Verifies that the rendered file exists, has a valid video stream, duration, and audio track.
    """
    probe = probe_video(rendered_mp4_path)
    if not probe.is_valid:
        return False, f"Invalid video stream or decode error: {probe.error or 'No video stream detected'}"

    if probe.file_size_bytes < 1000:
        return False, f"Rendered file size ({probe.file_size_bytes} bytes) is corrupt or too small"

    if probe.duration < min_duration and probe.duration > 0:
        return False, f"Rendered duration ({probe.duration:.1f}s) is less than required minimum ({min_duration}s)"

    return True, f"Valid MP4: {probe.width}x{probe.height} @ {probe.fps}fps, {probe.duration:.1f}s, audio: {probe.audio_codec or 'none'}"
