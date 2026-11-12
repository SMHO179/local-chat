"""One side of a real call, run as its own process (driven by test_two_processes.py).

Host:   python tests/peer_process.py host   --bind <LAN IP> --port <p> --seconds 4
Client: python tests/peer_process.py client --ip <host IP> --port <p> --code <CODE> --seconds 4

Uses the real signaling server, WebRTC (DTLS-SRTP, Opus) and PeerSession; only the sound card
is replaced by a tone generator (FakeAudio). Prints one JSON line prefixed with RESULT.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.config import CONNECT_TIMEOUT_S, JOIN_TIMEOUT_S  # noqa: E402
from app.core.room import generate_room_code, sign_sdp, verify_sdp  # noqa: E402
from app.networking.peer import PeerSession  # noqa: E402
from app.networking.signaling import JoinReply, SignalingServer, send_join  # noqa: E402
from fakes import FakeAudio  # noqa: E402


async def run_host(args) -> dict:
    audio = FakeAudio(freq=args.freq)
    code = generate_room_code()
    holder: dict = {}
    qualities: list = []

    async def on_join(request):
        peer = PeerSession(audio, on_quality=qualities.append, on_state=lambda s: None)
        holder["peer"] = peer
        answer = await peer.accept_offer(request.sdp)
        return JoinReply(sdp=answer, mac=sign_sdp(code, "answer", answer), host_name="host-process")

    server = SignalingServer(args.bind, args.port, code, on_join, "host-process")
    await server.start()
    print(f"ROOM {code}", flush=True)
    try:
        while "peer" not in holder:
            await asyncio.sleep(0.05)
        connected = await holder["peer"].wait_connected(CONNECT_TIMEOUT_S)
        await asyncio.sleep(args.seconds)
        await holder["peer"].close()
    finally:
        await server.stop()
    return {"role": "host", "connected": connected, "rms": audio.received_rms(), "hz": audio.dominant_hz(),
            "frames": len(audio.received), "quality": qualities[-1].label if qualities else None}


async def run_client(args) -> dict:
    audio = FakeAudio(freq=args.freq)
    qualities: list = []
    peer = PeerSession(audio, on_quality=qualities.append, on_state=lambda s: None)
    try:
        offer = await peer.create_offer()
        reply = await send_join(args.ip, args.port, args.code, offer,
                                sign_sdp(args.code, "offer", offer), "client-process", JOIN_TIMEOUT_S)
        if not verify_sdp(args.code, "answer", reply.sdp, reply.mac):
            raise SystemExit("answer failed verification")
        await peer.apply_answer(reply.sdp)
        connected = await peer.wait_connected(CONNECT_TIMEOUT_S)
        await asyncio.sleep(args.seconds)
        await peer.close()
    finally:
        pass
    return {"role": "client", "connected": connected, "rms": audio.received_rms(), "hz": audio.dominant_hz(),
            "frames": len(audio.received), "quality": qualities[-1].label if qualities else None}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["host", "client"])
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--ip", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--code", default="")
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--freq", type=float, required=True, help="tone frequency this side sends")
    args = parser.parse_args()
    result = asyncio.run(run_host(args) if args.role == "host" else run_client(args))
    print("RESULT " + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
