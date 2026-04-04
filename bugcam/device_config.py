"""Typed access to persisted BugCam device config."""
from __future__ import annotations

from dataclasses import dataclass

from .config import DEFAULT_API_URL, DEFAULT_S3_BUCKET, get_default_dot_ids, get_default_flick_id, load_config, parse_dot_ids


@dataclass(frozen=True)
class DeviceConfig:
    api_url: str = DEFAULT_API_URL
    api_key: str = ""
    device_id: str = ""
    device_name: str = ""
    s3_bucket: str = DEFAULT_S3_BUCKET
    flick_id: str = ""
    dot_ids: list[str] | None = None


def load_device_config() -> DeviceConfig:
    """Load persisted device config with defaults applied."""
    config = load_config()
    flick_id = str(config.get("flick_id") or get_default_flick_id())
    dot_ids = parse_dot_ids(config.get("dot_ids")) or get_default_dot_ids()
    return DeviceConfig(
        api_url=str(config.get("api_url") or DEFAULT_API_URL),
        api_key=str(config.get("api_key") or ""),
        device_id=str(config.get("device_id") or ""),
        device_name=str(config.get("device_name") or ""),
        s3_bucket=str(config.get("s3_bucket") or DEFAULT_S3_BUCKET),
        flick_id=flick_id,
        dot_ids=dot_ids,
    )


def resolve_flick_id(flick_id: str | None) -> str:
    """Resolve flick_id with CLI override first, then config, then default."""
    if flick_id:
        return flick_id
    return load_device_config().flick_id or get_default_flick_id()
