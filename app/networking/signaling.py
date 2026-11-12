"""Minimal local HTTP signaling for a single two-person call.

Hosts expose a single join endpoint; a client posts its SDP offer and receives the
host's SDP answer. The room code and SDP authentication are verified by the caller
(call_controller/room), but the signaling layer enforces the basic protocol shape
and guards against obvious misuse on the LAN.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

import aiohttp
from aiohttp import web

from app.core.constants import MAX_HTTP_BODY, SIGNALING_PATH

log = logging.getLogger(__name__)


class SignalingError(RuntimeError):
    """User-facing signaling failure."""

    pass


@dataclass(frozen=True, slots=True)
class JoinRequest:
    sdp: str
    peer_name: str


@dataclass(frozen=True, slots=True)
class JoinReply:
    sdp: str
    mac: str
    host_name: str


JoinHandler = Callable[[JoinRequest], Awaitable[JoinReply]]


class SignalingServer:
    """HTTP server that accepts at most one active join at a time."""

    def __init__(
        self,
        bind_ip: str,
        port: int,
        code: str,
        handler: JoinHandler,
        host_name: str,
        on_lockout: Callable[[], None] | None = None,
    ) -> None:
        self._bind_ip = bind_ip
        self._port = port
        self._code = code
        self._handler = handler
        self._host_name = host_name
        self._on_lockout = on_lockout
        self._runner: web.AppRunner | None = None
        self._busy = False

    async def start(self) -> None:
        app = web.Application(client_max_size=MAX_HTTP_BODY)
        app.router.add_post(SIGNALING_PATH, self._handle_join)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, self._bind_ip, self._port)
        try:
            await site.start()
        except OSError as exc:
            await runner.cleanup()
            raise SignalingError(
                f"Could not start listening on {self._bind_ip}:{self._port}: {exc}"
            ) from exc
        self._runner = runner
        log.info("signaling listening on %s:%s", self._bind_ip, self._port)

    async def stop(self) -> None:
        runner, self._runner = self._runner, None
        if runner is not None:
            try:
                await runner.cleanup()
            except Exception:
                log.debug("signaling cleanup failed", exc_info=True)

    def release_slot(self) -> None:
        """Allow another peer to join after a disconnect."""
        self._busy = False

    async def _handle_join(self, request: web.Request) -> web.Response:
        if self._busy:
            return web.json_response({"error": "busy"}, status=409)
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid request"}, status=400)
        if not isinstance(payload, dict):
            return web.json_response({"error": "invalid request"}, status=400)

        code = payload.get("code")
        sdp = payload.get("sdp")
        mac = payload.get("mac")
        peer_name = payload.get("name")
        if not isinstance(code, str) or not isinstance(sdp, str) or not isinstance(mac, str):
            return web.json_response({"error": "invalid request"}, status=400)
        if code != self._code:
            return web.json_response({"error": "wrong room code"}, status=403)
        if not isinstance(peer_name, str) or not peer_name.strip():
            peer_name = "Guest"

        self._busy = True
        try:
            reply = await self._handler(
                JoinRequest(sdp=sdp, peer_name=peer_name.strip()[:64])
            )
        except SignalingError as exc:
            self._busy = False
            return web.json_response({"error": str(exc)}, status=400)
        except Exception:
            self._busy = False
            log.exception("join handler failed")
            return web.json_response({"error": "host could not accept the call"}, status=500)

        return web.json_response(
            {"sdp": reply.sdp, "mac": reply.mac, "host_name": reply.host_name}
        )


async def send_join(
    host_ip: str,
    port: int,
    code: str,
    offer_sdp: str,
    mac: str,
    client_name: str,
    timeout: float,
) -> JoinReply:
    """Send an offer to the host and return its answer."""
    url = f"http://{host_ip}:{port}{SIGNALING_PATH}"
    payload = {"code": code, "sdp": offer_sdp, "mac": mac, "name": client_name}
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.post(url, json=payload) as resp:
                try:
                    data = await resp.json()
                except Exception:
                    data = {}
                if resp.status != 200:
                    message = data.get("error") if isinstance(data, dict) else None
                    if resp.status == 403:
                        raise SignalingError("The room code was not accepted.")
                    if resp.status == 409:
                        raise SignalingError("The host is already in a call.")
                    if isinstance(message, str) and message:
                        raise SignalingError(message)
                    raise SignalingError(f"The host rejected the request ({resp.status}).")
                if not isinstance(data, dict):
                    raise SignalingError("The host sent an invalid response.")
                sdp = data.get("sdp")
                reply_mac = data.get("mac")
                host_name = data.get("host_name")
                if not isinstance(sdp, str) or not isinstance(reply_mac, str):
                    raise SignalingError("The host sent an invalid response.")
                if not isinstance(host_name, str) or not host_name.strip():
                    host_name = "Host"
                return JoinReply(sdp=sdp, mac=reply_mac, host_name=host_name.strip()[:64])
    except asyncio.TimeoutError as exc:
        raise SignalingError("The host did not answer in time.") from exc
    except aiohttp.ClientError as exc:
        raise SignalingError(f"Could not reach the host at {host_ip}:{port}.") from exc
    except OSError as exc:
        raise SignalingError(f"Could not reach the host at {host_ip}:{port}.") from exc
