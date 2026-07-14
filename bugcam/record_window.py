"""Local-time recording window evaluated in a configured IANA timezone.

Devices keep their system clocks (and all machine timestamps) in UTC; the
configured timezone exists so operators can express the recording window in
local wall time ("05:00-22:00") and have it track DST automatically.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, time as dtime, timezone, tzinfo
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Applied when a timezone is configured but no explicit window is set:
# comfortably covers summer daylight at the deployment sites while skipping
# the night hours, which the pipeline spends draining the processing backlog.
DEFAULT_RECORD_WINDOW = "05:00-22:00"

_WINDOW_RE = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


def resolve_zone(timezone_name: str | None) -> tzinfo:
    """Resolve an IANA timezone name, or the system-local zone when unset."""
    if not timezone_name:
        local = datetime.now(timezone.utc).astimezone().tzinfo
        return local if local is not None else timezone.utc
    try:
        return ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError(
            f"Unknown timezone {timezone_name!r}; use an IANA name like "
            "Europe/London, Europe/Amsterdam, or America/Toronto"
        ) from exc


class RecordingWindow:
    """Daily recording window in local wall time.

    ``start``/``end`` of ``None`` means always open. The start bound is
    inclusive and the end bound exclusive; ``start > end`` wraps past
    midnight (an overnight window).
    """

    def __init__(
        self,
        start: dtime | None,
        end: dtime | None,
        zone: tzinfo,
        zone_label: str,
    ) -> None:
        self.start = start
        self.end = end
        self.zone = zone
        self.zone_label = zone_label

    @property
    def always_open(self) -> bool:
        return self.start is None

    @classmethod
    def from_config(
        cls, window: str | None, timezone_name: str | None
    ) -> "RecordingWindow":
        """Build a window from config values.

        ``window`` accepts "HH:MM-HH:MM", "always", or None. With no explicit
        window, a configured timezone implies DEFAULT_RECORD_WINDOW and no
        timezone means record around the clock (the historical behavior).
        Raises ValueError on malformed input.
        """
        zone = resolve_zone(timezone_name)
        zone_label = timezone_name or f"system local ({zone})"

        if window is None or not str(window).strip():
            window = DEFAULT_RECORD_WINDOW if timezone_name else "always"
        window = str(window).strip()

        if window.lower() == "always":
            return cls(None, None, zone, zone_label)

        match = _WINDOW_RE.match(window)
        if not match:
            raise ValueError(
                f"Invalid record window {window!r}; expected 'HH:MM-HH:MM' or 'always'"
            )
        try:
            start = dtime(int(match.group(1)), int(match.group(2)))
            end = dtime(int(match.group(3)), int(match.group(4)))
        except ValueError as exc:
            raise ValueError(f"Invalid record window {window!r}: {exc}") from exc
        if start == end:
            raise ValueError(
                f"Invalid record window {window!r}: start and end are equal "
                "(use 'always' to record around the clock)"
            )
        if not timezone_name:
            logger.warning(
                "record_window %s set without a configured timezone; "
                "evaluating it in %s", window, zone_label,
            )
        return cls(start, end, zone, zone_label)

    def is_open(self, now: datetime | None = None) -> bool:
        """Whether recording should run at ``now`` (an aware datetime)."""
        if self.always_open:
            return True
        local = (now or datetime.now(timezone.utc)).astimezone(self.zone).time()
        wall = local.replace(second=0, microsecond=0, tzinfo=None)
        if self.start <= self.end:
            return self.start <= wall < self.end
        return wall >= self.start or wall < self.end

    def describe(self) -> str:
        if self.always_open:
            return f"always ({self.zone_label})"
        return (
            f"{self.start:%H:%M}-{self.end:%H:%M} {self.zone_label}"
        )


def video_stem_utc_iso(date_time: str) -> str | None:
    """ISO-8601 UTC timestamp for a compact YYYYMMDD_HHMMSS[_micros] video stem.

    The recorder stamps filenames in UTC, so the result carries an explicit
    +00:00 offset. Returns None when the stem doesn't parse.
    """
    stamp = _parse_video_stem(date_time)
    return stamp.isoformat() if stamp else None


def local_video_date(date_time: str, zone: tzinfo | None) -> str:
    """Local calendar date (YYYYMMDD) of a UTC video stem.

    Falls back to the stem's own date prefix when no zone is configured or
    the stem doesn't parse.
    """
    stamp = _parse_video_stem(date_time) if zone is not None else None
    if stamp is None:
        return date_time[:8]
    return stamp.astimezone(zone).strftime("%Y%m%d")


def _parse_video_stem(date_time: str) -> datetime | None:
    parts = date_time.split("_")
    if len(parts) < 2:
        return None
    try:
        return datetime.strptime(
            f"{parts[0]}_{parts[1]}", "%Y%m%d_%H%M%S"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
