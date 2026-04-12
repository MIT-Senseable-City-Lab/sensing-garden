"""
Classification queue manager for interleaving FLIK and DOT classification.

Provides a disk-based FIFO queue that persists across crashes and allows
fair scheduling of classification tasks from both FLIK detection and DOT uploads.
"""

import json
import logging
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class QueueEntry:
    """Represents a track queued for classification."""
    entry_type: str                          # "flik" or "dot"
    source_device: str
    date: str
    time: Optional[str]
    track_id: str
    track_dir: str                           # Path to crops directory
    labels_path: Optional[str] = None        # Path to labels JSON (for DOT)
    background_path: Optional[str] = None    # Path to background image (for DOT composite)
    num_crops: int = 0
    output_dir: str = ""                     # Where to write final results
    queued_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> "QueueEntry":
        data = json.loads(json_str)
        return cls(**data)


class ClassificationQueue:
    """
    Disk-based FIFO queue for classification tasks.
    
    Queues tracks from both FLIK detection and DOT uploads for
    fair interleaved processing. Files are written to disk so
    pending classifications survive crashes.
    """
    
    def __init__(self, pending_dir: Path):
        self.pending_dir = Path(pending_dir)
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
    
    def enqueue(
        self,
        entry_type: str,
        source_device: str,
        date: str,
        track_id: str,
        track_dir: Path,
        output_dir: Path,
        time: Optional[str] = None,
        labels_path: Optional[Path] = None,
        background_path: Optional[Path] = None,
        num_crops: int = 0,
    ) -> Path:
        """Queue a track for classification."""
        entry = QueueEntry(
            entry_type=entry_type,
            source_device=source_device,
            date=date,
            time=time,
            track_id=track_id,
            track_dir=str(track_dir),
            labels_path=str(labels_path) if labels_path else None,
            background_path=str(background_path) if background_path else None,
            num_crops=num_crops,
            output_dir=str(output_dir),
        )
        
        with self._lock:
            # Use timestamp in filename for uniqueness and FIFO ordering
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{source_device}_{date}_{timestamp}_{track_id}.json"
            filepath = self.pending_dir / filename
            filepath.write_text(entry.to_json())
            logger.debug(f"Queued for classification: {filepath.name}")
        
        return filepath
    
    def get_next(self) -> Optional[tuple[Path, QueueEntry]]:
        """Get oldest pending entry (FIFO by mtime)."""
        with self._lock:
            files = sorted(
                self.pending_dir.glob("*.json"),
                key=lambda p: p.stat().st_mtime
            )
            
            if not files:
                return None
            
            filepath = files[0]
            try:
                entry = QueueEntry.from_json(filepath.read_text())
                logger.debug(f"Retrieved from queue: {filepath.name}")
                return filepath, entry
            except Exception as e:
                logger.error(f"Failed to read queue entry {filepath}: {e}")
                # Move corrupted file aside
                corrupted = filepath.with_suffix(".corrupted")
                filepath.rename(corrupted)
                logger.warning(f"Moved corrupted file to {corrupted}")
                return None
    
    def remove(self, filepath: Path) -> None:
        """Remove processed entry from queue."""
        with self._lock:
            if filepath.exists():
                filepath.unlink()
                logger.debug(f"Removed from queue: {filepath.name}")
    
    def count(self) -> int:
        """Count pending entries."""
        return len(list(self.pending_dir.glob("*.json")))
    
    def recover(self) -> int:
        """Recover pending entries after crash. Returns count."""
        count = self.count()
        if count > 0:
            logger.info(f"Recovered {count} pending classification(s) from {self.pending_dir}")
        return count
    
    def get_pending_entries(self) -> list[tuple[Path, QueueEntry]]:
        """Get all pending entries sorted by mtime (for debugging/inspection)."""
        entries = []
        with self._lock:
            files = sorted(
                self.pending_dir.glob("*.json"),
                key=lambda p: p.stat().st_mtime
            )
            for filepath in files:
                try:
                    entry = QueueEntry.from_json(filepath.read_text())
                    entries.append((filepath, entry))
                except Exception:
                    pass
        return entries


def get_pending_dir() -> Path:
    """Get the pending classification queue directory."""
    from bugcam.config import get_state_dir
    return get_state_dir() / "pending"