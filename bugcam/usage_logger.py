"""Usage logging for API endpoint monitoring."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from bugcam.config import get_state_dir

logger = logging.getLogger(__name__)

USAGE_LOG_FILENAME = "usage_log.jsonl"


def log_usage(
    operation: str,
    endpoint: str,
    bytes_sent: int,
    success: bool,
    s3_key: str | None = None,
    error: str | None = None,
    duration_ms: float | None = None,
) -> None:
    entry: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "endpoint": endpoint,
        "bytes_sent": bytes_sent,
        "success": success,
    }
    if s3_key is not None:
        entry["s3_key"] = s3_key
    if error is not None:
        entry["error"] = error
    if duration_ms is not None:
        entry["duration_ms"] = round(duration_ms, 1)

    log_path = get_state_dir() / USAGE_LOG_FILENAME
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError as exc:
        logger.warning("Failed to write usage log: %s", exc)
