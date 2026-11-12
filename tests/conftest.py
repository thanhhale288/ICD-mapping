"""Cấu hình pytest chung: chặn mạng + giả lập fetch offline.

- Mọi kết nối socket ra ngoài bị chặn (NetworkBlocked) → test không bao giờ
  phụ thuộc mạng.
- Fixture `offline_fetch` thay httpx.Client và Playwright trong scripts/fetch.py
  bằng phản hồi giả lập (fixture HTML) và chuyển cache/evidence vào tmp_path.
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class NetworkBlocked(RuntimeError):
    pass


def _blocked(*args, **kwargs):
    raise NetworkBlocked("network access is disabled in tests")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)


LONG_BODY = " ".join(["Bộ Giao thông vận tải công bố mở cảng cạn."] * 40)

TVPL_CHALLENGE = "<html><head><title>Just a moment...</title></head><body><script>cf-challenge</script></body></html>"
VIMAWA_HTML = f"<html><head><title>Cục Hàng hải Việt Nam</title></head><body><p>{LONG_BODY}</p></body></html>"
BCP_HTML = (
    "<html><head><title>Bộ GTVT công bố mở cảng cạn đầu tiên tại Hải Phòng</title>"
    "<script>var captcha = 'g-captcha-config';</script></head>"
    f"<body><article>{LONG_BODY}</article></body></html>"
)
TVPL_TIER3_TEXT = "Quyết định 976/QĐ-BGTVT năm 2023 công bố mở cảng cạn Phú Mỹ. " + LONG_BODY


def _route(request: httpx.Request, verify: bool) -> httpx.Response:
    host = request.url.host
    if host == "thuvienphapluat.vn":
        return httpx.Response(403, html=TVPL_CHALLENGE, request=request)
    if host == "vimawa.gov.vn":
        if verify:
            raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed", request=request)
        return httpx.Response(200, html=VIMAWA_HTML, request=request)
    if host == "mt.gov.vn":
        raise httpx.ConnectError("[Errno -2] Name or service not known", request=request)
    if host == "baochinhphu.vn":
        return httpx.Response(200, html=BCP_HTML, request=request)
    return httpx.Response(404, html="<title>404 Not Found</title>", request=request)


@pytest.fixture
def offline_fetch(monkeypatch, tmp_path):
    """Giả lập mạng cho scripts/fetch.py; trả về module fetch đã vá."""
    import fetch as F

    real_client = httpx.Client
    calls: list[tuple[str, bool]] = []

    def fake_client(*args, verify=True, **kwargs):
        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((str(request.url), bool(verify)))
            return _route(request, bool(verify))

        kwargs.pop("transport", None)
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    def fake_playwright(url, *, headless, wait_s, stt="", tier=2, **kw):
        r = F.FetchResult(url=url, final_url=url, stt=stt, tier=tier, fetched_at=F._now_iso())
        if "thuvienphapluat.vn" in url and tier == 3:
            r.status, r.http_code = "MỞ_ĐƯỢC", 200
            r.title = "Quyết định 976/QĐ-BGTVT 2023 mở cảng cạn Phú Mỹ"
            r.text = TVPL_TIER3_TEXT
        else:
            r.status, r.http_code = "ESCALATE", 403
            r.title, r.reason = "Just a moment...", "Cloudflare (giả lập)"
        return r

    monkeypatch.setattr(F.httpx, "Client", fake_client)
    monkeypatch.setattr(F, "_playwright_fetch", fake_playwright)
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    monkeypatch.setattr(F, "ROOT", tmp_path)
    monkeypatch.setattr(F, "CACHE_DIR", tmp_path / "cache" / "pages")
    monkeypatch.setattr(F, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(F, "CAN_MO_TAY", tmp_path / "data" / "can_mo_tay.csv")
    monkeypatch.setattr(F, "RATE_STATE", tmp_path / "cache" / "fetch_rate.json")
    monkeypatch.setattr(F, "RATE_MIN_S", 0.0)
    monkeypatch.setattr(F, "RATE_MAX_S", 0.0)
    F._test_calls = calls
    return F
