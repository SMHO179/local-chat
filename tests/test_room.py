import pytest

from app.core.room import generate_room_code, normalize_room_code, parse_host_ip, sign_sdp, verify_sdp
from app.core.config import ROOM_ALPHABET


def test_generated_codes_use_safe_alphabet_and_length():
    codes = {generate_room_code() for _ in range(200)}
    assert len(codes) > 190  # effectively unique
    for code in codes:
        assert len(code) == 6
        assert set(code) <= set(ROOM_ALPHABET)
        assert not set(code) & set("01IO")


def test_normalize_accepts_case_spaces_and_dashes():
    assert normalize_room_code(" k7m-2qf ") == "K7M2QF"
    assert normalize_room_code("K7M 2QF") == "K7M2QF"


@pytest.mark.parametrize("bad", ["", "K7M2Q", "K7M2QFA", "K7M2Q0", "K7M2QI", "K7M2Q!", "../../x"])
def test_normalize_rejects_invalid_codes(bad):
    with pytest.raises(ValueError):
        normalize_room_code(bad)


@pytest.mark.parametrize("good", ["192.168.137.1", "10.0.0.5", "172.16.4.2", "169.254.10.9", "127.0.0.1"])
def test_host_ip_accepts_local_addresses(good):
    assert parse_host_ip(good) == good


@pytest.mark.parametrize("bad", ["8.8.8.8", "example.com", "999.1.1.1", "", "::1", "192.168.1"])
def test_host_ip_rejects_public_or_invalid_addresses(bad):
    with pytest.raises(ValueError):
        parse_host_ip(bad)


def test_sdp_signature_binds_role_code_and_content():
    sdp = "v=0\r\na=fingerprint:sha-256 AB:CD\r\n"
    mac = sign_sdp("K7M2QF", "offer", sdp)
    assert verify_sdp("K7M2QF", "offer", sdp, mac)
    assert not verify_sdp("K7M2QF", "answer", sdp, mac)           # role swap
    assert not verify_sdp("ZZZ222", "offer", sdp, mac)            # wrong code
    assert not verify_sdp("K7M2QF", "offer", sdp + "x", mac)      # tampered SDP
    assert not verify_sdp("K7M2QF", "offer", sdp, None)           # missing mac
    assert not verify_sdp("K7M2QF", "offer", sdp, "é" * 4)        # non-ASCII mac
