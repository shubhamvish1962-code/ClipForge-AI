"""
ClipForge AI — Centralized Storage Service.
Provides an OS-agnostic, safe abstraction for file uploads, processed video clips,
temporary files, and validation.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple

import shortuuid
from apps.api.core.config import get_settings

logger = logging.getLogger("clipforge.storage")


class StorageService:
    """Central storage service managing uploads, processed clips, and temp scratch files."""

    def __init__(self):
        self.settings = get_settings()
        self.base_dir = self.settings.storage_path
        self.uploads_dir = self.settings.uploads_path
        self.processed_dir = self.settings.processed_path
        self.temp_dir = self.base_dir / "temp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def save_upload(
        self,
        content: bytes,
        project_id: str,
        original_filename: str = "video.mp4",
    ) -> Tuple[Path, int]:
        """
        Saves uploaded file content into a project-scoped directory safely.
        Returns (saved_path, byte_count).
        """
        project_uploads = self.uploads_dir / project_id
        project_uploads.mkdir(parents=True, exist_ok=True)

        clean_name = Path(original_filename).name.replace(" ", "_")
        safe_filename = f"{shortuuid.uuid()}_{clean_name}"
        destination = project_uploads / safe_filename

        with open(destination, "wb") as f:
            f.write(content)

        file_size = destination.stat().st_size
        logger.info(f"Saved upload to {destination} ({file_size} bytes)")
        return destination, file_size

    def get_file(self, file_path: str | Path) -> Optional[Path]:
        """
        Resolves a file path, ensuring it exists and is a valid file.
        """
        if not file_path:
            return None
        p = Path(file_path)
        if p.is_file() and p.stat().st_size > 0:
            return p
        # Check relative to base storage
        rel = self.base_dir / file_path
        if rel.is_file() and rel.stat().st_size > 0:
            return rel
        return None

    def exists(self, file_path: str | Path) -> bool:
        """Check if file exists and has size > 0."""
        resolved = self.get_file(file_path)
        return resolved is not None

    def delete(self, file_path: str | Path) -> bool:
        """Deletes a file safely."""
        p = self.get_file(file_path)
        if p and p.exists():
            try:
                p.unlink()
                logger.info(f"Deleted file {p}")
                return True
            except Exception as e:
                logger.warning(f"Failed to delete {p}: {e}")
        return False

    def validate_video_file(self, file_path: str | Path) -> Tuple[bool, str, int]:
        """
        Validates that a video file exists, is non-zero, and has a supported extension.
        Returns (is_valid, reason, size_bytes).
        """
        resolved = self.get_file(file_path)
        if not resolved:
            return False, "File does not exist or is 0 bytes", 0

        size = resolved.stat().st_size
        max_bytes = self.settings.max_upload_size_mb * 1024 * 1024
        if size > max_bytes:
            return False, f"File size ({size / 1e6:.1f} MB) exceeds limit ({self.settings.max_upload_size_mb} MB)", size

        valid_extensions = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
        if resolved.suffix.lower() not in valid_extensions:
            return False, f"Unsupported file extension {resolved.suffix}. Allowed: {', '.join(valid_extensions)}", size

        return True, "Valid video file", size

    def cleanup_temp(self, pattern: str = "*") -> int:
        """Clean up temporary files matching pattern."""
        cleaned = 0
        for f in self.temp_dir.glob(pattern):
            if f.is_file():
                try:
                    f.unlink()
                    cleaned += 1
                except Exception:
                    pass
        return cleaned


# Global Singleton
storage_service = StorageService()
