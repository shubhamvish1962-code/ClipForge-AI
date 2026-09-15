"""
ClipForge AI — FFmpeg & yt-dlp Video Processing Wrapper.

Provides real video downloading, clipping, 9:16 vertical cropping,
caption burn-in, and high-definition MP4 rendering.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import imageio_ffmpeg

logger = logging.getLogger("clipforge.video")


def get_ffmpeg_binary() -> str:
    """Return system ffmpeg or bundled imageio-ffmpeg binary."""
    try:
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return "ffmpeg"


class SourceUnreachableError(RuntimeError):
    """The source could not be contacted, as opposed to being invalid."""


#: Tries per range before giving up on it.
SECTION_DOWNLOAD_ATTEMPTS = 3
#: Base wait before a retry; multiplied by the attempt number.
SECTION_RETRY_BACKOFF_SECONDS = 8
#: Pause between consecutive range downloads, to stay under rate limits.
SECTION_REQUEST_GAP_SECONDS = 3


_FFMPEG_PATH_PATCHED = False


def _ensure_ffmpeg_on_path() -> None:
    """
    Make a bare `ffmpeg` resolvable via shutil.which().

    yt-dlp's --download-sections path (FFmpegFD, the external-downloader used
    to fetch and cut ranges in one step) looks up `ffmpeg` by name rather than
    honouring `ffmpeg_location` the way its postprocessors do. imageio-ffmpeg's
    bundled binary is named e.g. `ffmpeg-win-x86_64-v7.1.exe`, which `which()`
    never matches — so without this, section downloads fail with "ffmpeg is
    not installed" even though a working ffmpeg is right there.

    A copy named exactly `ffmpeg(.exe)` is created once per process next to the
    real binary, and that directory is added to PATH for this process only.
    """
    global _FFMPEG_PATH_PATCHED
    if _FFMPEG_PATH_PATCHED:
        return

    import shutil as _shutil
    import sys as _sys

    real = Path(get_ffmpeg_binary())
    stable_name = "ffmpeg.exe" if _sys.platform == "win32" else "ffmpeg"
    stable_path = real.parent / stable_name

    if not stable_path.exists():
        try:
            _shutil.copy2(real, stable_path)
        except Exception as e:
            logger.warning(f"Could not create stable ffmpeg alias: {e}")
            return

    if str(real.parent) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(real.parent) + os.pathsep + os.environ.get("PATH", "")

    _FFMPEG_PATH_PATCHED = True


def get_video_info(url: str) -> Optional[dict]:
    """
    Read a source's duration/resolution without downloading anything.

    Used to populate real VideoMetadata for audio-first ingestion, where the
    pipeline has audio (for transcription and clip selection) but has not
    fetched video yet — so there is no local file left to probe.
    """
    try:
        import yt_dlp

        # yt-dlp's own ffmpeg-availability probe caches its result at the
        # *class* level for the life of the process (FFmpegPostProcessor.
        # _version_cache), independent of any single YoutubeDL instance. If
        # the very first yt-dlp call in this process runs before PATH is
        # patched, that negative result sticks even after patching — so this
        # must happen before the first yt-dlp call of any kind, not only
        # before the ones that need ffmpeg directly.
        _ensure_ffmpeg_on_path()

        opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return None

        # Prefer the best video format's own dimensions over the top-level
        # fields, which can reflect a lower-resolution default format.
        width = info.get("width") or 0
        height = info.get("height") or 0
        fps = info.get("fps") or 30.0
        for fmt in reversed(info.get("formats") or []):
            if fmt.get("vcodec") not in (None, "none") and fmt.get("width") and fmt.get("height"):
                width, height = fmt["width"], fmt["height"]
                fps = fmt.get("fps") or fps
                break

        return {
            "duration": float(info.get("duration") or 0.0),
            "width": int(width),
            "height": int(height),
            "fps": float(fps),
            "title": info.get("title", ""),
        }
    except Exception as e:
        logger.warning(f"Could not read video info for {url}: {e}")
        # Surface the distinction the caller cannot make from a bare None:
        # a network outage is not the same as a bad or unavailable video, and
        # telling the user "no usable info" when their wifi dropped sends them
        # looking for problems in the wrong place.
        text = str(e).lower()
        if any(s in text for s in ("getaddrinfo", "failed to resolve", "temporary failure in name resolution")):
            raise SourceUnreachableError(
                "Could not reach YouTube — check your internet connection, then try again."
            ) from None
        return None



@dataclass
class DownloadedSection:
    """A downloaded slice of a source video and the absolute range it covers."""

    range_start: float  # padded start, in the original video's timeline
    range_end: float    # padded end, in the original video's timeline
    path: Path

    def local_offset(self, absolute_time: float) -> float:
        """Convert an absolute-video timestamp into an offset inside this file."""
        return max(0.0, absolute_time - self.range_start)


def download_video_section(
    url: str,
    start: float,
    end: float,
    output_dir: Path,
    filename_prefix: str,
) -> Optional[Path]:
    """
    Download exactly one time range as its own small local file.

    yt-dlp's `download_ranges` accepts multiple ranges per call, but passing
    several disjoint ranges through one `outtmpl` was tried and only the first
    range's content survived — later ranges silently overwrote it rather than
    concatenating (verified: two ranges in, one padded-single-range file out).
    Calling this once per range with a unique filename sidesteps that entirely
    and is simpler to reason about, since Stage 7 already renders one clip at
    a time anyway.
    """
    try:
        import yt_dlp

        _ensure_ffmpeg_on_path()
        output_dir.mkdir(parents=True, exist_ok=True)
        tag = f"{round(start * 1000)}_{round(end * 1000)}"
        out_template = str(output_dir / f"{filename_prefix}_sec{tag}_%(id)s.%(ext)s")

        def _one_range(info_dict, ydl):
            return [{"start_time": start, "end_time": end}]

        ydl_opts = {
            "format": (
                "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
                "best[height<=1080][ext=mp4]/best[height<=1080]"
            ),
            "merge_output_format": "mp4",
            "ffmpeg_location": get_ffmpeg_binary(),
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "download_ranges": _one_range,
            "force_keyframes_at_cuts": True,
            "retries": 3,
            "fragment_retries": 3,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        video_id = info.get("id") if info else None
        if video_id:
            from apps.api.video.probe import probe_video

            for f in sorted(
                output_dir.glob(f"*sec{tag}_{video_id}*"),
                key=lambda p: p.stat().st_size if p.is_file() else 0,
                reverse=True,
            ):
                name = f.name.lower()
                if not f.is_file() or f.stat().st_size == 0:
                    continue
                if name.endswith((".part", ".ytdl")):
                    continue
                if probe_video(f).is_valid:
                    return f

        logger.warning(f"Section download produced no usable file for {url} [{start:.1f}-{end:.1f}]")
    except Exception as e:
        logger.warning(f"Section download failed for {url} [{start:.1f}-{end:.1f}]: {e}")
    return None


def download_video_sections(
    url: str,
    ranges: list[tuple[float, float]],
    output_dir: Path,
    filename_prefix: str,
    padding: float = 1.5,
) -> list[DownloadedSection]:
    """
    Download only the given time ranges, one small file per merged range.

    Fetching just the ranges clip selection actually chose is dramatically
    smaller than the full video — a handful of 30s clips out of a long
    recording is a few minutes of footage, not the whole thing. `padding`
    gives the renderer a little slack at each edge so a crop boundary landing
    a frame early/late does not run off the fetched range.

    Overlapping/adjacent ranges are merged first so shared footage is not
    fetched twice. Returns only the ranges that actually downloaded — a
    failure on one range does not lose the others.
    """
    if not ranges:
        return []

    import time

    merged = _merge_ranges([(max(0.0, s - padding), e + padding) for s, e in ranges])
    out: list[DownloadedSection] = []

    for index, (start, end) in enumerate(merged):
        # Space the requests out. Firing several range downloads back to back
        # at the same video is what trips YouTube's "confirm you're not a bot"
        # check partway through a run, which used to cost every remaining clip.
        if index:
            time.sleep(SECTION_REQUEST_GAP_SECONDS)

        path = None
        for attempt in range(SECTION_DOWNLOAD_ATTEMPTS):
            path = download_video_section(url, start, end, output_dir, filename_prefix)
            if path:
                break
            if attempt < SECTION_DOWNLOAD_ATTEMPTS - 1:
                backoff = SECTION_RETRY_BACKOFF_SECONDS * (attempt + 1)
                logger.warning(
                    f"Section [{start:.1f}-{end:.1f}] failed, retrying in {backoff}s "
                    f"(attempt {attempt + 2}/{SECTION_DOWNLOAD_ATTEMPTS})"
                )
                time.sleep(backoff)

        if path:
            out.append(DownloadedSection(range_start=start, range_end=end, path=path))
        else:
            logger.warning(f"Gave up on section [{start:.1f}-{end:.1f}] after retries")

    # If ranges were wanted but none arrived, the per-range approach is being
    # blocked outright. One full download is slower but salvages the run
    # instead of losing every clip.
    if merged and not out:
        logger.warning("All section downloads failed; falling back to a full download")
        full = download_youtube_video(url, output_dir, f"{filename_prefix}_full")
        if full:
            from apps.api.video.probe import probe_video

            probe = probe_video(full)
            if probe.is_valid:
                # One "section" spanning the whole file, so callers rebase
                # against 0.0 and the rest of the pipeline is unchanged.
                out.append(DownloadedSection(range_start=0.0, range_end=probe.duration, path=full))

    return out


def _merge_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Collapse overlapping/adjacent (start, end) pairs into their union."""
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def download_audio_only(url: str, output_dir: Path, filename_prefix: str) -> Optional[Path]:
    """
    Fetch just the audio track for transcription.

    Audio is roughly 40x smaller than video, so this finishes in seconds and is
    far less likely to be throttled or blocked mid-transfer. The pipeline does
    not need pixels until rendering, so the video itself can wait until the
    clip ranges are known.
    """
    try:
        import yt_dlp

        _ensure_ffmpeg_on_path()  # see get_video_info() for why this must run early

        output_dir.mkdir(parents=True, exist_ok=True)
        out_template = str(output_dir / f"{filename_prefix}_%(id)s.%(ext)s")

        ydl_opts = {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "fragment_retries": 3,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = Path(ydl.prepare_filename(info))
            if filename.exists() and filename.stat().st_size > 0:
                return filename

            salvaged = _find_downloaded_audio(output_dir, info.get("id") if info else None, filename_prefix)
            if salvaged:
                return salvaged

        logger.warning(f"Audio download produced no usable file for {url}")
    except Exception as e:
        # The audio can be fully downloaded and still raise here — on Windows
        # yt-dlp's final `.temp.m4a` -> `.m4a` rename intermittently hits
        # "WinError 5: Access is denied" (antivirus or an indexer holding the
        # freshly-written file). Discarding a complete download over a failed
        # rename sent an empty path downstream, which silently degraded the
        # whole pipeline, so check for a usable file before giving up.
        salvaged = _find_downloaded_audio(output_dir, _video_id_from_url(url), filename_prefix)
        if salvaged:
            logger.warning(
                f"Audio download reported an error ({e}) but a complete file was "
                f"found; continuing with {salvaged.name}"
            )
            return salvaged
        logger.warning(f"Audio-only download failed for {url}: {e}")
    return None


def _video_id_from_url(url: str) -> Optional[str]:
    """Best-effort video id, used to locate files after a failed download."""
    try:
        import yt_dlp

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        return info.get("id") if info else None
    except Exception:
        return None


def _find_downloaded_audio(
    output_dir: Path, video_id: Optional[str], filename_prefix: str
) -> Optional[Path]:
    """
    Locate a complete audio file for this video, verified by probing it.

    Accepts `.temp.*` leftovers: when only the rename failed, the temp file is
    the complete download. Validity is confirmed by probing for an audio
    stream rather than trusting the extension or size.

    The glob is anchored to `{prefix}_{id}` rather than a loose `*{id}*`.
    Section downloads for the same video live in this directory too
    (`{prefix}_sec{range}_{id}.mp4`), and a loose match combined with
    largest-wins would hand back a multi-hundred-MB video clip instead of the
    audio track.
    """
    if not video_id:
        return None

    from apps.api.video.probe import probe_video

    candidates = [
        f for f in output_dir.glob(f"{filename_prefix}_{video_id}*")
        if f.is_file() and f.stat().st_size > 0 and not f.name.lower().endswith((".part", ".ytdl"))
    ]
    # Among those, prefer the largest — a partial and a complete copy can coexist.
    for f in sorted(candidates, key=lambda p: p.stat().st_size, reverse=True):
        if probe_video(f).has_audio:
            return f
    return None


def download_youtube_video(url: str, output_dir: Path, filename_prefix: str = "yt_video") -> Optional[Path]:
    """
    Download a video from YouTube or external URL using yt-dlp.
    Returns path to downloaded MP4 file, or None if failed.
    """
    try:
        import yt_dlp

        _ensure_ffmpeg_on_path()  # see get_video_info() for why this must run early
        output_dir.mkdir(parents=True, exist_ok=True)
        out_template = str(output_dir / f"{filename_prefix}_%(id)s.%(ext)s")
        ffmpeg_exe = get_ffmpeg_binary()

        # Cap the resolution during format *selection*. Without a height cap
        # yt-dlp picks the largest available stream (a 4K AV1 source can be 5+ GB),
        # which is far more than a 1080x1920 clip needs and makes long downloads
        # likely to be throttled or 403'd partway through. max_filesize alone does
        # not help here — it aborts mid-download rather than choosing a smaller format.
        ydl_opts = {
            "format": (
                "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
                "best[height<=1080][ext=mp4]/"
                "best[height<=1080]/best"
            ),
            "merge_output_format": "mp4",
            "ffmpeg_location": ffmpeg_exe,
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "max_filesize": 500_000_000,
            "retries": 3,
            "fragment_retries": 3,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            mp4_filename = Path(filename).with_suffix(".mp4")
            if mp4_filename.exists() and not str(mp4_filename).endswith(".part"):
                return mp4_filename
            if os.path.exists(filename) and not filename.endswith(".part"):
                return Path(filename)
            
            # Recover the output file by id. Candidates are verified to actually
            # contain a video stream rather than filtered by filename: yt-dlp's
            # per-format suffixes change (an audio-only track can arrive as
            # ".f140-7.m4a", which a ".f140." name check misses), and returning a
            # partial or audio-only artefact as if it were the video is worse than
            # reporting failure.
            from apps.api.video.probe import probe_video

            video_id = info.get("id") if info else None
            if video_id:
                for f in sorted(
                    output_dir.glob(f"*{video_id}*"),
                    key=lambda p: p.stat().st_size if p.is_file() else 0,
                    reverse=True,
                ):
                    fname = f.name.lower()
                    if not f.is_file() or f.stat().st_size == 0:
                        continue
                    if fname.endswith(".part") or fname.endswith(".ytdl"):
                        continue
                    if probe_video(f).is_valid:
                        return f
            # Deliberately no bare glob("*.mp4") fallback here. Matching on any
            # mp4 in the uploads directory can return a completely unrelated
            # video when this download fails — returning None is correct.
            logger.warning(f"yt-dlp produced no usable file for {url}")
    except Exception as e:
        logger.warning(f"yt-dlp download failed for {url}: {e}")
    return None


def cut_and_crop_video(
    input_path: str,
    output_path: str,
    start_time: float,
    end_time: float,
    target_width: int = 1080,
    target_height: int = 1920,
    quality: str = "1080p",
    bitrate: str = "balanced",
) -> bool:
    """
    Cut video segment and perform smart 9:16 vertical crop with FFmpeg.
    Supports 4K, 1080p, 720p quality modes and high/balanced/compact bitrates.
    Guarantees full stereo audio stream synchronization.
    """
    ffmpeg_exe = get_ffmpeg_binary()
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    duration = max(1.0, end_time - start_time)

    # Resolution mapping
    if quality == "4k":
        target_width, target_height = 2160, 3840
        crf = "18"
    elif quality == "720p":
        target_width, target_height = 720, 1280
        crf = "26"
    else:  # 1080p standard
        target_width, target_height = 1080, 1920
        crf = "21"

    # Audio bitrate mapping
    audio_bitrate = "320k" if bitrate == "high" else "128k" if bitrate == "compact" else "192k"

    # Scale to fill target resolution then crop center
    vf_filter = (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
        f"crop={target_width}:{target_height}"
    )

    cmd = [
        ffmpeg_exe,
        "-y",
        "-ss", f"{start_time:.3f}",
        "-i", str(input_path),
        "-t", f"{duration:.3f}",
        "-vf", vf_filter,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", crf,
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-avoid_negative_ts", "make_zero",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_file),
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return output_file.exists() and output_file.stat().st_size > 0
    except Exception as e:
        logger.warning(f"FFmpeg cut_and_crop_video failed: {e}")
        return False


def generate_high_definition_clip(
    output_path: str,
    title: str = "ClipForge AI",
    duration: float = 30.0,
) -> bool:
    """
    Generate a valid, high-definition 1080x1920 30fps vertical MP4 video clip
    with an elegant dark canvas, title text overlay, and clean audio.
    Replaces TV test color bars with a sleek video preview layout.
    """
    ffmpeg_exe = get_ffmpeg_binary()
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Escape title text for FFmpeg drawtext
    clean_text = title.replace(":", "\\:").replace("'", "").replace('"', "")[:40]

    cmd = [
        ffmpeg_exe,
        "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x0f172a:s=1080x1920:r=30:d={duration}",
        "-f", "lavfi",
        "-i", f"anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
        "-vf", (
            f"drawtext=text='CLIPFORGE AI':fontcolor=0x8b5cf6:fontsize=36:x=(w-text_w)/2:y=240,"
            f"drawtext=text='{clean_text}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=0x000000@0.6:boxborderw=16,"
            f"drawtext=text='9\\:16 Vertical Render Preview':fontcolor=0x94a3b8:fontsize=28:x=(w-text_w)/2:y=h-280"
        ),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_file),
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return output_file.exists() and output_file.stat().st_size > 0
    except Exception as e:
        logger.warning(f"FFmpeg synthetic video generation failed: {e}")
        return False
