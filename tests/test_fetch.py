"""P1.1 – nghiệm thu fetch.py, chạy offline (thay cho `fetch.py test` cần mạng)."""
from __future__ import annotations

import socket

import pytest


def test_network_is_blocked():
    with pytest.raises(Exception):
        socket.create_connection(("example.com", 80), timeout=1)


def test_run_acceptance_offline(offline_fetch, capsys):
    assert offline_fetch.run_acceptance(use_cache=False) == 0
    assert "ALL PASS" in capsys.readouterr().out


def test_tvpl_cloudflare_escalates_to_tier3(offline_fetch):
    url = dict((s, u) for s, u, _ in offline_fetch.ACCEPTANCE)["tvpl"]
    r = offline_fetch.fetch(url, stt="tvpl", use_cache=False)
    assert r.status == "MỞ_ĐƯỢC" and r.tier == 3
    assert "976" in r.title


def test_vimawa_ssl_fallback(offline_fetch):
    url = dict((s, u) for s, u, _ in offline_fetch.ACCEPTANCE)["vimawa"]
    r = offline_fetch.fetch(url, stt="vimawa", use_cache=False)
    assert r.ssl_insecure and r.status == "LỖI_SSL_MỞ_ĐƯỢC"
    assert len(r.text) > 100
    verifies = [v for u, v in offline_fetch._test_calls if "vimawa" in u]
    assert verifies[0] is True and False in verifies


def test_dns_error_is_dead(offline_fetch):
    r = offline_fetch.fetch("https://mt.gov.vn/x", stt="mt", use_cache=False)
    assert r.status == "LINK_CHẾT" and "DNS" in r.reason


def test_cache_roundtrip(offline_fetch):
    url = "https://baochinhphu.vn/a.htm"
    r1 = offline_fetch.fetch(url, stt="1")
    r2 = offline_fetch.fetch(url, stt="1")
    assert not r1.from_cache and r2.from_cache and r1.status == r2.status == "MỞ_ĐƯỢC"


def test_needs_escalation_ignores_captcha_word():
    import fetch as F
    text = "nội dung " * 200
    assert F._needs_escalation(200, "Báo Chính phủ", text, "<script>captcha</script>" + text) == (False, "")
