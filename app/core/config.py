"""Fixed protocol and tuning constants."""

APP_NAME = "local-chat"

# TCP port for the one-shot offer/answer exchange on the LAN.
SIGNAL_PORT = 47823

# Audio format: Opus runs at 48 kHz; 20 ms frames are its native packet size.
SAMPLE_RATE = 48_000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000       # 960 samples per frame
MIC_BLOCK_SAMPLES = SAMPLE_RATE // 100               # 10 ms capture callbacks
CAPTURE_MAX_SAMPLES = SAMPLE_RATE // 10              # keep at most 100 ms of mic backlog
PLAYBACK_MAX_SAMPLES = SAMPLE_RATE * 120 // 1000     # keep at most 120 ms of playout backlog

# Room codes: 6 characters without look-alikes (0/O, 1/I).
ROOM_CODE_LENGTH = 6
ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# Signaling limits.
MAX_FAILED_JOINS = 20          # after this many bad attempts the room locks
FAILED_JOIN_DELAY_S = 1.0      # slows down each bad attempt
JOIN_TIMEOUT_S = 10.0
CONNECT_TIMEOUT_S = 30.0

STATS_INTERVAL_S = 2.0
