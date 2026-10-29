"""
Tìm kiếm web theo thứ tự: Brave → Google CSE → (Bing đã ngừng) → báo cần agent.

Khi một provider hết quota / lỗi auth / không có key, tự chuyển provider tiếp theo
trong cùng phiên (và nhớ provider đã chết để không gọi lại).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
STATE_PATH = ROOT / "cache" / "search_provider_state.json"

PROVIDERS = ("brave", "google", "bing")


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    provider: str


class QuotaExhausted(Exception):
    """Provider hết hạn mức hoặc không dùng được nữa trong phiên này."""


class ProviderUnavailable(Exception):
    """Thiếu key / dịch vụ đã ngừng / lỗi cấu hình."""


def load_dotenv(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _read_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"disabled": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"disabled": {}}


def _write_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def disable_provider(name: str, reason: str) -> None:
    state = _read_state()
    state.setdefault("disabled", {})[name] = reason
    _write_state(state)


def is_disabled(name: str) -> bool:
    return name in _read_state().get("disabled", {})


def reset_provider_state() -> None:
    if STATE_PATH.exists():
        STATE_PATH.unlink()


def _client() -> "httpx.Client":
    if httpx is None:
        raise RuntimeError("Cần cài httpx: pip install httpx")
    return httpx.Client(timeout=30.0)


def _search_brave(query: str, count: int) -> list[SearchHit]:
    key = os.environ.get("BRAVE_API_KEY", "").strip()
    if not key:
        raise ProviderUnavailable("Thiếu BRAVE_API_KEY")

    with _client() as client:
        r = client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": key,
            },
            params={
                "q": query,
                "count": min(count, 20),
                "country": "VN",
                "search_lang": "vi",
            },
        )

    if r.status_code in (401, 403):
        raise ProviderUnavailable(f"Brave auth lỗi HTTP {r.status_code}")
    if r.status_code in (402, 429):
        raise QuotaExhausted(f"Brave hết quota/credit HTTP {r.status_code}")
    if r.status_code >= 400:
        # Một số bản Brave trả 422/400 khi plan sai — coi như unavailable
        body = r.text[:300]
        if "credit" in body.lower() or "quota" in body.lower() or "limit" in body.lower():
            raise QuotaExhausted(f"Brave hết hạn mức: {body}")
        raise ProviderUnavailable(f"Brave lỗi HTTP {r.status_code}: {body}")

    data = r.json()
    hits: list[SearchHit] = []
    for item in data.get("web", {}).get("results", [])[:count]:
        hits.append(
            SearchHit(
                title=item.get("title") or "",
                url=item.get("url") or "",
                snippet=item.get("description") or "",
                provider="brave",
            )
        )
    return hits


def _search_google(query: str, count: int) -> list[SearchHit]:
    key = os.environ.get("GOOGLE_CSE_API_KEY", "").strip()
    cx = os.environ.get("GOOGLE_CSE_CX", "").strip()
    if not key or not cx:
        raise ProviderUnavailable("Thiếu GOOGLE_CSE_API_KEY hoặc GOOGLE_CSE_CX")

    with _client() as client:
        r = client.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": key,
                "cx": cx,
                "q": query,
                "num": min(count, 10),
                "hl": "vi",
                "gl": "vn",
            },
        )

    if r.status_code in (401, 403):
        body = r.text.lower()
        if "quota" in body or "rate" in body or "exhausted" in body:
            raise QuotaExhausted(f"Google hết quota HTTP {r.status_code}")
        raise ProviderUnavailable(f"Google auth/cấu hình lỗi HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code == 429:
        raise QuotaExhausted("Google hết quota ngày (thường 100 query free)")
    if r.status_code >= 400:
        raise ProviderUnavailable(f"Google lỗi HTTP {r.status_code}: {r.text[:300]}")

    data = r.json()
    hits: list[SearchHit] = []
    for item in data.get("items", [])[:count]:
        hits.append(
            SearchHit(
                title=item.get("title") or "",
                url=item.get("link") or "",
                snippet=item.get("snippet") or "",
                provider="google",
            )
        )
    return hits


def _search_bing(query: str, count: int) -> list[SearchHit]:
    # Bing Web Search API v7 đã ngừng 11/08/2025. Giữ stub để cascade rõ ràng.
    key = os.environ.get("BING_API_KEY", "").strip()
    if not key:
        raise ProviderUnavailable(
            "Bing Web Search API đã ngừng (11/08/2025); không còn đăng ký key mới"
        )
    raise ProviderUnavailable(
        "Bing Web Search API đã ngừng; bỏ BING_API_KEY và dùng Brave/Google/agent"
    )


_SEARCHERS = {
    "brave": _search_brave,
    "google": _search_google,
    "bing": _search_bing,
}


def search(query: str, count: int = 10) -> tuple[list[SearchHit], str]:
    """
    Trả (hits, provider_đã_dùng).
    Nếu cả ba provider không dùng được → RuntimeError với hướng dẫn agent.
    """
    load_dotenv()
    errors: list[str] = []

    for name in PROVIDERS:
        if is_disabled(name):
            errors.append(f"{name}: đã tắt trong phiên ({_read_state()['disabled'].get(name)})")
            continue
        try:
            hits = _SEARCHERS[name](query, count)
            return hits, name
        except QuotaExhausted as e:
            disable_provider(name, str(e))
            errors.append(f"{name}: {e}")
        except ProviderUnavailable as e:
            disable_provider(name, str(e))
            errors.append(f"{name}: {e}")

    raise RuntimeError(
        "Không còn search API khả dụng. Cascade đã thử Brave → Google → Bing.\n"
        "Tiếp theo: agent tra trong phiên (WebSearch) hoặc nạp lại credit/key rồi "
        "chạy scripts/search.py --reset-state.\n"
        "Chi tiết:\n- " + "\n- ".join(errors)
    )


def main(argv: list[str]) -> int:
    load_dotenv()
    if "--reset-state" in argv:
        reset_provider_state()
        print("Đã xóa cache/search_provider_state.json")
        return 0
    if "--status" in argv:
        print(json.dumps(_read_state(), ensure_ascii=False, indent=2))
        print("BRAVE_API_KEY:", "có" if os.environ.get("BRAVE_API_KEY") else "không")
        print("GOOGLE_CSE:", "có" if os.environ.get("GOOGLE_CSE_API_KEY") and os.environ.get("GOOGLE_CSE_CX") else "không")
        print("BING_API_KEY:", "có (nhưng API đã ngừng)" if os.environ.get("BING_API_KEY") else "không")
        return 0

    query = " ".join(a for a in argv if not a.startswith("--")).strip()
    if not query:
        print(
            "Usage:\n"
            "  python scripts/search.py \"cảng cạn Long Bình Đồng Nai\"\n"
            "  python scripts/search.py --status\n"
            "  python scripts/search.py --reset-state",
            file=sys.stderr,
        )
        return 2

    try:
        hits, provider = search(query, count=10)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(f"# provider={provider} query={query!r}")
    print(json.dumps([asdict(h) for h in hits], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
