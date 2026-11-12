"""End-to-end: two separate processes call each other over the machine's LAN interface.

Each process runs the real signaling server or client, WebRTC negotiation (DTLS-SRTP,
Opus) and the peer session. Only the sound card is replaced by a generated tone.
"""

import json
import queue
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from app.core.room import detect_lan_ip

ROOT = Path(__file__).resolve().parents[1]
PEER = ROOT / "tests" / "peer_process.py"


def _free_port(ip: str) -> int:
    with socket.socket() as s:
        s.bind((ip, 0))
        return s.getsockname()[1]


def _reader(proc, lines: queue.Queue) -> None:
    for line in proc.stdout:
        lines.put(line.rstrip("\n"))
    lines.put(None)


def _result(lines: queue.Queue, timeout: float) -> dict:
    while True:
        line = lines.get(timeout=timeout)
        if line is None:
            raise AssertionError("process exited without a result")
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT "):])


@pytest.mark.skipif(detect_lan_ip() == "127.0.0.1", reason="needs a LAN interface")
def test_two_processes_establish_call_and_exchange_audio():
    ip = detect_lan_ip()
    port = _free_port(ip)
    host = subprocess.Popen(
        [sys.executable, str(PEER), "host", "--bind", ip, "--port", str(port), "--seconds", "4", "--freq", "300"],
        cwd=ROOT, stdout=subprocess.PIPE, text=True,
    )
    host_lines: queue.Queue = queue.Queue()
    threading.Thread(target=_reader, args=(host, host_lines), daemon=True).start()
    try:
        code = None
        while code is None:
            line = host_lines.get(timeout=30)
            assert line is not None, "host exited early"
            if line.startswith("ROOM "):
                code = line.split()[1]

        client = subprocess.run(
            [sys.executable, str(PEER), "client", "--ip", ip, "--port", str(port),
             "--code", code, "--seconds", "4", "--freq", "700"],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        client_result = next(
            json.loads(line[7:]) for line in client.stdout.splitlines() if line.startswith("RESULT ")
        )
        host_result = _result(host_lines, timeout=60)
    finally:
        host.kill()

    print("host:", host_result)
    print("client:", client_result)
    assert host_result["connected"] and client_result["connected"]
    # The host sends 300 Hz and the client sends 700 Hz, so each side must hear the
    # other's frequency (not its own, and not silence).
    assert host_result["frames"] > 50 and client_result["frames"] > 50
    assert abs(host_result["hz"] - 700) < 15, host_result
    assert abs(client_result["hz"] - 300) < 15, client_result
    assert host_result["quality"] in ("Good", "Fair", "Poor", "Measuring")
