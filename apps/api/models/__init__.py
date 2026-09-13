"""ClipForge AI — ORM Models package."""

from apps.api.models.user import User
from apps.api.models.project import Project, Source, RightsRecord
from apps.api.models.video import Video, VideoMetadata
from apps.api.models.transcript import Transcript, TranscriptSegment, Speaker
from apps.api.models.analysis import Scene, Topic
from apps.api.models.clip import (
    CandidateClip,
    ClipScore,
    ClipVariant,
    Edit,
    Render,
    QAResult,
    ClipMetadata,
    Export,
)
from apps.api.models.job import ProcessingJob, AgentRun
from apps.api.models.settings import UserSettings, CaptionTemplate, PlatformPreset

__all__ = [
    "User",
    "Project", "Source", "RightsRecord",
    "Video", "VideoMetadata",
    "Transcript", "TranscriptSegment", "Speaker",
    "Scene", "Topic",
    "CandidateClip", "ClipScore", "ClipVariant",
    "Edit", "Render", "QAResult", "ClipMetadata", "Export",
    "ProcessingJob", "AgentRun",
    "UserSettings", "CaptionTemplate", "PlatformPreset",
]
