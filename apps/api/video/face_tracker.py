"""
Face and active-speaker tracking for 9:16 reframing.

The renderer previously always centre-cropped, so whoever was talking could sit
off-frame for the whole clip. This module works out where to put the crop window
over time.

Three decisions shape the implementation:

* **Sample, don't scan.** Faces are detected a few times per second, not on every
  frame. Nobody moves fast enough to need 30 fps detection, and sampling is an
  order of magnitude cheaper.
* **Smooth and resist.** Raw per-sample positions jitter. Positions are averaged
  over a window, and switching to a different face requires a sustained change —
  otherwise the crop flips back and forth between two people.
* **Degrade, don't fail.** If MediaPipe is missing, or no face is found, callers
  get None and keep the existing centre-crop behaviour.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("clipforge.video.face_tracker")

#: Detections per second of video. 3 is plenty for head movement.
SAMPLE_FPS = 3.0
#: Averaging window, in samples, applied to the crop centre.
SMOOTHING_WINDOW = 5
#: A different face must win by this margin (fraction of frame width) before the
#: crop moves to it. Prevents flip-flopping between two similar faces.
SWITCH_HYSTERESIS = 0.12
#: Below this detection confidence a face is ignored.
MIN_DETECTION_CONFIDENCE = 0.5
#: Give up after this many consecutive face-free samples at the start of a clip.
EARLY_EXIT_SAMPLES = 12


@dataclass
class TrackPoint:
    """Where the crop should be centred at a moment in time."""

    time: float
    #: Horizontal centre as a fraction of frame width (0.0 = left, 1.0 = right).
    center_x: float
    #: Vertical centre as a fraction of frame height.
    center_y: float
    face_count: int = 0
    confidence: float = 0.0


#: Optional MediaPipe Tasks model. MediaPipe 1.x dropped the legacy
#: `mp.solutions` API, and its Tasks FaceDetector needs an explicit .tflite
#: asset that does not ship with the package. Drop `blaze_face_short_range.tflite`
#: here to use it; otherwise the bundled OpenCV cascade is used.
MEDIAPIPE_MODEL = Path("storage/models/blaze_face_short_range.tflite")


def is_available() -> bool:
    """True when face tracking can actually run."""
    try:
        import cv2  # noqa: F401

        return True
    except ImportError:
        return False


def _make_detector():
    """
    Build a frame -> list[face dict] callable.

    Prefers MediaPipe when its model asset is present (better with angled and
    partially occluded faces), otherwise falls back to the Haar cascade that
    ships inside opencv — which needs no download and works offline.
    """
    if MEDIAPIPE_MODEL.exists():
        try:
            return _mediapipe_detector()
        except Exception as e:
            logger.warning(f"MediaPipe detector unavailable ({e}); using OpenCV cascade")

    return _cascade_detector()


def _mediapipe_detector():
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    import mediapipe as mp
    import numpy as np

    options = vision.FaceDetectorOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(MEDIAPIPE_MODEL)),
        min_detection_confidence=MIN_DETECTION_CONFIDENCE,
    )
    detector = vision.FaceDetector.create_from_options(options)

    def detect(frame_rgb, width: int, height: int) -> list[dict]:
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(frame_rgb))
        result = detector.detect(image)
        faces = []
        for det in (result.detections or []):
            box = det.bounding_box
            w = box.width / width
            h = box.height / height
            if w <= 0 or h <= 0:
                continue
            score = float(det.categories[0].score) if det.categories else 0.0
            faces.append({
                "cx": min(1.0, max(0.0, box.origin_x / width + w / 2)),
                "cy": min(1.0, max(0.0, box.origin_y / height + h * 0.4)),
                "area": w * h,
                "score": score,
            })
        return faces

    logger.info("Face detection: MediaPipe Tasks")
    return detect


def _cascade_detector():
    import cv2

    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_alt2.xml"
    cascade = cv2.CascadeClassifier(str(cascade_path))
    if cascade.empty():
        raise RuntimeError(f"Could not load Haar cascade from {cascade_path}")

    def detect(frame_rgb, width: int, height: int) -> list[dict]:
        gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
        gray = cv2.equalizeHist(gray)
        found = cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5,
            minSize=(int(min(width, height) * 0.06),) * 2,
        )
        faces = []
        for (x, y, w, h) in found:
            faces.append({
                "cx": min(1.0, max(0.0, (x + w / 2) / width)),
                "cy": min(1.0, max(0.0, (y + h * 0.4) / height)),
                "area": (w / width) * (h / height),
                # Haar gives no confidence; treat every accepted hit equally.
                "score": 1.0,
            })
        return faces

    logger.info("Face detection: OpenCV Haar cascade")
    return detect


def track_faces(
    video_path: str | Path,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
    sample_fps: float = SAMPLE_FPS,
) -> Optional[list[TrackPoint]]:
    """
    Sample the clip range and return a smoothed crop path.

    Returns None when tracking is unavailable or no face was found anywhere in
    the range, so the caller can fall back to centre-crop.
    """
    if not is_available():
        logger.info("Face tracking unavailable (mediapipe/opencv not installed)")
        return None

    import cv2

    path = Path(video_path)
    if not path.exists():
        logger.warning(f"Cannot track faces, file missing: {path}")
        return None

    samples: list[tuple[float, list[dict]]] = []
    for outcome in _scan_faces(path, start_time, end_time, sample_fps):
        if outcome is None:
            return None  # file could not be opened
        samples.append(outcome)

    if not samples:
        logger.info(f"No faces detected in {path.name} between {start_time:.1f}s")
        return None

    raw: list[TrackPoint] = []
    previous_center: Optional[float] = None
    for t, faces in samples:
        if not faces:
            continue
        chosen = _choose_face(faces, previous_center)
        previous_center = chosen["cx"]
        raw.append(TrackPoint(
            time=round(t, 3), center_x=chosen["cx"], center_y=chosen["cy"],
            face_count=len(faces), confidence=chosen["score"],
        ))

    if not raw:
        logger.info(f"No faces detected in {path.name} between {start_time:.1f}s")
        return None

    smoothed = _smooth(raw)
    logger.info(
        f"Tracked {len(smoothed)} points in {path.name} ({start_time:.1f}s+), "
        f"max faces={max(p.face_count for p in raw)}"
    )
    return smoothed


def _scan_faces(path: Path, start_time: float, end_time: Optional[float], sample_fps: float):
    """
    Shared frame-sampling core for both single- and dual-speaker tracking.

    Yields (timestamp, faces_at_that_timestamp) for each sampled frame — or a
    single `None` if the file could not even be opened, which callers must
    check for before treating an empty result as "no faces found".
    """
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        logger.warning(f"OpenCV could not open {path.name}")
        yield None
        return

    try:
        native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        video_duration = frame_count / native_fps if native_fps else 0.0

        end = end_time if end_time is not None else video_duration
        end = min(end, video_duration) if video_duration else end
        if end <= start_time:
            return

        detect = _make_detector()

        # Seek once to the clip start, then read forward. Per-sample seeking
        # (cap.set) costs far more than decoding the frames in between, because
        # each seek re-syncs to a keyframe.
        cap.set(cv2.CAP_PROP_POS_MSEC, start_time * 1000.0)

        frame_stride = max(1, int(round(native_fps / max(sample_fps, 0.5))))
        index = 0
        samples_taken = 0
        found_any = False

        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break

            t = start_time + index / native_fps
            if t >= end:
                break

            if index % frame_stride == 0:
                samples_taken += 1
                height, width = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                faces = detect(rgb, width, height)
                found_any = found_any or bool(faces)

                if not faces and not found_any and samples_taken >= EARLY_EXIT_SAMPLES:
                    # Nothing face-like in the opening seconds — this is very
                    # likely screen capture, b-roll or animation. Scanning the
                    # rest would only burn time to reach the same answer.
                    logger.info(
                        f"No face in first {samples_taken} samples of {path.name}; "
                        "skipping the rest of the scan"
                    )
                    break

                yield (round(t, 3), faces)

            index += 1
    finally:
        cap.release()


#: Fraction of sampled frames that must show 2+ separated faces before a clip
#: is treated as a two-person scene. A momentary second face (someone walking
#: through frame) should not flip the whole clip into split-screen.
DUAL_SPEAKER_THRESHOLD = 0.6
#: Two faces closer than this (fraction of frame width) are treated as one
#: person's face detected twice, not two distinct speakers.
DUAL_MIN_SEPARATION = 0.15


@dataclass
class DualTrackResult:
    """Independent crop paths for a two-speaker split-screen layout."""

    left: list[TrackPoint]
    right: list[TrackPoint]


def track_two_speakers(
    video_path: str | Path,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
    sample_fps: float = SAMPLE_FPS,
) -> Optional[DualTrackResult]:
    """
    Detect a stable two-person scene and return one crop path per speaker.

    Returns None for anything that is not clearly and consistently a
    two-speaker shot — single speaker, no faces, or an incidental second face
    passing through frame all fall back to the normal single-crop path.
    """
    if not is_available():
        return None

    path = Path(video_path)
    if not path.exists():
        return None

    samples: list[tuple[float, list[dict]]] = []
    for outcome in _scan_faces(path, start_time, end_time, sample_fps):
        if outcome is None:
            return None
        samples.append(outcome)

    if not samples:
        return None

    def _well_separated(faces: list[dict]) -> Optional[tuple[dict, dict]]:
        if len(faces) < 2:
            return None
        by_area = sorted(faces, key=lambda f: f["area"], reverse=True)[:2]
        a, b = by_area
        if abs(a["cx"] - b["cx"]) < DUAL_MIN_SEPARATION:
            return None
        return (a, b) if a["cx"] <= b["cx"] else (b, a)

    dual_samples = sum(1 for _, faces in samples if _well_separated(faces))
    if dual_samples / len(samples) < DUAL_SPEAKER_THRESHOLD:
        return None  # not consistently a two-person scene

    # Assign each frame's two faces to a stable left/right identity by
    # nearest-previous-position, the same principle _choose_face uses for one
    # face, applied independently to each side.
    left_raw: list[TrackPoint] = []
    right_raw: list[TrackPoint] = []
    prev_left: Optional[float] = None
    prev_right: Optional[float] = None

    for t, faces in samples:
        pair = _well_separated(faces)
        if pair is None:
            continue
        a, b = pair  # a.cx <= b.cx by construction

        # Keep whichever assignment is more consistent with last frame, rather
        # than always trusting raw left/right position — otherwise two people
        # briefly crossing would swap which track represents which person.
        if prev_left is not None and prev_right is not None:
            straight = abs(a["cx"] - prev_left) + abs(b["cx"] - prev_right)
            swapped = abs(a["cx"] - prev_right) + abs(b["cx"] - prev_left)
            if swapped < straight:
                a, b = b, a

        left_raw.append(TrackPoint(time=t, center_x=a["cx"], center_y=a["cy"],
                                    face_count=len(faces), confidence=a["score"]))
        right_raw.append(TrackPoint(time=t, center_x=b["cx"], center_y=b["cy"],
                                     face_count=len(faces), confidence=b["score"]))
        prev_left, prev_right = a["cx"], b["cx"]

    if not left_raw or not right_raw:
        return None

    logger.info(
        f"Two-speaker scene detected in {path.name} "
        f"({dual_samples}/{len(samples)} samples), building split-screen crop"
    )
    return DualTrackResult(left=_smooth(left_raw), right=_smooth(right_raw))


def _choose_face(faces: list[dict], previous_center: Optional[float]) -> dict:
    """
    Pick which face the crop should follow.

    Without audio-visual speaker detection, the largest face is the best cheap
    proxy for "who is the subject". Hysteresis keeps the crop on the current
    subject unless a different face is clearly more prominent.
    """
    largest = max(faces, key=lambda f: f["area"])
    if previous_center is None or len(faces) == 1:
        return largest

    # Stay with whoever we were following if they are still present.
    nearest = min(faces, key=lambda f: abs(f["cx"] - previous_center))
    if abs(nearest["cx"] - previous_center) > SWITCH_HYSTERESIS:
        return largest

    # Only switch if the other face is meaningfully bigger.
    if largest is not nearest and largest["area"] > nearest["area"] * 1.4:
        return largest
    return nearest


def _smooth(points: list[TrackPoint]) -> list[TrackPoint]:
    """Moving average over the crop centre, so the frame glides instead of snapping."""
    if len(points) <= 2:
        return points

    half = max(1, SMOOTHING_WINDOW // 2)
    out: list[TrackPoint] = []

    for i, p in enumerate(points):
        lo = max(0, i - half)
        hi = min(len(points), i + half + 1)
        window = points[lo:hi]
        out.append(TrackPoint(
            time=p.time,
            center_x=round(sum(w.center_x for w in window) / len(window), 4),
            center_y=round(sum(w.center_y for w in window) / len(window), 4),
            face_count=p.face_count,
            confidence=p.confidence,
        ))

    return out


def build_crop_x_expression(
    points: list[TrackPoint],
    clip_start: float,
    max_points: int = 24,
) -> str:
    """
    Turn a crop path into an ffmpeg `crop` x expression.

    The result is relative to `in_w`/`out_w`, so it stays correct whatever the
    source resolution is. Times are rebased to the clip, because ffmpeg's `t`
    starts at 0 after seeking.

    Produces a piecewise-linear ramp between keyframes; ffmpeg evaluates it per
    frame, which is what makes the motion continuous rather than stepped.
    """
    if not points:
        return "(in_w-out_w)/2"

    kf = _thin(points, max_points)
    # Offset so the face sits in the middle of the crop window, then clamp to
    # the valid range instead of letting the window run off the frame edge.
    def offset(p: TrackPoint) -> str:
        return f"clip(in_w*{p.center_x:.4f}-out_w/2,0,in_w-out_w)"

    if len(kf) == 1:
        return offset(kf[0])

    expr = offset(kf[-1])
    for i in range(len(kf) - 2, -1, -1):
        a, b = kf[i], kf[i + 1]
        t0 = max(0.0, a.time - clip_start)
        t1 = max(t0 + 0.001, b.time - clip_start)
        ramp = (
            f"({offset(a)}+({offset(b)}-{offset(a)})*(t-{t0:.3f})/{t1 - t0:.3f})"
        )
        expr = f"if(lt(t,{t1:.3f}),{ramp},{expr})"

    return expr


def build_split_screen_filter_complex(
    result: "DualTrackResult",
    clip_start: float,
    target_width: int,
    target_height: int,
) -> str:
    """
    Build a `-filter_complex` graph stacking two speaker-tracked crops.

    Each half reuses the exact same scale-then-crop-then-track logic as the
    single-speaker path (`build_crop_x_expression`), so a person's framing
    looks identical whether they end up alone in frame or sharing a stacked
    layout — only a final downscale to half height and a vstack are added.
    Produces a single labeled output `[vout]`; the caller still needs to map
    audio separately, since filter_complex does not carry audio through.
    """
    half_h = target_height // 2
    left_expr = build_crop_x_expression(result.left, clip_start)
    right_expr = build_crop_x_expression(result.right, clip_start)

    return (
        f"[0:v]split=2[sstop][ssbot];"
        f"[sstop]scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
        f"crop={target_width}:{target_height}:x='{left_expr}':y=0,"
        f"scale={target_width}:{half_h}[sstopc];"
        f"[ssbot]scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
        f"crop={target_width}:{target_height}:x='{right_expr}':y=0,"
        f"scale={target_width}:{half_h}[ssbotc];"
        f"[sstopc][ssbotc]vstack=inputs=2[vout]"
    )


def _thin(points: list[TrackPoint], limit: int) -> list[TrackPoint]:
    """
    Reduce keyframes so the filter string stays manageable.

    A very long expression slows ffmpeg's per-frame evaluation and can exceed
    command-line limits, and the crop path is smooth enough that dropping
    intermediate points is visually free.
    """
    if len(points) <= limit:
        return points
    stride = len(points) / limit
    thinned = [points[int(i * stride)] for i in range(limit)]
    if thinned[-1].time != points[-1].time:
        thinned[-1] = points[-1]
    return thinned
