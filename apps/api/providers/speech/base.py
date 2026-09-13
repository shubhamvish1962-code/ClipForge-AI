"""Speech-to-Text Provider Abstraction + Mock Implementation."""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from typing import Optional


class BaseSpeechProvider(ABC):
    """Abstract speech-to-text provider interface."""

    @abstractmethod
    async def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        word_timestamps: bool = True,
        speaker_diarization: bool = True,
    ) -> dict:
        """
        Transcribe audio file.
        Returns: {
            "segments": [{"start": float, "end": float, "text": str, "speaker": str, "confidence": float, "words": [...]}],
            "full_text": str,
            "language": str,
            "speakers": [{"label": str, "segment_count": int}],
            "model": str,
        }
        """
        ...


class MockSpeechProvider(BaseSpeechProvider):
    """Mock STT provider with realistic demo transcript."""

    DEMO_SEGMENTS = [
        {"start": 0.0, "end": 5.2, "text": "You know what's interesting about building AI products?", "speaker": "Speaker 1", "confidence": 0.95},
        {"start": 5.2, "end": 12.8, "text": "Most people think the hard part is the technology, but it's actually understanding what humans actually need.", "speaker": "Speaker 1", "confidence": 0.93},
        {"start": 13.1, "end": 15.4, "text": "Can you give us an example of that?", "speaker": "Speaker 2", "confidence": 0.91},
        {"start": 15.8, "end": 28.5, "text": "Sure. We spent six months building this incredibly sophisticated recommendation engine. It could predict what users wanted with 95% accuracy. But nobody used it because the interface was confusing.", "speaker": "Speaker 1", "confidence": 0.94},
        {"start": 29.0, "end": 35.2, "text": "So you had the best technology but the worst user experience?", "speaker": "Speaker 2", "confidence": 0.90},
        {"start": 35.5, "end": 48.3, "text": "Exactly. We threw away three months of work and rebuilt the whole thing with a simple search bar. Engagement went up 400%. Sometimes the simplest solution wins.", "speaker": "Speaker 1", "confidence": 0.96},
        {"start": 48.8, "end": 55.1, "text": "That's a powerful lesson. What about the funding side? How did you convince investors?", "speaker": "Speaker 2", "confidence": 0.89},
        {"start": 55.5, "end": 72.0, "text": "We got rejected by 47 investors before someone said yes. And the one who said yes wasn't even impressed by our technology. They invested because they saw how obsessed we were with the problem.", "speaker": "Speaker 1", "confidence": 0.95},
        {"start": 72.5, "end": 78.3, "text": "47 rejections. That must have been incredibly discouraging.", "speaker": "Speaker 2", "confidence": 0.92},
        {"start": 78.8, "end": 95.0, "text": "It was brutal. There were days I wanted to quit. But every rejection taught us something. By the time we got to investor 48, our pitch was so refined, so clear, so compelling that they wrote us a check in the meeting.", "speaker": "Speaker 1", "confidence": 0.97},
        {"start": 95.5, "end": 102.4, "text": "What's the biggest mistake founders make when pitching?", "speaker": "Speaker 2", "confidence": 0.88},
        {"start": 102.8, "end": 118.0, "text": "They talk about features instead of problems. Nobody cares that you use transformer models or that your latency is 50 milliseconds. They care that their customers are frustrated and you can fix it.", "speaker": "Speaker 1", "confidence": 0.96},
        {"start": 118.5, "end": 125.2, "text": "Features versus problems. That's a great framework.", "speaker": "Speaker 2", "confidence": 0.90},
        {"start": 125.8, "end": 142.0, "text": "And here's the thing most people don't realize: the best products don't just solve problems, they eliminate entire categories of problems. Think about how smartphones eliminated the need for separate cameras, maps, music players, and alarm clocks.", "speaker": "Speaker 1", "confidence": 0.95},
        {"start": 142.5, "end": 148.8, "text": "So what's next for your company? What problem category are you trying to eliminate?", "speaker": "Speaker 2", "confidence": 0.91},
        {"start": 149.2, "end": 168.0, "text": "We're working on making content creation effortless. Right now, if you want to turn a long video into short clips, you need a video editor, a copywriter, a social media manager, and hours of time. We want to eliminate all of that with AI.", "speaker": "Speaker 1", "confidence": 0.94},
        {"start": 168.5, "end": 175.3, "text": "And you think AI is ready for that?", "speaker": "Speaker 2", "confidence": 0.88},
        {"start": 175.8, "end": 195.0, "text": "It's getting there. The models aren't perfect yet, but they're good enough to handle 80% of the work. And that 80% is the boring, repetitive part. We let AI handle the grunt work and let humans focus on the creative decisions.", "speaker": "Speaker 1", "confidence": 0.93},
        {"start": 195.5, "end": 205.0, "text": "That's a really compelling vision. Last question — what advice would you give to someone starting their AI journey today?", "speaker": "Speaker 2", "confidence": 0.90},
        {"start": 205.5, "end": 228.0, "text": "Start with a real problem, not with a technology. Don't build an AI product because AI is cool. Build it because someone is struggling and you can help them. The technology is just a tool. The impact is what matters.", "speaker": "Speaker 1", "confidence": 0.97},
    ]

    async def transcribe(self, audio_path: str, language: Optional[str] = None,
                         word_timestamps: bool = True, speaker_diarization: bool = True) -> dict:
        await asyncio.sleep(random.uniform(1.0, 2.0))  # Simulate processing

        segments = []
        for seg in self.DEMO_SEGMENTS:
            segment = {
                **seg,
                "words": self._generate_word_timestamps(seg["text"], seg["start"], seg["end"]) if word_timestamps else None,
            }
            segments.append(segment)

        full_text = " ".join(s["text"] for s in self.DEMO_SEGMENTS)

        return {
            "segments": segments,
            "full_text": full_text,
            "language": language or "en",
            "word_count": len(full_text.split()),
            "speakers": [
                {"label": "Speaker 1", "segment_count": 11, "total_duration": 168.0},
                {"label": "Speaker 2", "segment_count": 9, "total_duration": 60.0},
            ],
            "model": "mock-stt-v1",
            "is_demo": True,
        }

    def _generate_word_timestamps(self, text: str, start: float, end: float) -> list[dict]:
        words = text.split()
        if not words:
            return []
        duration = end - start
        word_duration = duration / len(words)
        return [
            {
                "word": w,
                "start": round(start + i * word_duration, 3),
                "end": round(start + (i + 1) * word_duration, 3),
                "confidence": round(random.uniform(0.85, 0.99), 2),
            }
            for i, w in enumerate(words)
        ]


def get_speech_provider() -> BaseSpeechProvider:
    from apps.api.core.config import get_settings
    settings = get_settings()
    if settings.speech_provider == "mock":
        return MockSpeechProvider()

    if settings.speech_provider == "faster_whisper":
        try:
            from apps.api.providers.speech.whisper_local import WhisperLocalProvider

            return WhisperLocalProvider(
                model_size=settings.whisper_model_size,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
            )
        except ImportError as e:
            import logging

            logging.getLogger("clipforge.speech").warning(
                f"faster-whisper not installed, falling back to mock: {e}"
            )
            return MockSpeechProvider()

    # Future: openai_whisper, deepgram, assemblyai
    return MockSpeechProvider()
