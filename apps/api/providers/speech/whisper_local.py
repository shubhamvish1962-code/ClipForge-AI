"""
Local speech-to-text via faster-whisper (CTranslate2).

Runs entirely offline — no API key, no per-video cost. The model is downloaded
once on first use and cached by huggingface_hub.

Two things this provider does NOT do, deliberately:

* **Speaker diarization.** Whisper does not identify speakers. Rather than
  fabricate labels, every segment is attributed to a single speaker. Real
  diarization needs a separate model (pyannote) and is out of scope here.
* **Blocking the event loop.** Transcription is CPU/GPU bound and can take
  minutes, so it runs in a worker thread.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from apps.api.providers.speech.base import BaseSpeechProvider

logger = logging.getLogger("clipforge.speech.whisper")

#: Transcripts are cached here, keyed by file content hash + model.
CACHE_DIR = Path("storage/transcripts")

# 16 kHz mono is what Whisper expects; anything else gets resampled internally.
_SAMPLE_RATE = 16000

#: Set once CUDA is proven unusable, so later calls skip the failing attempt
#: instead of paying the load-and-fail cost on every transcription.
_CUDA_UNUSABLE = False


class WhisperLocalProvider(BaseSpeechProvider):
    """faster-whisper backed transcription with word-level timestamps."""

    _model: Any = None
    _model_key: Optional[tuple] = None

    def __init__(self, model_size: str = "base", device: str = "auto", compute_type: str = "auto"):
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type

    # ── model loading (shared across instances) ──────────────────────────

    @classmethod
    def _get_model(cls, model_size: str, device: str, compute_type: str):
        """Load once and reuse — model init is expensive."""
        key = (model_size, device, compute_type)
        if cls._model is not None and cls._model_key == key:
            return cls._model

        from faster_whisper import WhisperModel

        resolved_device, resolved_compute = _resolve_device(device, compute_type)
        logger.info(
            f"Loading faster-whisper '{model_size}' on {resolved_device} ({resolved_compute}). "
            "First run downloads the model."
        )

        try:
            model = WhisperModel(model_size, device=resolved_device, compute_type=resolved_compute)
        except Exception as e:
            # A CUDA device can be present while its runtime libraries are not
            # (cuBLAS/cuDNN ship with the CUDA toolkit, not the driver). Counting
            # devices is not proof CUDA works, so fall back rather than fail.
            if resolved_device != "cuda" or device != "auto":
                raise
            logger.warning(
                f"CUDA present but unusable ({str(e)[:120]}); falling back to CPU int8. "
                "Install the CUDA runtime (cuBLAS + cuDNN) for GPU transcription."
            )
            resolved_device, resolved_compute = "cpu", "int8"
            model = WhisperModel(model_size, device=resolved_device, compute_type=resolved_compute)

        cls._model = model
        cls._model_key = key
        return cls._model

    # ── BaseSpeechProvider ───────────────────────────────────────────────

    async def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        word_timestamps: bool = True,
        speaker_diarization: bool = True,
    ) -> dict:
        # Guard the empty string explicitly: Path("") is Path("."), which exists,
        # so a plain exists() check passes and Whisper then tries to read the
        # working directory — surfacing as a baffling "Permission denied: '.'".
        if not str(audio_path).strip():
            raise ValueError("No audio path supplied for transcription (empty source path)")

        source = Path(audio_path)
        if not source.is_file():
            raise FileNotFoundError(f"Audio/video file not found for transcription: {audio_path}")

        cache_key = _cache_key(source, self._model_size, language)
        cached = _read_cache(cache_key)
        if cached is not None:
            logger.info(f"Transcript cache hit for {source.name}")
            return cached

        result = await asyncio.to_thread(
            self._transcribe_sync, source, language, word_timestamps
        )
        _write_cache(cache_key, result)
        return result

    # ── internals ────────────────────────────────────────────────────────

    def _transcribe_sync(self, source: Path, language: Optional[str], word_timestamps: bool) -> dict:
        model = self._get_model(self._model_size, self._device, self._compute_type)

        # Whisper reads media directly, but going through ffmpeg first gives a
        # predictable 16 kHz mono wav and avoids container quirks.
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "audio.wav"
            if not _extract_audio(source, wav):
                # Fall back to letting whisper open the original file.
                wav = source

            try:
                segments_iter, info = model.transcribe(
                    str(wav),
                    language=language,
                    word_timestamps=word_timestamps,
                    vad_filter=True,  # skip silence — faster and avoids hallucinated text
                )
                # Force the lazy generator to run now, so a CUDA failure surfaces
                # here where it can still be retried rather than mid-iteration.
                segment_list = list(segments_iter)
            except Exception as e:
                if not _is_cuda_runtime_error(e) or self._device != "auto":
                    raise
                logger.warning(
                    f"GPU transcription failed ({str(e)[:120]}); retrying on CPU. "
                    "Install the CUDA runtime (cuBLAS + cuDNN) for GPU support."
                )
                global _CUDA_UNUSABLE
                _CUDA_UNUSABLE = True  # don't pay for this attempt again
                type(self)._model = None
                type(self)._model_key = None
                self._device, self._compute_type = "cpu", "int8"
                model = self._get_model(self._model_size, "cpu", "int8")
                segments_iter, info = model.transcribe(
                    str(wav),
                    language=language,
                    word_timestamps=word_timestamps,
                    vad_filter=True,
                )
                segment_list = list(segments_iter)

            segments: list[dict] = []
            full_text_parts: list[str] = []
            word_total = 0

            for seg in segment_list:
                text = (seg.text or "").strip()
                if not text:
                    continue

                words = None
                if word_timestamps and getattr(seg, "words", None):
                    words = [
                        {
                            "word": w.word.strip(),
                            "start": round(float(w.start), 3),
                            "end": round(float(w.end), 3),
                            "confidence": round(float(getattr(w, "probability", 1.0) or 1.0), 3),
                        }
                        for w in seg.words
                        if w.start is not None and w.end is not None
                    ]
                    word_total += len(words or [])

                segments.append({
                    "start": round(float(seg.start), 3),
                    "end": round(float(seg.end), 3),
                    "text": text,
                    # Whisper has no speaker model; see module docstring.
                    "speaker": "Speaker 1",
                    "confidence": round(_confidence_from(seg), 3),
                    "words": words,
                })
                full_text_parts.append(text)

        full_text = " ".join(full_text_parts).strip()
        if not word_total:
            word_total = len(full_text.split())

        duration = segments[-1]["end"] if segments else 0.0
        logger.info(
            f"Transcribed {source.name}: {len(segments)} segments, "
            f"{word_total} words, {duration:.1f}s, lang={info.language}"
        )

        return {
            "segments": segments,
            "full_text": full_text,
            "word_count": word_total,
            "language": info.language or "en",
            "speakers": [{
                "label": "Speaker 1",
                "segment_count": len(segments),
                "total_duration": round(duration, 2),
            }],
            "model": f"faster-whisper-{self._model_size}",
        }


def _is_cuda_runtime_error(e: Exception) -> bool:
    """True when the failure looks like a missing CUDA runtime rather than bad input."""
    msg = str(e).lower()
    return any(t in msg for t in ("cublas", "cudnn", "cuda", "libcu", ".dll is not found"))


def _confidence_from(seg: Any) -> float:
    """
    Map avg_logprob onto a rough 0-1 confidence.

    Whisper reports an average log probability, not a probability. exp() gives a
    usable monotonic proxy for ranking segments; it is not calibrated.
    """
    lp = getattr(seg, "avg_logprob", None)
    if lp is None:
        return 0.9
    import math

    return max(0.0, min(1.0, math.exp(float(lp))))


def _extract_audio(source: Path, dest: Path) -> bool:
    """Pull a 16 kHz mono wav out of any media file. False if ffmpeg fails."""
    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        res = subprocess.run(
            [
                ffmpeg, "-y", "-i", str(source),
                "-vn", "-ac", "1", "-ar", str(_SAMPLE_RATE),
                "-c:a", "pcm_s16le", str(dest),
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600,
        )
        return res.returncode == 0 and dest.exists() and dest.stat().st_size > 0
    except Exception as e:
        logger.warning(f"Audio extraction failed for {source.name}: {e}")
        return False


def _resolve_device(device: str, compute_type: str) -> tuple[str, str]:
    """Use CUDA when it is actually usable, otherwise int8 on CPU."""
    if device != "auto":
        return device, (compute_type if compute_type != "auto" else "default")

    if not _CUDA_UNUSABLE:
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                return "cuda", ("float16" if compute_type == "auto" else compute_type)
        except Exception:
            pass

    return "cpu", ("int8" if compute_type == "auto" else compute_type)


# ── caching ──────────────────────────────────────────────────────────────


def _cache_key(source: Path, model_size: str, language: Optional[str]) -> str:
    """
    Hash file identity + model settings.

    Uses size and mtime rather than full content so a multi-GB video does not
    have to be read twice just to decide whether to reuse a transcript.
    """
    stat = source.stat()
    raw = f"{source.resolve()}|{stat.st_size}|{int(stat.st_mtime)}|{model_size}|{language or 'auto'}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _read_cache(key: str) -> Optional[dict]:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(key: str, payload: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{key}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"Could not cache transcript: {e}")
