"""
P1.1 — Mở trang theo 4 tầng, cache 7 ngày, lưu bằng chứng vào evidence/.

Tầng 1: httpx (header Chrome, retry, SSL fallback, PDF)
Tầng 2: Playwright Chrome ẩn
Tầng 3: Playwright Chrome có giao diện + profile .browser-profile/
Tầng 4: không tự vượt → nguồn thay thế / data/can_mo_tay.csv

Không kết luận BỊ_CHẶN chỉ vì HTML có chữ "captcha" (baochinhphu).
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import random
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "cache" / "pages"
EVIDENCE_DIR = ROOT / "evidence"
BROWSER_PROFILE = ROOT / ".browser-profile"
CAN_MO_TAY = ROOT / "data" / "can_mo_tay.csv"
RATE_STATE = ROOT / "cache" / "fetch_rate.json"

CACHE_DAYS = 7
TIMEOUT_S = 20.0
TIER2_WAIT_S = 8.0
TIER3_WAIT_S = 25.0
RATE_MIN_S = 3.0
RATE_MAX_S = 5.0

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    # Không xin br nếu chưa cài brotli — httpx sẽ để body nén → parse sai
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

CHALLENGE_TITLES = (
    "just a moment",
    "chờ một chút",
    "attention required",
    "please wait",
    "checking your browser",
    "cf-browser-verification",
    "ddos protection",
)

DEAD_TITLE_HINTS = (
    "không tìm thấy",
    "not found",
    "page not found",
    "404",
    "410",
    "trang không tồn tại",
    "không tìm thấy ứng dụng",
    "error 404",
)

LOGIN_HINTS = (
    "đăng nhập",
    "sign in",
    "log in",
    "login required",
    "paywall",
    "subscribe to continue",
)


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    status: str = ""  # MỞ_ĐƯỢC | LỖI_SSL_MỞ_ĐƯỢC | LINK_CHẾT | BỊ_CHẶN | CẦN_MỞ_TAY
    tier: int = 0
    http_code: int | None = None
    title: str = ""
    text: str = ""
    content_type: str = ""
    ssl_insecure: bool = False
    reason: str = ""
    screenshot_path: str = ""
    text_path: str = ""
    fetched_at: str = ""
    from_cache: bool = False
    stt: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _url_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _slug(stt: str, url: str) -> str:
    key = _url_key(url)
    prefix = f"{stt}_" if stt else ""
    return f"{prefix}{key}"


def _looks_pdf(url: str, content_type: str, body: bytes) -> bool:
    ct = (content_type or "").lower()
    if "pdf" in ct:
        return True
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        return True
    return body[:5] == b"%PDF-"


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not m:
        return ""
    title = re.sub(r"\s+", " ", m.group(1)).strip()
    title = re.sub(r"<[^>]+>", "", title)
    title = html_lib.unescape(title)
    return title[:300]


def _html_to_text(html: str) -> str:
    # Bỏ script/style trước khi strip tag — tránh bắt nhầm chữ captcha trong JS
    cleaned = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    cleaned = re.sub(r"(?is)<!--.*?-->", " ", cleaned)
    cleaned = re.sub(r"(?is)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?is)</p>", "\n", cleaned)
    cleaned = re.sub(r"(?is)</(div|li|h[1-6]|tr)>", "\n", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    # Decode named + numeric entities (Ho&agrave;ng → Hoàng). Do NOT blank &#NNN;.
    cleaned = html_lib.unescape(cleaned)
    cleaned = cleaned.replace("\xa0", " ")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _visible_text_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def _is_challenge_title(title: str) -> bool:
    t = (title or "").lower()
    return any(h in t for h in CHALLENGE_TITLES)


def _is_dead_title(title: str, text: str) -> bool:
    blob = f"{title}\n{text[:2000]}".lower()
    return any(h in blob for h in DEAD_TITLE_HINTS)


def _is_cms_access_denied(title: str, text: str) -> bool:
    """Drupal/CMS từ chối quyền — không phải Cloudflare; escalate không giúp."""
    blob = f"{title}\n{text[:2000]}".lower()
    return (
        "you are not authorized to access this page" in blob
        or "bạn không được phép truy cập" in blob
        or ("access denied" in blob and "not authorized" in blob)
    )


def _needs_escalation(http_code: int | None, title: str, text: str, html: str) -> tuple[bool, str]:
    """Escalate lên tầng 2/3 khi nghi chặn bot hoặc cần JS.

    Không kết luận BỊ_CHẶN chỉ vì HTML có chữ captcha (baochinhphu).
    """
    code = http_code or 0
    html_l = (html or "")[:8000].lower()

    # CMS 403 cố định — giữ ở tầng 1 (đã mở được HTML, thường kèm SSL)
    if _is_cms_access_denied(title, text):
        return False, ""

    if code in (403, 429, 503):
        return True, f"HTTP {code} — thử tầng Playwright"
    if _is_challenge_title(title):
        return True, f"tiêu đề trang chờ: {title!r}"
    # Cloudflare / challenge markers trong HTML (kèm nội dung mỏng)
    cf_markers = ("cf-browser-verification", "cf-challenge", "just a moment", "chờ một chút")
    if any(m in html_l for m in cf_markers) and _visible_text_len(text) < 400:
        return True, "dấu hiệu Cloudflare/challenge trong HTML"
    # HTML ngắn, gần như không có chữ nội dung
    if html and len(html) < 10_000 and _visible_text_len(text) < 80:
        return True, "HTML ngắn / gần như không có chữ"
    # Cần JS: body gần trống sau khi bỏ script
    if html and _visible_text_len(text) < 40 and ("<script" in html_l):
        return True, "nội dung rỗng, trang cần JavaScript"
    return False, ""


def _needs_manual(title: str, text: str) -> tuple[bool, str]:
    blob = f"{title}\n{text[:3000]}".lower()
    # CAPTCHA bắt thao tác (không phải chỉ có chữ captcha trong JS)
    interactive = (
        "cf-turnstile" in blob
        or "g-recaptcha" in blob
        or "hcaptcha" in blob
        or "solve the challenge" in blob
        or "xác minh bạn là người" in blob
    )
    if interactive and _visible_text_len(text) < 200:
        return True, "CAPTCHA / xác minh bắt thao tác"
    if any(h in blob for h in LOGIN_HINTS) and _visible_text_len(text) < 300:
        return True, "trang đòi đăng nhập / trả phí"
    return False, ""


def _redirected_to_home(original: str, final: str) -> bool:
    o, f = urlparse(original), urlparse(final)
    if not f.netloc or o.netloc.lower() != f.netloc.lower():
        return False
    op = (o.path or "/").rstrip("/") or "/"
    fp = (f.path or "/").rstrip("/") or "/"
    # Chuyển về trang chủ (path rỗng hoặc /) trong khi URL gốc có path sâu
    if fp == "/" and op != "/" and len(op) > 1:
        return True
    return False


def _extract_pdf_text(data: bytes) -> tuple[str, str]:
    """Trả (text, note). note = cần OCR nếu không có lớp chữ."""
    text = ""
    try:
        import pdfplumber
        import io

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            parts = []
            for page in pdf.pages[:30]:
                parts.append(page.extract_text() or "")
            text = "\n".join(parts).strip()
    except Exception as e:
        text = ""
        pdf_err = str(e)
    else:
        pdf_err = ""

    if not text:
        try:
            import fitz

            doc = fitz.open(stream=data, filetype="pdf")
            parts = [page.get_text() for page in doc[:30]]
            text = "\n".join(parts).strip()
            doc.close()
        except Exception as e:
            if not pdf_err:
                pdf_err = str(e)

    if not text:
        return "", "cần OCR hoặc mở tay" + (f" ({pdf_err})" if pdf_err else "")
    return text, ""


# --- cache / rate / evidence -------------------------------------------------


def _cache_path(url: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{_url_key(url)}.json"


def _load_cache(url: str) -> FetchResult | None:
    path = _cache_path(url)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    fetched_at = data.get("fetched_at") or ""
    try:
        ts = datetime.fromisoformat(fetched_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if datetime.now(timezone.utc) - ts.astimezone(timezone.utc) > timedelta(days=CACHE_DAYS):
        return None
    result = FetchResult(**{k: data[k] for k in FetchResult.__dataclass_fields__ if k in data})
    result.from_cache = True
    return result


def _save_cache(result: FetchResult) -> None:
    path = _cache_path(result.url)
    path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def _rate_wait(domain: str) -> None:
    if not domain:
        return
    RATE_STATE.parent.mkdir(parents=True, exist_ok=True)
    state: dict[str, float] = {}
    if RATE_STATE.exists():
        try:
            state = json.loads(RATE_STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
    last = float(state.get(domain, 0))
    gap = random.uniform(RATE_MIN_S, RATE_MAX_S)
    now = time.time()
    wait = last + gap - now
    if wait > 0:
        time.sleep(wait)
    state[domain] = time.time()
    RATE_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _save_evidence(
    result: FetchResult,
    *,
    html_or_bytes: bytes | str | None = None,
    screenshot: bytes | None = None,
) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slug(result.stt, result.url)
    text_path = EVIDENCE_DIR / f"{slug}.txt"
    meta_path = EVIDENCE_DIR / f"{slug}.meta.json"

    header = (
        f"URL: {result.url}\n"
        f"Final: {result.final_url}\n"
        f"Status: {result.status}\n"
        f"Tier: {result.tier}\n"
        f"HTTP: {result.http_code}\n"
        f"Title: {result.title}\n"
        f"Fetched: {result.fetched_at}\n"
        f"SSL insecure: {result.ssl_insecure}\n"
        f"Reason: {result.reason}\n"
        f"{'=' * 60}\n\n"
    )
    text_path.write_text(header + (result.text or ""), encoding="utf-8")
    result.text_path = str(text_path.relative_to(ROOT))

    if screenshot:
        png_path = EVIDENCE_DIR / f"{slug}.png"
        png_path.write_bytes(screenshot)
        result.screenshot_path = str(png_path.relative_to(ROOT))

    if html_or_bytes is not None and not result.screenshot_path:
        # Tầng 1 không có ảnh — lưu raw để đối chiếu
        raw_path = EVIDENCE_DIR / f"{slug}.raw"
        if isinstance(html_or_bytes, bytes):
            raw_path.write_bytes(html_or_bytes[:2_000_000])
        else:
            raw_path.write_text(html_or_bytes[:2_000_000], encoding="utf-8")

    meta_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _append_can_mo_tay(result: FetchResult) -> None:
    CAN_MO_TAY.parent.mkdir(parents=True, exist_ok=True)
    new_file = not CAN_MO_TAY.exists()
    reason = result.reason.replace('"', "'")
    line = f'{result.stt},"{result.url}",{result.tier},"{reason}",{result.fetched_at}\n'
    with CAN_MO_TAY.open("a", encoding="utf-8") as f:
        if new_file:
            f.write("stt,url,tier,reason,fetched_at\n")
        f.write(line)


# --- tầng 1: httpx -----------------------------------------------------------


def _tier1(url: str, stt: str = "") -> FetchResult:
    result = FetchResult(url=url, stt=stt, fetched_at=_now_iso(), tier=1)
    domain = _domain(url)
    _rate_wait(domain)

    last_err: Exception | None = None
    response: httpx.Response | None = None
    ssl_insecure = False

    def _is_ssl_error(exc: BaseException) -> bool:
        blob = f"{type(exc).__name__} {exc}".lower()
        cause = getattr(exc, "__cause__", None)
        if cause is not None:
            blob += f" {type(cause).__name__} {cause}".lower()
        return any(
            k in blob
            for k in (
                "ssl",
                "certificate",
                "certverify",
                "certification",
                "tls",
                "self-signed",
                "certificate_verify_failed",
            )
        )

    for attempt in range(3):  # lần đầu + 2 retry
        try:
            with httpx.Client(
                headers=HEADERS,
                follow_redirects=True,
                timeout=TIMEOUT_S,
                verify=not ssl_insecure,
            ) as client:
                response = client.get(url)
            break
        except httpx.TimeoutException as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
            continue
        except httpx.ConnectError as e:
            msg = str(e).lower()
            if "name or service not known" in msg or "nodename nor servname" in msg or "getaddrinfo" in msg:
                result.status = "LINK_CHẾT"
                result.reason = f"DNS lỗi: {e}"
                return result
            if not ssl_insecure and _is_ssl_error(e):
                ssl_insecure = True
                last_err = e
                continue
            last_err = e
            time.sleep(1.5 * (attempt + 1))
            continue
        except httpx.HTTPError as e:
            if not ssl_insecure and _is_ssl_error(e):
                ssl_insecure = True
                last_err = e
                continue
            last_err = e
            time.sleep(1.5 * (attempt + 1))
            continue

    if response is None:
        if not ssl_insecure and last_err and _is_ssl_error(last_err):
            ssl_insecure = True
            try:
                with httpx.Client(
                    headers=HEADERS,
                    follow_redirects=True,
                    timeout=TIMEOUT_S,
                    verify=False,
                ) as client:
                    response = client.get(url)
            except Exception as e:
                result.status = "LINK_CHẾT"
                result.reason = f"không kết nối được: {e}"
                return result
        else:
            result.status = "LINK_CHẾT"
            result.reason = f"không kết nối được: {last_err}"
            return result

    result.http_code = response.status_code
    result.final_url = str(response.url)
    result.content_type = response.headers.get("content-type", "")
    result.ssl_insecure = ssl_insecure
    body = response.content

    # Dead by status
    if response.status_code in (404, 410):
        result.status = "LINK_CHẾT"
        result.reason = f"HTTP {response.status_code}"
        result.title = _extract_title(body.decode("utf-8", errors="replace")) if body else ""
        result.text = _html_to_text(body.decode("utf-8", errors="replace"))[:5000] if body else ""
        return result

    # Retry backoff for rate / server errors (không phải challenge)
    if response.status_code in (429, 500, 502, 504) and not _is_challenge_title(
        _extract_title(body.decode("utf-8", errors="replace"))
    ):
        # đã retry trong loop khi exception; ở đây coi là có response
        pass

    if _looks_pdf(result.final_url, result.content_type, body):
        text, note = _extract_pdf_text(body)
        result.content_type = "application/pdf"
        result.title = Path(urlparse(result.final_url).path).name or "PDF"
        result.text = text
        if note and not text:
            result.status = "CẦN_MỞ_TAY"
            result.reason = note
            result.tier = 4
            return result
        result.status = "LỖI_SSL_MỞ_ĐƯỢC" if ssl_insecure else "MỞ_ĐƯỢC"
        if note:
            result.reason = note
        return result

    html = body.decode("utf-8", errors="replace")
    title = _extract_title(html)
    text = _html_to_text(html)
    result.title = title
    result.text = text[:50_000]

    if _redirected_to_home(url, result.final_url):
        result.status = "LINK_CHẾT"
        result.reason = "bị chuyển về trang chủ"
        return result

    if response.status_code == 200 and _is_dead_title(title, text):
        result.status = "LINK_CHẾT"
        result.reason = f"trang báo lỗi (HTTP 200): {title!r}"
        return result

    escalate, why = _needs_escalation(response.status_code, title, text, html)
    if escalate:
        result.status = "ESCALATE"
        result.reason = why
        result.meta["html_len"] = len(html)
        return result

    # CMS Access denied: đã mở được HTML (thường sau SSL bypass)
    if _is_cms_access_denied(title, text):
        result.status = "LỖI_SSL_MỞ_ĐƯỢC" if ssl_insecure else "MỞ_ĐƯỢC"
        result.reason = "trang từ chối truy cập (Access denied / not authorized)"
        result.meta["html_len"] = len(html)
        result.meta["cms_denied"] = True
        return result

    # Soft fail: 4xx khác (trừ challenge đã escalate)
    if response.status_code >= 400:
        result.status = "LINK_CHẾT"
        result.reason = f"HTTP {response.status_code}"
        return result

    result.status = "LỖI_SSL_MỞ_ĐƯỢC" if ssl_insecure else "MỞ_ĐƯỢC"
    result.meta["html_len"] = len(html)
    return result


# --- tầng 2 & 3: Playwright --------------------------------------------------


_STEALTH_ARGS = ["--disable-blink-features=AutomationControlled"]
_STEALTH_INIT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


def _playwright_fetch(
    url: str,
    *,
    headless: bool,
    wait_s: float,
    stt: str = "",
    tier: int = 2,
) -> FetchResult:
    from playwright.sync_api import sync_playwright

    result = FetchResult(url=url, stt=stt, fetched_at=_now_iso(), tier=tier)
    domain = _domain(url)
    _rate_wait(domain)

    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    screenshot: bytes | None = None

    try:
        with sync_playwright() as p:
            if headless:
                browser = p.chromium.launch(
                    channel="chrome",
                    headless=True,
                    args=_STEALTH_ARGS,
                )
                context = browser.new_context(
                    user_agent=CHROME_UA,
                    locale="vi-VN",
                    viewport={"width": 1280, "height": 900},
                    ignore_https_errors=True,
                )
            else:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(BROWSER_PROFILE),
                    channel="chrome",
                    headless=False,
                    user_agent=CHROME_UA,
                    locale="vi-VN",
                    viewport={"width": 1280, "height": 900},
                    ignore_https_errors=True,
                    args=_STEALTH_ARGS,
                )
                browser = None

            page = context.new_page() if headless else (
                context.pages[0] if context.pages else context.new_page()
            )
            page.add_init_script(_STEALTH_INIT)
            response = None
            try:
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(max(TIMEOUT_S, wait_s + 5) * 1000),
                )
            except Exception as e:
                result.status = "ESCALATE" if headless else "BỊ_CHẶN"
                result.reason = f"goto lỗi: {e}"
                try:
                    if headless:
                        context.close()
                        browser.close()  # type: ignore[union-attr]
                    else:
                        context.close()
                except Exception:
                    pass
                return result

            # Chờ challenge tự qua: title đổi + có chữ thật (CF thường ~4–8s)
            deadline = time.time() + wait_s
            while time.time() < deadline:
                title_now = page.title() or ""
                try:
                    body_now = page.inner_text("body") or ""
                except Exception:
                    body_now = ""
                if not _is_challenge_title(title_now) and _visible_text_len(body_now) > 400:
                    page.wait_for_timeout(500)
                    break
                page.wait_for_timeout(500)

            result.final_url = page.url
            result.http_code = response.status if response else None
            result.title = page.title() or ""
            try:
                result.text = page.inner_text("body")[:50_000]
            except Exception:
                result.text = _html_to_text(page.content())[:50_000]
            result.content_type = "text/html"
            try:
                screenshot = page.screenshot(full_page=False, type="png")
            except Exception:
                screenshot = None

            html = page.content()
            title = result.title
            text = result.text

            if result.http_code in (404, 410) or (
                (result.http_code or 0) == 200 and _is_dead_title(title, text)
            ):
                result.status = "LINK_CHẾT"
                result.reason = f"HTTP {result.http_code} / trang lỗi: {title!r}"
            elif _redirected_to_home(url, result.final_url):
                result.status = "LINK_CHẾT"
                result.reason = "bị chuyển về trang chủ"
            elif _is_cms_access_denied(title, text):
                result.status = "MỞ_ĐƯỢC"
                result.reason = "trang từ chối truy cập (Access denied / not authorized)"
                result.meta["cms_denied"] = True
            else:
                still_challenge = _is_challenge_title(title) and _visible_text_len(text) < 400

                if still_challenge:
                    if headless:
                        result.status = "ESCALATE"
                        result.reason = f"vẫn trang chờ sau tầng 2: {title!r}"
                    else:
                        manual, why = _needs_manual(title, text)
                        if manual:
                            result.status = "CẦN_MỞ_TAY"
                            result.reason = why
                            result.tier = 4
                        else:
                            result.status = "BỊ_CHẶN"
                            result.reason = f"qua tầng 3 vẫn chặn: {title!r}"
                else:
                    manual, why = _needs_manual(title, text)
                    if manual and _visible_text_len(text) < 200:
                        result.status = "CẦN_MỞ_TAY"
                        result.reason = why
                        result.tier = 4
                    else:
                        result.status = "MỞ_ĐƯỢC"
                        result.meta["html_len"] = len(html)

            if headless:
                context.close()
                browser.close()  # type: ignore[union-attr]
            else:
                context.close()

    except Exception as e:
        result.status = "ESCALATE" if headless else "BỊ_CHẶN"
        result.reason = f"playwright lỗi: {e}"
        return result

    result.meta["screenshot_bytes"] = screenshot  # tạm, sẽ bỏ trước khi cache
    return result


# --- API chính ----------------------------------------------------------------


def fetch(
    url: str,
    *,
    stt: str = "",
    use_cache: bool = True,
    max_tier: int = 3,
    save: bool = True,
) -> FetchResult:
    """
    Mở URL theo cascade tầng 1→2→3. Trả FetchResult.

    status:
      MỞ_ĐƯỢC | LỖI_SSL_MỞ_ĐƯỢC | LINK_CHẾT | BỊ_CHẶN | CẦN_MỞ_TAY
    """
    url = url.strip()
    if use_cache:
        cached = _load_cache(url)
        if cached is not None:
            if stt and not cached.stt:
                cached.stt = stt
            return cached

    # Tầng 1
    result = _tier1(url, stt=stt)
    screenshot: bytes | None = None
    ssl_from_t1 = result.ssl_insecure
    reason_t1 = result.reason

    if result.status == "ESCALATE" and max_tier >= 2:
        # Tầng 2
        r2 = _playwright_fetch(url, headless=True, wait_s=TIER2_WAIT_S, stt=stt, tier=2)
        screenshot = r2.meta.pop("screenshot_bytes", None)
        r2.ssl_insecure = r2.ssl_insecure or ssl_from_t1
        if r2.status == "ESCALATE" and max_tier >= 3:
            # Tầng 3
            r3 = _playwright_fetch(url, headless=False, wait_s=TIER3_WAIT_S, stt=stt, tier=3)
            screenshot = r3.meta.pop("screenshot_bytes", None) or screenshot
            r3.ssl_insecure = r3.ssl_insecure or ssl_from_t1
            result = r3
        elif r2.status == "ESCALATE":
            result = r2
            result.status = "BỊ_CHẶN"
            result.reason = result.reason or "dừng trước tầng 3"
        else:
            result = r2
        if result.status == "MỞ_ĐƯỢC" and ssl_from_t1:
            result.status = "LỖI_SSL_MỞ_ĐƯỢC"
            result.reason = result.reason or "mở được sau khi bỏ kiểm chứng chỉ (tầng 1)"
        if reason_t1 and result.reason and reason_t1 not in result.reason:
            result.reason = f"{reason_t1} → {result.reason}"
        elif reason_t1 and not result.reason:
            result.reason = reason_t1
    elif result.status == "ESCALATE":
        result.status = "BỊ_CHẶN"

    # Dọn meta tạm
    result.meta.pop("screenshot_bytes", None)

    if result.status == "CẦN_MỞ_TAY":
        _append_can_mo_tay(result)

    if save and result.status in (
        "MỞ_ĐƯỢC",
        "LỖI_SSL_MỞ_ĐƯỢC",
        "LINK_CHẾT",
        "BỊ_CHẶN",
        "CẦN_MỞ_TAY",
    ):
        _save_evidence(result, screenshot=screenshot)
        _save_cache(result)

    return result


def fetch_many(urls: list[tuple[str, str]], **kwargs: Any) -> list[FetchResult]:
    """urls: list of (stt, url)."""
    out: list[FetchResult] = []
    for stt, url in urls:
        print(f"→ [{stt}] {url}", flush=True)
        r = fetch(url, stt=str(stt), **kwargs)
        print(
            f"  status={r.status} tier={r.tier} http={r.http_code} "
            f"ssl={r.ssl_insecure} title={r.title[:80]!r}",
            flush=True,
        )
        out.append(r)
    return out


# --- nghiệm thu P1.1 ---------------------------------------------------------

ACCEPTANCE: list[tuple[str, str, str]] = [
    # stt, url, kỳ vọng (status chứa / tier tối thiểu nếu mở được)
    (
        "tvpl",
        "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-976-QD-BGTVT-2023-mo-cang-can-Phu-My-697784.aspx?tab=3",
        "tier3",
    ),
    (
        "vimawa",
        "https://vimawa.gov.vn/vi/node/15406",
        "ssl_or_ok",
    ),
    (
        "mt",
        "https://mt.gov.vn/cntt/tin-tuc/858/94903/cong-bo-mo-cang-can-dong-pho-moi-%28lao-cai%29.aspx",
        "dead",
    ),
    (
        "bcp",
        "https://baochinhphu.vn/bo-gtvt-cong-bo-mo-cang-can-dau-tien-tai-hai-phong-102246365.htm",
        "ok_not_blocked",
    ),
]


def run_acceptance(use_cache: bool = False) -> int:
    """Chạy 4 URL nghiệm thu P1.1. Trả 0 nếu đủ điều kiện."""
    print("=== P1.1 acceptance ===", flush=True)
    results: dict[str, FetchResult] = {}
    ok_all = True

    for stt, url, expect in ACCEPTANCE:
        print(f"\n--- {stt}: expect={expect} ---", flush=True)
        r = fetch(url, stt=stt, use_cache=use_cache, max_tier=3)
        results[stt] = r
        print(
            f"status={r.status} tier={r.tier} http={r.http_code} "
            f"ssl={r.ssl_insecure} from_cache={r.from_cache}\n"
            f"title={r.title!r}\nreason={r.reason!r}\n"
            f"text_len={len(r.text)} evidence={r.text_path}",
            flush=True,
        )

        passed = False
        if expect == "tier3":
            passed = r.status == "MỞ_ĐƯỢC" and r.tier == 3
        elif expect == "ssl_or_ok":
            # vimawa: SSL fallback hoạt động (cert lỗi → verify=False vẫn lấy được HTML)
            passed = (
                r.ssl_insecure
                and r.status in ("LỖI_SSL_MỞ_ĐƯỢC", "MỞ_ĐƯỢC")
                and len(r.text) > 100
            )
        elif expect == "dead":
            passed = r.status == "LINK_CHẾT"
        elif expect == "ok_not_blocked":
            passed = r.status in ("MỞ_ĐƯỢC", "LỖI_SSL_MỞ_ĐƯỢC") and r.status != "BỊ_CHẶN"
            # Không bị nhận nhầm chỉ vì captcha trong source
            passed = passed and len(r.text) > 100

        print(f"{'PASS' if passed else 'FAIL'} [{stt}]", flush=True)
        ok_all = ok_all and passed

    print("\n=== SUMMARY ===", flush=True)
    for stt, r in results.items():
        print(f"  {stt}: {r.status} tier={r.tier} ssl={r.ssl_insecure}", flush=True)
    print("ALL PASS" if ok_all else "SOME FAILED", flush=True)
    return 0 if ok_all else 1


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "test":
        use_cache = "--cache" in argv
        return run_acceptance(use_cache=use_cache)
    if len(argv) >= 2:
        url = argv[1]
        stt = argv[2] if len(argv) > 2 else ""
        r = fetch(url, stt=stt, use_cache="--cache" in argv)
        print(json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
        return 0 if r.status in ("MỞ_ĐƯỢC", "LỖI_SSL_MỞ_ĐƯỢC") else 1
    print("Usage: python scripts/fetch.py test [--cache]")
    print("       python scripts/fetch.py <url> [stt] [--cache]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
