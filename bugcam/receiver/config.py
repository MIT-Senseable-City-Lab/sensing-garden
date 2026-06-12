"""Configuration defaults for the DOT receiver."""

import os

from ..app_config import get_bundled_config

_RECEIVER_DEFAULTS = get_bundled_config().get("receiver", {})

RECEIVER_DEFAULT_PORT = int(os.environ.get("BUGCAM_RECEIVER_PORT", str(_RECEIVER_DEFAULTS.get("port", 5001))))
RECEIVER_DEFAULT_HOST = os.environ.get("BUGCAM_RECEIVER_HOST", str(_RECEIVER_DEFAULTS.get("host", "0.0.0.0")))

FINALIZATION_DELAY = 60.0
STALE_AGE = 600
CHECK_INTERVAL = 2.0
