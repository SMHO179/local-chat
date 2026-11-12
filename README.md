# local-chat

A native desktop app for a private one-to-one voice call between two computers on the same
local network (LAN, Wi-Fi or a mobile hotspot). Audio goes directly between the two
computers. No internet connection, accounts, cloud services or external servers are used.

Target platform: Windows 10/11. Python 3.12+.

## Installation (Windows, PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Install the same version on both computers.

## Making a call

1. **Host:** click **Create Call**. The call screen shows your address on the network and a
   six-character room code.
2. **Other computer:** click **Join Call**, enter the host's address and the room code, and
   click **Join Call** again.
3. When the connection is established, both screens show **Connected**.

Either side can click **Disconnect** to end the call. If the call drops, the host returns to
waiting so the other computer can rejoin. The joiner returns to the start screen.

### Network requirements

- Both computers must be on the same network, such as a shared Wi-Fi network or a Windows
  mobile hotspot. The hotspot configuration has not been tested.
- Windows Firewall will ask whether to allow Python on private networks the first time the
  app listens. Allow it. The signaling server uses TCP port **47823** on the host's LAN
  address. The audio connection uses UDP on ports chosen by the system.
- Set the network profile to **Private**. Public networks block incoming connections.

## Audio controls

- **Microphone / Speaker** selectors on the call screen. Changing a device during a call
  reopens it.
- **Mute / Unmute**.
- **Push-to-talk mode**: when enabled, the microphone is sent only while you hold
  **Hold to talk** or the Space bar. Push-to-talk works only while the app window has focus.
- **Level meters** for your microphone and the remote audio.
- **Connection quality** (Good / Fair / Poor) from WebRTC statistics: round-trip time and
  packet loss, updated every two seconds.

If the microphone cannot be opened, the call continues in listen-only mode. If the speaker
cannot be opened, the call continues in talk-only mode. The call screen shows the problem.

## Security

- Audio is encrypted with DTLS-SRTP, which aiortc negotiates for every WebRTC connection.
- The signaling server listens only on the host's LAN address. It is not reachable from the
  internet unless the router forwards the port.
- Room codes are six characters from a 32-character alphabet, generated with `secrets`.
- The offer and answer are authenticated with an HMAC keyed by the room code. The HMAC covers
  the DTLS certificate fingerprint, so a device on the LAN that does not know the code cannot
  substitute itself into the call.
- The host rejects a second peer while a call is active. After 20 wrong codes the room locks,
  and the host must create a new call.
- Audio is never recorded or written to disk.

Limitation: the signaling exchange itself is plain HTTP on the LAN. The room code is the only
secret, and it is typed in by hand, so anyone who sees it before the other computer joins can
join first. Create the call only when the other person is ready.

## Not implemented

- Echo cancellation, noise suppression and automatic gain control. aiortc does not provide
  them and the app does not add them. Use a headset to avoid echo.
- Global push-to-talk hotkeys. Push-to-talk works only while the app window has focus.
- Automatic reconnection after a dropped connection.
- Calls between more than two computers.
- IPv6.

## Project structure

```
local-chat/
├── main.py                    entry point
├── requirements.txt
├── app/
│   ├── core/
│   │   ├── config.py          protocol and tuning constants
│   │   ├── room.py            room codes, address checks, HMAC authentication
│   │   └── call_controller.py call lifecycle; runs asyncio in a worker thread
│   ├── networking/
│   │   ├── signaling.py       local offer/answer exchange over HTTP (aiohttp)
│   │   └── peer.py            WebRTC peer connection (aiortc), statistics
│   ├── audio/
│   │   ├── engine.py          microphone/speaker streams (sounddevice), device listing
│   │   └── frames.py          PCM framing, resampling, frame pacing, level meters
│   └── ui/                    PySide6 screens, widgets and the dark theme
└── tests/
```

## Tests

```powershell
python -m pytest
```

What the tests cover:

- `test_room.py`, `test_frames_and_engine.py`: room codes, address validation, HMAC
  authentication, framing and pacing, mute and push-to-talk gating, buffer caps, and
  playback levels.
- `test_signaling.py`: a valid join, a wrong code, a tampered offer, a busy room, lockout
  after repeated failures, unreachable hosts, and a port already in use.
- `test_two_processes.py`: two separate processes call each other over the machine's LAN
  interface. Each side runs the real signaling server or client, WebRTC negotiation and
  audio transport. Only the sound card is replaced with a generated tone. The test checks
  that each side hears the other's tone frequency.
- `test_controller_flow.py`: two real call controllers go through the full lifecycle: wait,
  reject a wrong code, connect, hang up, and return to waiting. It also checks error
  reporting for unreachable hosts.
- `test_ui_smoke.py`: the window and call screen respond to input and state changes.

Verified in a Linux environment with Python 3.12 and the versions in `requirements.txt`.
Each pinned package was also checked for a Windows x64 Python 3.12 wheel.

**Not yet verified:** the app has not been run on Windows, and it has not been run with
two physical computers. Audio devices were not available in the test environment, so the
microphone and speaker paths were tested only with the sound card replaced.

## Troubleshooting

- **"Cannot reach host"**: check the address, that the host is still on the call screen
  waiting, and that Windows Firewall allows Python on the private network.
- **"Wrong room code"**: codes are case-insensitive, but the code must match exactly.
- **Microphone meter stays at zero**: Windows privacy settings may be blocking desktop apps
  from the microphone. Check Settings → Privacy & security → Microphone.
- **Devices missing from the selector**: only devices that accept 48 kHz mono 16-bit audio
  are listed. Some devices list only other sample rates.
