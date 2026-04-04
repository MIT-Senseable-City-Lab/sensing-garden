"""
Video capture module - continuous recording with gapless chunk saving.

Provides:
    VideoRecorder: Continuous recorder that saves fixed-duration chunks
"""

from .recorder import VideoRecorder

__all__ = ["VideoRecorder"]
