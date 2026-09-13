"""
Generate a test video that actually contains speech.

The existing `create_test_video.py` produces a 440 Hz sine tone, which is fine
for render plumbing but useless for transcription — Whisper's VAD correctly
strips it as silence, so ASR and clip selection can never be exercised.

This builds a real spoken-word fixture using the Windows TTS voice, then muxes
it onto a test video track. Ground truth is known, so transcription accuracy
can be checked rather than guessed.

Usage:  python scripts/create_speech_sample.py
Output: storage/sample_speech_video.mp4
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT = Path("storage/sample_speech_video.mp4")

# Deliberately written to contain the signals clip selection looks for:
# a question-and-answer beat, concrete numbers, and contrast markers.
SCRIPT = """
Most people think the hardest part of building a product is the technology.
It isn't. The hardest part is figuring out what people actually want.
So what changed for us? We spent six months building a recommendation engine.
It predicted user behaviour with ninety five percent accuracy.
And almost nobody used it, because the interface confused them.
We threw away three months of work and replaced it with a single search bar.
Engagement went up four hundred percent in two weeks.
The lesson was brutal but simple. Accuracy is not the same thing as usefulness.
Here is the part nobody talks about. We were rejected by forty seven investors.
Every rejection taught us something about how to explain the problem.
By the time we reached investor forty eight, the pitch was sharp enough to close in one meeting.
If you are building something right now, start with the problem, not the technology.
"""


def synthesize(dest: Path) -> bool:
    """Render SCRIPT to a wav file with the Windows speech synthesizer."""
    text = " ".join(SCRIPT.split())
    ps = f"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Rate = 0
$s.SetOutputToWaveFile("{dest}")
$s.Speak(@'
{text}
'@)
$s.Dispose()
"""
    res = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True, text=True, timeout=180,
    )
    if res.returncode != 0:
        print("TTS failed:", res.stderr[:300])
        return False
    return dest.exists() and dest.stat().st_size > 1000


def build_video(wav: Path, out: Path) -> bool:
    """Mux the speech onto a simple video track sized like real footage."""
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    out.parent.mkdir(parents=True, exist_ok=True)

    res = subprocess.run(
        [
            ffmpeg, "-y",
            "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30",
            "-i", str(wav),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",              # length follows the speech
            str(out),
        ],
        capture_output=True, text=True, timeout=600,
    )
    if res.returncode != 0:
        print("ffmpeg mux failed:", res.stderr[-400:])
        return False
    return out.exists() and out.stat().st_size > 0


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "speech.wav"
        print("Synthesizing speech...")
        if not synthesize(wav):
            sys.exit("Could not synthesize speech")
        print(f"  wav: {wav.stat().st_size/1024:.0f} KB")

        print("Building video...")
        if not build_video(wav, OUT):
            sys.exit("Could not build video")

    from apps.api.video.probe import probe_video

    p = probe_video(OUT)
    print(f"\nCreated {OUT}")
    print(f"  {p.width}x{p.height}  {p.duration:.1f}s  audio={p.audio_codec}  valid={p.is_valid}")


if __name__ == "__main__":
    main()
