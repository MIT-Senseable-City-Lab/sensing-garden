"""Configuration defaults for the DOT receiver."""

import os

RECEIVER_DEFAULT_PORT = int(os.environ.get("BUGCAM_RECEIVER_PORT", "5001"))
RECEIVER_DEFAULT_HOST = os.environ.get("BUGCAM_RECEIVER_HOST", "0.0.0.0")

FINALIZATION_DELAY = 5.0
STALE_AGE = 600
CHECK_INTERVAL = 2.0
