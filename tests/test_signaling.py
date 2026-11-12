import asyncio
import socket

import pytest

from app.core.room import sign_sdp
from app.networking.peer import Quality, classify_quality, quality_from_report
from app.networking.signaling import JoinReply, SignalingError, SignalingServer, send_join


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _answer_handler(request):
    return JoinReply(sdp="answer-sdp", mac=sign_sdp("K7M2QF", "answer", "answer-sdp"), host_name="host-pc")


def _server(port, handler=_answer_handler, lockout=None, max_failed=20):
    return SignalingServer(
        "127.0.0.1", port, "K7M2QF", handler, "host-pc",
        on_lockout=lockout, max_failed_joins=max_failed, failed_join_delay=0.0,
    )


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_valid_join_returns_answer():
    async def scenario():
        port = _free_port()
        server = _server(port)
        await server.start()
        try:
            mac = sign_sdp("K7M2QF", "offer", "offer-sdp")
            reply = await send_join("127.0.0.1", port, "K7M2QF", "offer-sdp", mac, "laptop", timeout=5)
            return reply
        finally:
            await server.stop()

    reply = run(scenario())
    assert reply.sdp == "answer-sdp"
    assert reply.host_name == "host-pc"


def test_wrong_code_is_rejected():
    async def scenario():
        port = _free_port()
        server = _server(port)
        await server.start()
        try:
            mac = sign_sdp("ZZZ222", "offer", "offer-sdp")
            with pytest.raises(SignalingError, match="Wrong room code"):
                await send_join("127.0.0.1", port, "ZZZ222", "offer-sdp", mac, "x", timeout=5)
        finally:
            await server.stop()

    run(scenario())


def test_tampered_sdp_is_rejected_even_with_right_code():
    async def scenario():
        port = _free_port()
        server = _server(port)
        await server.start()
        try:
            mac = sign_sdp("K7M2QF", "offer", "offer-sdp")
            with pytest.raises(SignalingError):
                await send_join("127.0.0.1", port, "K7M2QF", "offer-sdp-tampered", mac, "x", timeout=5)
        finally:
            await server.stop()

    run(scenario())


def test_second_peer_is_refused_while_room_is_claimed():
    async def scenario():
        port = _free_port()
        server = _server(port)
        await server.start()
        try:
            mac = sign_sdp("K7M2QF", "offer", "offer-sdp")
            await send_join("127.0.0.1", port, "K7M2QF", "offer-sdp", mac, "first", timeout=5)
            with pytest.raises(SignalingError, match="already has a connection"):
                await send_join("127.0.0.1", port, "K7M2QF", "offer-sdp", mac, "second", timeout=5)
            server.release_slot()
            await send_join("127.0.0.1", port, "K7M2QF", "offer-sdp", mac, "third", timeout=5)
        finally:
            await server.stop()

    run(scenario())


def test_room_locks_after_too_many_failed_attempts():
    locked = []

    async def scenario():
        port = _free_port()
        server = _server(port, lockout=lambda: locked.append(True), max_failed=3)
        await server.start()
        try:
            for _ in range(3):
                with pytest.raises(SignalingError, match="Wrong room code"):
                    await send_join("127.0.0.1", port, "ZZZ222", "o", sign_sdp("ZZZ222", "offer", "o"), "x", 5)
            mac = sign_sdp("K7M2QF", "offer", "offer-sdp")
            with pytest.raises(SignalingError, match="locked"):
                await send_join("127.0.0.1", port, "K7M2QF", "offer-sdp", mac, "x", timeout=5)
        finally:
            await server.stop()

    run(scenario())
    assert locked == [True]


def test_unreachable_host_gives_clear_error():
    async def scenario():
        with pytest.raises(SignalingError, match="Cannot reach"):
            await send_join("127.0.0.1", _free_port(), "K7M2QF", "o", "m", "x", timeout=3)

    run(scenario())


def test_port_in_use_is_reported_not_crashed():
    async def scenario():
        with socket.socket() as blocker:
            blocker.bind(("127.0.0.1", 0))
            blocker.listen()
            port = blocker.getsockname()[1]
            server = _server(port)
            with pytest.raises(SignalingError, match="Could not listen"):
                await server.start()

    run(scenario())


def test_quality_classification_thresholds():
    assert classify_quality(40, 0.5) == "Good"
    assert classify_quality(200, 1) == "Fair"
    assert classify_quality(400, 0) == "Poor"
    assert classify_quality(40, 8) == "Poor"


class _Stat:
    def __init__(self, type_, **fields):
        self.type = type_
        self.__dict__.update(fields)


def test_quality_from_aiortc_style_report():
    report = {
        "outbound": _Stat("outbound-rtp"),
        "rin": _Stat("remote-inbound-rtp", roundTripTime=0.06, fractionLost=5),
    }
    quality = quality_from_report(report)
    assert quality.label == "Good"
    assert quality.rtt_ms == pytest.approx(60.0)
    assert quality.loss_pct == pytest.approx(5 / 256 * 100)


def test_quality_without_remote_stats_is_measuring():
    assert quality_from_report({}) == Quality("Measuring", None, None)
