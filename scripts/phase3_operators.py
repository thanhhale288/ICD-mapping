"""
P3.1 — Lấy danh mục mạng lưới ICD của các nhà khai thác.

Đọc trang mạng lưới / hệ thống ICD của:
  Tân Cảng Sài Gòn, Gemadept, VIMC, TBS, Transimex, Hateco, Sotrans.

Ghép tên ICD ↔ URL → data/ung_vien.csv (loai_nguon=operator_network)
Tóm tắt → data/operator_networks.json

Usage:
  python3 scripts/phase3_operators.py
  python3 scripts/phase3_operators.py --no-cache
  python3 scripts/phase3_operators.py --max-tier 1
"""

from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch import HEADERS, TIMEOUT_S, fetch  # noqa: E402
from match import (  # noqa: E402
    IcdKey,
    load_keys,
    normalize_name,
    normalize_text,
    strip_accents,
)

UNG_VIEN = ROOT / "data" / "ung_vien.csv"
OUT_JSON = ROOT / "data" / "operator_networks.json"
KEYS_CSV = ROOT / "data" / "icd_keys.csv"

VN_TZ = timezone(timedelta(hours=7))

UNG_VIEN_COLUMNS = [
    "stt",
    "ten_icd",
    "url",
    "nguon",
    "loai_nguon",
    "query",
    "provider",
    "title",
    "snippet",
    "operator",
    "fetched_at",
]

NAME_MATCH_THRESHOLD = 88

# Bỏ link menu / tin chung không phải trang ICD
SKIP_URL_HINTS = (
    "/en/",
    "/tin-tuc",
    "/news/",
    "/article/",
    "javascript:",
    "mailto:",
    "#",
)

# trang chỉ dùng để xác nhận seed — không parse heading/đoạn văn
SEED_ONLY_URL_HINTS = (
    "/press-center/",
    "/tin-tuc",
    "/news/",
)

ICD_NAME_HINT = re.compile(
    r"(?:icd|cảng\s*cạn|cang\s*can|điểm\s*thông\s*quan|"
    r"diem\s*thong\s*quan|inland\s*container)",
    re.I,
)


@dataclass
class SeedIcd:
    name: str
    url: str
    prefer_stt: int | None = None
    location_hint: str = ""


@dataclass
class OperatorSpec:
    key: str
    display: str
    network_urls: list[str]
    seeds: list[SeedIcd] = field(default_factory=list)
    # từ khóa khớp chu_dau_tu / don_vi_khai_thac
    owner_hints: list[str] = field(default_factory=list)
    # token bắt buộc trong tên scraped (seed không cần)
    brand_tokens: list[str] = field(default_factory=list)
    # host được giữ khi scrape link con (không www.)
    allowed_hosts: list[str] = field(default_factory=list)
    # trang catalog/tin ngành — chỉ dùng seed, không parse danh mục quốc gia
    catalog_urls: list[str] = field(default_factory=list)


# --- Danh mục URL đã xác minh (WebSearch/WebFetch 30/10/2026) ---
OPERATORS: list[OperatorSpec] = [
    OperatorSpec(
        key="tan_cang_sai_gon",
        display="Tân Cảng Sài Gòn",
        network_urls=[
            # listing /cang-cong-ty đôi khi 500 — vẫn thử; seed bù
            "https://saigonnewport.com.vn/cang-cong-ty",
            "https://saigonnewport.com.vn/",
        ],
        owner_hints=["tan cang", "saigon newport", "tancang"],
        brand_tokens=["tan cang", "tancang", "song than", "long binh", "nhon trach", "que vo", "moc bai", "ha nam", "hai phong"],
        allowed_hosts=[
            "saigonnewport.com.vn",
            "icdlongbinh.com",
            "icdsongthan.com.vn",
        ],
        seeds=[
            SeedIcd(
                "ICD Tân Cảng Hải Phòng",
                "https://saigonnewport.com.vn/cang-cong-ty/tan-cang-hai-phong-icd",
                prefer_stt=4,
                location_hint="Hải Phòng",
            ),
            SeedIcd(
                "ICD Tân Cảng Quế Võ",
                "https://saigonnewport.com.vn/cang-cong-ty/tan-cang-que-vo-icd",
                prefer_stt=8,
                location_hint="Bắc Ninh",
            ),
            SeedIcd(
                "ICD Tân Cảng Hà Nam",
                "https://saigonnewport.com.vn/cang-cong-ty/tan-cang-dong-van-ha-nam-icd",
                prefer_stt=12,
                location_hint="Ninh Bình",
            ),
            SeedIcd(
                "ICD Tân Cảng Nhơn Trạch",
                "https://saigonnewport.com.vn/cang-cong-ty/tan-cang-nhon-trach-icd",
                prefer_stt=14,
                location_hint="Đồng Nai",
            ),
            SeedIcd(
                "ICD Tân Cảng Long Bình",
                "https://saigonnewport.com.vn/cang-cong-ty/tan-cang-long-binh-icd",
                prefer_stt=15,
                location_hint="Đồng Nai",
            ),
            SeedIcd(
                "ICD Tân Cảng Long Bình (website riêng)",
                "https://icdlongbinh.com/",
                prefer_stt=15,
                location_hint="Đồng Nai",
            ),
            SeedIcd(
                "Cảng cạn Tân Cảng Mộc Bài",
                "https://saigonnewport.com.vn/cang-cong-ty/tan-cang-tay-ninh-icd",
                prefer_stt=19,
                location_hint="Tây Ninh",
            ),
            SeedIcd(
                "ICD Tân Cảng Sóng Thần",
                "https://saigonnewport.com.vn/cang-cong-ty/icd-tan-cang-song-than",
                prefer_stt=106,
                location_hint="TP. Hồ Chí Minh",
            ),
            SeedIcd(
                "ICD Tân Cảng Sóng Thần (website riêng)",
                "https://www.icdsongthan.com.vn/",
                prefer_stt=106,
                location_hint="TP. Hồ Chí Minh",
            ),
        ],
    ),
    OperatorSpec(
        key="gemadept",
        display="Gemadept",
        network_urls=[
            "https://www.gemadept.com.vn/he-sinh-thai-cang-logistics/",
            "https://www.gemadept.com.vn/dich-vu/khai-thac-cang/",
        ],
        owner_hints=["gemadept", "nam dinh vu", "phuoc long", "nam hai"],
        brand_tokens=["gemadept", "nam hai", "phuoc long", "nam dinh vu", "pip"],
        allowed_hosts=[
            "gemadept.com.vn",
            "pip.gemadept.com.vn",
            "nhi.gemadept.com.vn",
        ],
        seeds=[
            SeedIcd(
                "Nam Hải ICD",
                "https://www.gemadept.com.vn/nam-hai-icd/",
                location_hint="Hải Phòng",
            ),
            SeedIcd(
                "Phước Long ICD",
                "https://www.gemadept.com.vn/phuoc-long-icd/",
                location_hint="TP. Hồ Chí Minh",
            ),
            SeedIcd(
                "Phước Long ICD (PIP)",
                "https://pip.gemadept.com.vn/gioi-thieu/tong-quan/",
                location_hint="TP. Hồ Chí Minh",
            ),
            SeedIcd(
                "Cụm Cảng / ICD Nam Đình Vũ",
                "https://www.gemadept.com.vn/he-sinh-thai-cang-logistics/",
                prefer_stt=7,
                location_hint="Hải Phòng",
            ),
        ],
    ),
    OperatorSpec(
        key="vimc",
        display="VIMC",
        network_urls=[
            "https://vimclogistics.com/trang-gioi-thieu",
            "https://www.vimclogistics.com/",
            # tin ngành liệt kê nhiều ICD quốc gia — catalog, không scrape danh mục
            "https://vimc.co/chuan-hoa-mo-hinh-cang-can-tai-viet-nam/",
        ],
        owner_hints=["vimc", "vinalines"],
        brand_tokens=["vimc", "dong pho moi", "lao cai", "vinalines"],
        allowed_hosts=["vimclogistics.com", "vimclogistics.com.vn", "vimc.co"],
        catalog_urls=[
            "https://vimc.co/chuan-hoa-mo-hinh-cang-can-tai-viet-nam/",
        ],
        seeds=[
            SeedIcd(
                "Cảng cạn Đông Phố Mới (Lào Cai)",
                "https://vimclogistics.com/trang-gioi-thieu",
                prefer_stt=1,
                location_hint="Lào Cai",
            ),
            SeedIcd(
                "ICD Đông Phố Mới – tin VIMC",
                "https://vimc.co/thu-tuong-chinh-phu-pham-minh-chinh-khao-sat-cang-can-dong-pho-moi-tai-lao-cai/",
                prefer_stt=1,
                location_hint="Lào Cai",
            ),
        ],
    ),
    OperatorSpec(
        key="tbs",
        display="TBS",
        network_urls=[
            "https://www.tbsgroup.vn/linh-vuc-hoat-dong/logistics-va-cang/",
            "https://www.tbsgroup.vn/press-center/mo-rong-he-thong-icd-tan-van/",
        ],
        owner_hints=["tbs", "thai binh"],
        brand_tokens=["tbs", "tan van"],
        allowed_hosts=["tbsgroup.vn"],
        catalog_urls=[
            "https://www.tbsgroup.vn/press-center/mo-rong-he-thong-icd-tan-van/",
        ],
        seeds=[
            SeedIcd(
                "ICD TBS Tân Vạn",
                "https://www.tbsgroup.vn/linh-vuc-hoat-dong/logistics-va-cang/",
                prefer_stt=107,
                location_hint="TP. Hồ Chí Minh",
            ),
            SeedIcd(
                "ICD TBS Tân Vạn (mở rộng kho bãi)",
                "https://www.tbsgroup.vn/press-center/mo-rong-he-thong-icd-tan-van/",
                prefer_stt=107,
                location_hint="TP. Hồ Chí Minh",
            ),
        ],
    ),
    OperatorSpec(
        key="transimex",
        display="Transimex",
        network_urls=[
            "https://www.transimex.com.vn/",
            "https://www.transimex.com.vn/dich-vu/dich-vu-cang-icd-390.html",
        ],
        owner_hints=["transimex", "tms"],
        brand_tokens=["transimex", "tms"],
        allowed_hosts=["transimex.com.vn"],
        seeds=[
            SeedIcd(
                "ICD Transimex",
                "https://www.transimex.com.vn/dich-vu/dich-vu-cang-icd-390.html",
                location_hint="TP. Hồ Chí Minh",
            ),
        ],
    ),
    OperatorSpec(
        key="hateco",
        display="Hateco",
        network_urls=[
            "https://hatecologistics.vn/",
            "https://hatecologistics.vn/cang-can-long-bien/",
        ],
        owner_hints=["hateco"],
        brand_tokens=["hateco", "long bien"],
        allowed_hosts=["hatecologistics.vn"],
        seeds=[
            SeedIcd(
                "Cảng cạn Long Biên (ICD Hateco)",
                "https://hatecologistics.vn/cang-can-long-bien/",
                prefer_stt=11,
                location_hint="Hà Nội",
            ),
            SeedIcd(
                "ICD Long Biên – Hateco Logistics",
                "https://hatecologistics.vn/",
                prefer_stt=11,
                location_hint="Hà Nội",
            ),
            SeedIcd(
                "Bảng giá dịch vụ ICD Long Biên",
                "https://hatecologistics.vn/bang-gia-dich-vu-icd-long-bien/",
                prefer_stt=11,
                location_hint="Hà Nội",
            ),
        ],
    ),
    OperatorSpec(
        key="sotrans",
        display="Sotrans",
        network_urls=[
            "https://sotransgroup.vn/linh-vuc-hoat-dong/khai-thac-cang/",
            "https://sotrans.com.vn/dich-vu/khai-thac-cang/sotrans-icd/",
        ],
        owner_hints=["sotrans", "sowatco"],
        brand_tokens=["sotrans", "sowatco"],
        allowed_hosts=["sotransgroup.vn", "sotrans.com.vn", "icdsotrans.com.vn"],
        seeds=[
            SeedIcd(
                "ICD SOTRANS",
                "https://sotrans.com.vn/dich-vu/khai-thac-cang/sotrans-icd/",
                location_hint="TP. Hồ Chí Minh",
            ),
            SeedIcd(
                "SOWATCO Long Bình",
                "https://sotrans.com.vn/dich-vu/khai-thac-cang/sotrans-icd/",
                prefer_stt=98,
                location_hint="TP. Hồ Chí Minh",
            ),
        ],
    ),
]

NOISE_NAMES = {
    "icd",
    "cang icd",
    "cang icd transimex",
    "cang can",
    "diem thong quan noi dia",
    "diem thong quan noi dia icd",
    "dich vu cang icd",
    "dich vu",
    "chi tiet",
    "xem them",
    "tweet",
    "share",
    "facebook",
    "vi",
    "home",
    "trang chu",
    "he thong cang sotrans group",
    "cac dich vu tai sotrans icd",
    "bai chua container",
}


@dataclass
class FoundIcd:
    name: str
    url: str
    source_url: str
    title: str = ""
    snippet: str = ""
    prefer_stt: int | None = None
    location_hint: str = ""
    from_seed: bool = False


def _now_iso() -> str:
    return datetime.now(VN_TZ).isoformat(timespec="seconds")


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _looks_icd_anchor(text: str, href: str) -> bool:
    blob = f"{text} {href}"
    if ICD_NAME_HINT.search(blob):
        return True
    # slug kiểu *-icd, tan-cang-*-icd
    path = urlparse(href).path.lower()
    if re.search(r"(?:^|/)(?:icd|.*-icd)(?:/|$)", path):
        return True
    if "cang-can" in path or "cangcan" in path.replace("-", ""):
        return True
    return False


def _should_skip_url(url: str) -> bool:
    low = url.lower()
    return any(h in low for h in SKIP_URL_HINTS)


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _host_allowed(url: str, allowed: list[str]) -> bool:
    if not allowed:
        return True
    h = _host(url)
    return any(h == a or h.endswith("." + a) for a in allowed)


_FACILITY_TITLE = re.compile(
    r"^(?:(?:icd|cảng\s*cạn|cang\s*can|cụm\s*cảng(?:\s*/\s*icd)?)\s+.+"
    r"|sowatco\s+.+"
    r"|.+\s+icd(?:\s*\(.*\))?)$",
    re.I,
)


def _looks_facility_title(name: str) -> bool:
    """Tên dạng tiêu đề cơ sở, không phải câu văn."""
    n = _clean_facility_name(name)
    if len(n) > 70 or n.count(" ") > 10:
        return False
    # không kết thúc bằng dấu câu câu dài
    if n.endswith((".", ",", ";", ":")):
        return False
    nn = normalize_name(n)
    # câu có động từ / bổ ngữ dài
    if any(
        tok in nn.split()
        for tok in (
            "la",
            "duoc",
            "co",
            "voi",
            "trong",
            "cua",
            "cac",
            "va",
            "cho",
            "tu",
            "den",
            "khong",
            "ngay",
            "cang",
        )
    ) and len(nn.split()) > 5:
        # cho phép "cang can X" / "icd X" ngắn
        if not (
            nn.startswith("cang can ")
            or nn.startswith("icd ")
            or nn.endswith(" icd")
        ):
            return False
        if len(nn.split()) > 8:
            return False
    return bool(_FACILITY_TITLE.match(n) or _FACILITY_TITLE.match(nn))


def _is_noise_name(name: str) -> bool:
    nn = normalize_name(name)
    if not nn or len(nn) < 4:
        return True
    if nn in NOISE_NAMES:
        return True
    # email / handle
    if "@" in name or name.lower().startswith(("info@", "http")):
        return True
    # menu / UI / social
    if nn in {
        "chi tiet",
        "xem them",
        "doc tiep",
        "tweet",
        "share",
        "khai thac cang",
        "sotrans icd",
    } or nn.startswith("chi tiet"):
        return True
    # generic service label without facility toponym
    if nn in {"dich vu cang icd", "cang icd"} or nn.startswith("dich vu cang"):
        return True
    if nn == "diem thong quan noi dia" or nn.startswith("diem thong quan noi dia"):
        return True
    if len(name) > 85 or name.count(" ") > 12:
        return True
    if name.lower().startswith(("bộ ", "bao ", "báo ", "quy chuẩn", "mở rộng hệ thống")):
        return True
    if nn.startswith("mo rong he thong"):
        return True
    # scraped phải giống tiêu đề cơ sở (seed bỏ qua kiểm tra này ở chỗ khác)
    return False


def _clean_facility_name(name: str) -> str:
    """Bỏ số thứ tự '01. Phước Long ICD' → 'Phước Long ICD'."""
    name = _clean_text(name)
    name = re.sub(r"^\d+\s*[.)]\s*", "", name)
    return name.strip(" -–—|")


def fetch_html(url: str) -> tuple[str, str]:
    """Lấy HTML thô để parse link (fetch.py chỉ giữ text)."""
    try:
        with httpx.Client(
            headers=HEADERS,
            follow_redirects=True,
            timeout=TIMEOUT_S,
            verify=True,
        ) as client:
            resp = client.get(url)
            if resp.status_code >= 400:
                return "", url
            return resp.text, str(resp.url)
    except httpx.HTTPError:
        try:
            with httpx.Client(
                headers=HEADERS,
                follow_redirects=True,
                timeout=TIMEOUT_S,
                verify=False,
            ) as client:
                resp = client.get(url)
                return resp.text, str(resp.url)
        except httpx.HTTPError:
            return "", url


def parse_icd_links(
    html: str,
    base_url: str,
    *,
    allowed_hosts: list[str] | None = None,
    headings_only_short: bool = True,
) -> list[FoundIcd]:
    """Trích cặp (tên, url) từ HTML trang mạng lưới — ưu tiên <a href> ICD."""
    soup = BeautifulSoup(html or "", "lxml")
    found: list[FoundIcd] = []
    seen: set[tuple[str, str]] = set()
    allowed = allowed_hosts or []

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        abs_url = urljoin(base_url, href).split("#")[0]
        if _should_skip_url(abs_url):
            continue
        if not _host_allowed(abs_url, allowed):
            continue
        text = _clean_facility_name(a.get_text(" ", strip=True))
        if not text or len(text) < 3:
            text = _clean_facility_name(a.get("title") or a.get("aria-label") or "")
        if not _looks_icd_anchor(text, abs_url):
            continue
        if not text:
            slug = urlparse(abs_url).path.rstrip("/").split("/")[-1]
            text = _clean_facility_name(slug.replace("-", " "))
        if _is_noise_name(text):
            continue
        key = (normalize_name(text), abs_url.rstrip("/").lower())
        if key in seen:
            continue
        seen.add(key)
        found.append(
            FoundIcd(
                name=text,
                url=abs_url,
                source_url=base_url,
                snippet=text[:240],
            )
        )

    # Chỉ h1/h2 ngắn — tránh li/p kéo cả đoạn văn
    if headings_only_short:
        for tag in soup.find_all(["h1", "h2"]):
            text = _clean_facility_name(tag.get_text(" ", strip=True))
            if not text or len(text) > 60:
                continue
            if not ICD_NAME_HINT.search(text):
                continue
            if _is_noise_name(text):
                continue
            if text.lower().startswith(("các ", "cac ", "dịch ", "dich ", "khai ")):
                continue
            key = (normalize_name(text), base_url.rstrip("/").lower())
            if key in seen:
                continue
            seen.add(key)
            found.append(
                FoundIcd(
                    name=text,
                    url=base_url,
                    source_url=base_url,
                    snippet=text[:240],
                )
            )
    return found


def parse_icd_names_from_text(text: str, base_url: str) -> list[FoundIcd]:
    """Dự phòng khi không có HTML: bắt cụm 'ICD …' / 'Cảng cạn …'."""
    found: list[FoundIcd] = []
    seen: set[str] = set()
    pat = re.compile(
        r"((?:ICD|Cảng\s*cạn)\s+[A-Za-zÀ-ỹ0-9][^,.;\n()]{2,50})",
        re.I,
    )
    for m in pat.finditer(text or ""):
        name = _clean_facility_name(m.group(1))
        if _is_noise_name(name):
            continue
        nn = normalize_name(name)
        if nn in seen:
            continue
        seen.add(nn)
        found.append(
            FoundIcd(
                name=name,
                url=base_url,
                source_url=base_url,
                snippet=name[:240],
            )
        )
    return found


def _owner_score(key: IcdKey, owner_hints: list[str]) -> float:
    if not owner_hints:
        return 0.0
    blob = normalize_name(f"{key.chu_dau_tu} {key.don_vi_khai_thac}")
    best = 0.0
    for h in owner_hints:
        hn = normalize_name(h)
        if not hn:
            continue
        if hn in blob:
            best = max(best, 100.0)
        else:
            best = max(best, float(fuzz.partial_ratio(hn, blob)))
    return best


def _location_score(key: IcdKey, location_hint: str) -> float:
    if not location_hint:
        return 0.0
    hint = normalize_text(location_hint)
    if not hint:
        return 0.0
    parts = [
        normalize_text(key.tinh_moi),
        normalize_text(key.tinh_cu),
        normalize_text(key.huyen_cu),
        *key.dia_ban_norm,
    ]
    best = 0.0
    for p in parts:
        if not p:
            continue
        if hint in p or p in hint:
            best = max(best, 100.0)
        else:
            best = max(best, float(fuzz.partial_ratio(hint, p)))
    return best


def _name_score_pair(scraped: str, known: str) -> float:
    """Chấm tên; tránh đảo token ngắn (nam hai ↔ ha nam)."""
    if not scraped or not known:
        return 0.0
    if scraped == known or known in scraped or scraped in known:
        return 100.0
    # partial/token_set chỉ khi ≥ 3 token hoặc độ dài đủ
    if len(scraped.split()) <= 2 or len(known.split()) <= 2:
        # yêu cầu chứa nhau theo biên từ
        if re.search(rf"(?<!\w){re.escape(known)}(?!\w)", scraped):
            return 100.0
        if re.search(rf"(?<!\w){re.escape(scraped)}(?!\w)", known):
            return 100.0
        # fuzz cao nhưng token đảo → loại
        ts = float(fuzz.token_set_ratio(scraped, known))
        if ts >= 95 and set(scraped.split()) == set(known.split()):
            return ts
        return 0.0
    return max(
        float(fuzz.token_set_ratio(scraped, known)),
        float(fuzz.partial_ratio(scraped, known)),
    )


def match_name_to_stt(
    name: str,
    keys: dict[int, IcdKey],
    *,
    prefer_stt: int | None = None,
    location_hint: str = "",
    owner_hints: list[str] | None = None,
) -> int | None:
    """Khớp tên ICD scraped với icd_keys; ưu tiên địa bàn + chủ đầu tư khi trùng tên."""
    if prefer_stt and prefer_stt in keys:
        return prefer_stt

    nn = normalize_name(name)
    if not nn or len(nn) < 3 or _is_noise_name(name):
        return None

    owner_hints = owner_hints or []
    candidates: list[tuple[float, int]] = []

    for stt, key in keys.items():
        best_name = 0.0
        for kn in key.names_norm:
            best_name = max(best_name, _name_score_pair(nn, kn))
        if best_name < NAME_MATCH_THRESHOLD:
            continue
        loc = _location_score(key, location_hint)
        own = _owner_score(key, owner_hints)
        # Tên ngắn (≤2 token): bắt buộc địa bàn hoặc chủ
        if len(nn.split()) <= 2 and loc < 70 and own < 70:
            continue
        score = best_name + 0.15 * loc + 0.2 * own
        if key.nhom_trung and loc < 60 and own < 60:
            score -= 12
        candidates.append((score, stt))

    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x[0], x[1]))
    top_score, top_stt = candidates[0]
    # từ chối khớp yếu còn lại
    if top_score < NAME_MATCH_THRESHOLD:
        return None
    return top_stt


def _snippet_from_text(text: str, name: str, width: int = 180) -> str:
    if not text:
        return ""
    raw = text.replace("\n", " ")
    idx = strip_accents(raw).lower().find(strip_accents(name).lower()[:20])
    if idx < 0:
        return _clean_text(raw)[:width]
    start = max(0, idx - 40)
    return _clean_text(raw[start : start + width])


def fetch_operator(
    op: OperatorSpec,
    keys: dict[int, IcdKey],
    *,
    use_cache: bool = True,
    max_tier: int = 3,
) -> dict[str, Any]:
    """Mở trang mạng lưới + gộp seed; trả summary 1 operator."""
    fetched_at = _now_iso()
    page_results: list[dict[str, Any]] = []
    scraped: list[FoundIcd] = []

    catalog_set = {u.rstrip("/").lower() for u in op.catalog_urls}

    for url in op.network_urls:
        print(f"  → fetch {url}", flush=True)
        is_catalog = url.rstrip("/").lower() in catalog_set
        try:
            r = fetch(url, stt=op.key, use_cache=use_cache, max_tier=max_tier)
        except Exception as e:  # noqa: BLE001
            page_results.append(
                {
                    "url": url,
                    "status": "ERROR",
                    "http_code": None,
                    "title": "",
                    "reason": str(e),
                    "catalog": is_catalog,
                }
            )
            continue
        page_results.append(
            {
                "url": url,
                "status": r.status,
                "http_code": r.http_code,
                "title": r.title,
                "reason": r.reason,
                "tier": r.tier,
                "final_url": r.final_url,
                "catalog": is_catalog,
            }
        )
        if r.status not in ("MỞ_ĐƯỢC", "LỖI_SSL_MỞ_ĐƯỢC"):
            print(f"    ! {r.status}: {r.reason}", flush=True)
            continue
        if is_catalog or any(h in url.lower() for h in SEED_ONLY_URL_HINTS):
            print(f"    ✓ {r.status} — seed-only/catalog (skip parse)", flush=True)
            continue
        html, html_final = fetch_html(r.final_url or url)
        links = parse_icd_links(
            html,
            html_final or r.final_url or url,
            allowed_hosts=op.allowed_hosts,
            headings_only_short=True,
        )
        if not links:
            # text fallback hẹp: chỉ tiêu đề "ICD …" / "Cảng cạn …" ngắn
            links = [
                x
                for x in parse_icd_names_from_text(r.text or "", r.final_url or url)
                if _looks_facility_title(x.name) and not _is_noise_name(x.name)
            ]
        for item in links:
            item.title = r.title
            item.snippet = item.snippet or _snippet_from_text(r.text, item.name)
        scraped.extend(links)
        print(f"    ✓ {r.status} — {len(links)} ICD/link", flush=True)

    # Gộp theo (tên chuẩn hóa, url) — cùng URL có thể liệt kê nhiều ICD
    by_key: dict[tuple[str, str], FoundIcd] = {}
    for item in scraped:
        k = (normalize_name(item.name), item.url.rstrip("/").lower())
        by_key[k] = item
    for seed in op.seeds:
        k = (normalize_name(seed.name), seed.url.rstrip("/").lower())
        if k in by_key:
            cur = by_key[k]
            if seed.prefer_stt and not cur.prefer_stt:
                cur.prefer_stt = seed.prefer_stt
            if seed.location_hint and not cur.location_hint:
                cur.location_hint = seed.location_hint
            cur.from_seed = True
            # seed luôn thắng tên scraped (normalize_name bỏ "ICD" → dễ trùng)
            cur.name = seed.name
            cur.snippet = cur.snippet or f"seed công khai — {op.display}"
        else:
            by_key[k] = FoundIcd(
                name=seed.name,
                url=seed.url,
                source_url=seed.url,
                prefer_stt=seed.prefer_stt,
                location_hint=seed.location_hint,
                from_seed=True,
                title="",
                snippet=f"seed công khai — {op.display}",
            )

    def _url_specificity(u: str) -> int:
        path = urlparse(u).path.rstrip("/")
        score = path.count("/")
        low = u.lower()
        if any(x in low for x in ("-icd", "/icd", "cang-can", "nam-hai", "phuoc-long")):
            score += 5
        if low.rstrip("/").endswith(
            (
                "he-sinh-thai-cang-logistics",
                "khai-thac-cang",
                "logistics-va-cang",
            )
        ):
            score -= 3
        return score

    # Bỏ bản sao scraped trỏ về trang listing khi đã có URL con cùng tên
    def _has_brand(name: str) -> bool:
        if not op.brand_tokens:
            return True
        nn = normalize_name(name)
        return any(normalize_name(t) in nn for t in op.brand_tokens)

    candidates: list[FoundIcd] = []
    for item in by_key.values():
        if item.from_seed:
            if _is_noise_name(item.name):
                continue
            candidates.append(item)
            continue
        if _is_noise_name(item.name) or not _looks_facility_title(item.name):
            continue
        if not _has_brand(item.name):
            continue
        if " voi " in f" {normalize_name(item.name)} ":
            continue
        if not (
            ICD_NAME_HINT.search(item.name) or _looks_icd_anchor(item.name, item.url)
        ):
            continue
        candidates.append(item)

    by_name: dict[str, list[FoundIcd]] = {}
    for item in candidates:
        by_name.setdefault(normalize_name(item.name), []).append(item)

    kept_items: list[FoundIcd] = []
    for _nk, group in by_name.items():
        # luôn giữ seed; với scraped chỉ giữ URL cụ thể nhất nếu không có seed
        seeds = [g for g in group if g.from_seed]
        scraped = [g for g in group if not g.from_seed]
        if seeds:
            kept_items.extend(seeds)
            continue
        scraped.sort(key=lambda g: _url_specificity(g.url), reverse=True)
        if scraped:
            kept_items.append(scraped[0])

    # cùng URL đã có seed → bỏ scraped trùng trang
    seed_urls = {i.url.rstrip("/").lower() for i in kept_items if i.from_seed}
    kept_items = [
        i
        for i in kept_items
        if i.from_seed or i.url.rstrip("/").lower() not in seed_urls
    ]

    icds_out: list[dict[str, Any]] = []
    ung_vien_rows: list[dict[str, str]] = []

    for item in sorted(kept_items, key=lambda x: normalize_name(x.name)):
        stt = match_name_to_stt(
            item.name,
            keys,
            prefer_stt=item.prefer_stt,
            location_hint=item.location_hint,
            owner_hints=op.owner_hints,
        )
        ten_keys = keys[stt].ten_chinh if stt and stt in keys else item.name
        icds_out.append(
            {
                "name": item.name,
                "url": item.url,
                "matched_stt": stt,
                "matched_ten": ten_keys if stt else None,
                "from_seed": item.from_seed,
                "source_url": item.source_url,
            }
        )
        ung_vien_rows.append(
            {
                "stt": str(stt) if stt else "",
                "ten_icd": ten_keys if stt else item.name,
                "url": item.url,
                "nguon": item.source_url,
                "loai_nguon": "operator_network",
                "query": op.display,
                "provider": op.display,
                "title": item.title or item.name,
                "snippet": item.snippet
                or (f"Mạng lưới {op.display}: {item.name}"),
                "operator": op.display,
                "fetched_at": fetched_at,
            }
        )

    blocked = [
        p
        for p in page_results
        if p.get("status") not in ("MỞ_ĐƯỢC", "LỖI_SSL_MỞ_ĐƯỢC")
    ]
    return {
        "operator": op.display,
        "operator_key": op.key,
        "network_urls": op.network_urls,
        "pages": page_results,
        "scrape_failed": bool(blocked) and not any(
            p.get("status") in ("MỞ_ĐƯỢC", "LỖI_SSL_MỞ_ĐƯỢC") for p in page_results
        ),
        "blocked_or_failed_pages": blocked,
        "icds": icds_out,
        "ung_vien_rows": ung_vien_rows,
        "fetched_at": fetched_at,
    }


def _load_existing_ung_vien() -> list[dict[str, str]]:
    if not UNG_VIEN.exists():
        return []
    with UNG_VIEN.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _row_quality(r: dict[str, str]) -> tuple[int, int]:
    """Ưu tiên dòng có STT và tên rõ (không generic)."""
    stt_bonus = 1 if r.get("stt") else 0
    name = r.get("ten_icd") or ""
    name_bonus = len(normalize_name(name))
    if _is_noise_name(name):
        name_bonus = -1
    return (stt_bonus, name_bonus)


def write_ung_vien(new_rows: list[dict[str, str]]) -> int:
    """Ghi/ghép ung_vien.csv: thay các dòng operator_network cũ, giữ dòng khác."""
    existing = _load_existing_ung_vien()
    kept = [r for r in existing if (r.get("loai_nguon") or "") != "operator_network"]
    # khử trùng theo (url, operator, stt|tên) — giữ bản tên tốt hơn
    best: dict[tuple[str, str, str], dict[str, str]] = {}
    for r in new_rows:
        if _is_noise_name(r.get("ten_icd") or ""):
            continue
        url = (r.get("url") or "").rstrip("/").lower()
        op = r.get("operator") or ""
        stt = r.get("stt") or ""
        # cùng URL+STT (hoặc cùng URL khi chưa khớp) → giữ tên tốt hơn
        key = (url, op, stt or normalize_name(r.get("ten_icd") or ""))
        prev = best.get(key)
        if prev is None or _row_quality(r) > _row_quality(prev):
            best[key] = {c: r.get(c, "") for c in UNG_VIEN_COLUMNS}

    deduped = sorted(
        best.values(),
        key=lambda r: (r.get("operator") or "", int(r["stt"] or 0), r.get("ten_icd") or ""),
    )
    all_rows = kept + deduped
    UNG_VIEN.parent.mkdir(parents=True, exist_ok=True)
    with UNG_VIEN.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=UNG_VIEN_COLUMNS)
        w.writeheader()
        w.writerows(all_rows)
    return len(deduped)


def main(argv: list[str]) -> int:
    use_cache = "--no-cache" not in argv
    max_tier = 3
    if "--max-tier" in argv:
        i = argv.index("--max-tier")
        max_tier = int(argv[i + 1])

    print("P3.1 — mạng lưới nhà khai thác ICD", flush=True)
    keys = load_keys(KEYS_CSV)
    print(f"Đã nạp {len(keys)} ICD từ icd_keys.csv", flush=True)

    summaries: list[dict[str, Any]] = []
    all_rows: list[dict[str, str]] = []

    for op in OPERATORS:
        print(f"\n=== {op.display} ===", flush=True)
        summary = fetch_operator(
            op, keys, use_cache=use_cache, max_tier=max_tier
        )
        summaries.append({k: v for k, v in summary.items() if k != "ung_vien_rows"})
        all_rows.extend(summary["ung_vien_rows"])
        n_match = sum(1 for x in summary["icds"] if x.get("matched_stt"))
        print(
            f"  → {len(summary['icds'])} ICD "
            f"({n_match} khớp STT; scrape_failed={summary['scrape_failed']})",
            flush=True,
        )

    n_written = write_ung_vien(all_rows)
    out = {
        "phase": "P3.1",
        "generated_at": _now_iso(),
        "operators_covered": len(summaries),
        "candidate_rows": n_written,
        "operators": summaries,
    }
    OUT_JSON.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"\nĐã ghi {n_written} dòng → {UNG_VIEN.relative_to(ROOT)}", flush=True)
    print(f"Tóm tắt → {OUT_JSON.relative_to(ROOT)}", flush=True)

    failed = [s["operator"] for s in summaries if s.get("scrape_failed")]
    partial = [
        s["operator"]
        for s in summaries
        if s.get("blocked_or_failed_pages") and not s.get("scrape_failed")
    ]
    if failed:
        print(f"Scrape FAIL (đã seed): {', '.join(failed)}", flush=True)
    if partial:
        print(f"Một số trang lỗi (có trang OK): {', '.join(partial)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
