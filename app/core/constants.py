"""Shared constants for local-chat."""

APP_NAME = "local-chat"
APP_VERSION = "0.1.0"

# Signaling
SIGNALING_PORT = 47823
SIGNALING_PATH = "/join"
MAX_HTTP_BODY = 256 * 1024  # 256 KiB, plenty for SDP offers/answers
