"""Room codes, host address checks and signaling message authentication."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
import socket

from app.core.config import ROOM_ALPHABET, ROOM_CODE_LENGTH

_CODE_RE = re.compile(f"[{ROOM_ALPHABET}]{{{ROOM_CODE_LENGTH}}}")


def generate_room_code() -> str:
    return "".join(secrets.choice(ROOM_ALPHABET) for _ in range(ROOM_CODE_LENGTH))


def normalize_room_code(raw: str) -> str:
    """Return the canonical room code or raise ValueError."""
    code = raw.strip().upper().replace(" ", "").replace("-", "")
    if not _CODE_RE.fullmatch(code):
        raise ValueError("Room code must be 6 letters or digits, e.g. K7M2QF.")
    return code


def parse_host_ip(raw: str) -> str:
    """Return the host IPv4 address if it is a local (private, link-local or loopback) address."""
    text = raw.strip()
    try:
        address = ipaddress.IPv4Address(text)
    except ValueError:
        raise ValueError("Enter the host's IPv4 address, e.g. 192.168.137.1.") from None
    if not (address.is_private or address.is_link_local or address.is_loopback):
        raise ValueError("The host address must be on your local network.")
    return str(address)


def detect_lan_ip() -> str:
    """Return the IPv4 address of the interface that faces the local network.

    No packets are sent: connecting a UDP socket only selects the outgoing route.
    Falls back to 127.0.0.1 when no network interface is available.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def sign_sdp(code: str, role: str, sdp: str) -> str:
    """Authenticate an SDP blob with the room code, so the signaling path cannot be tampered with.

    The SDP carries the DTLS certificate fingerprint; signing it means an attacker on the
    LAN who does not know the room code cannot substitute their own peer.
    """
    message = f"{role}\n{sdp}".encode("utf-8")
    return hmac.new(code.encode("ascii"), message, hashlib.sha256).hexdigest()


def verify_sdp(code: str, role: str, sdp: str, mac: object) -> bool:
    if not isinstance(mac, str) or not mac.isascii():
        return False
    return hmac.compare_digest(sign_sdp(code, role, sdp), mac)
