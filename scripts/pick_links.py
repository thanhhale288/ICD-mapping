"""
P3.5 — Chọn link cột G theo thứ tự ưu tiên (plan §10.6 / P3.5).

Ưu tiên:
  1. Website chính thức đã xác minh (trang riêng ICD)
  2. Văn bản nhà nước riêng về ICD
  3. Báo chí chính thống riêng về ICD, mới nhất, ưu tiên ≤24 tháng
Các link còn lại → nguon_kiem_chung (pipe-separated).

Đầu ra: data/link_chon.csv (đúng 128 dòng, 1/STT).

Usage:
  python3 scripts/pick_links.py
  python3 scripts/pick_links.py test
"""

from __future__ import annotations

import csv
import re
import sys
import tempfile
import unittest
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

KEYS_CSV = ROOT / "data" / "icd_keys.csv"
UNG_VIEN_CSV = ROOT / "data" / "ung_vien.csv"
LINK_CHECK_CSV = ROOT / "data" / "link_check.csv"
UNG_VIEN_CHECK_CSV = ROOT / "data" / "ung_vien_check.csv"
WEBSITE_VERIFY_CSV = ROOT / "data" / "website_verify.csv"
OUT_CSV = ROOT / "data" / "link_chon.csv"

VN_TZ = timezone(timedelta(hours=7))
MONTHS_24 = timedelta(days=730)  # ~24 months

# QĐ 979 — không bao giờ chọn cho cột G
QD979_DOCID = "208522"

OK_STATUSES = frozenset({"MỞ_ĐƯỢC_KHỚP", "ĐÃ_XÁC_MINH_TAY"})
OK_SSL_STATUS = "LỖI_SSL_MỞ_ĐƯỢC"
BANNED_STATUS = "CHỈ_KHỚP_CHUNG"

VERIFY_OFFICIAL = "chính thức – đã xác minh"
VERIFY_MAYBE = "có khả năng – cần xác nhận"
VERIFY_REJECT = "loại"

COLUMNS = [
    "stt",
    "ten",
    "url_chon",
    "loai_nguon",
    "do_uu_tien",  # 1 | 2 | 3 | (rỗng nếu không chọn)
    "trang_thai_verify",
    "ly_do",
    "nguon_kiem_chung",  # URL|URL|...
    "ghi_chu",
]

# --- Phân loại nguồn theo domain / loai_nguon ---

GOV_HOST_HINTS = (
    ".gov.vn",
    "chinhphu.vn",
    "congbao.chinhphu.vn",
    "vanban.chinhphu.vn",
    "moc.gov.vn",
    "mt.gov.vn",
    "bxd.gov.vn",
    "haiquan.gov.vn",
    "customs.gov.vn",
    "vimawa.gov.vn",
    "luatvietnam.vn",
    "thuvienphapluat.vn",
    "caselaw.vn",
    "logistics.gov.vn",
)

PRESS_HOST_HINTS = (
    "baochinhphu.vn",
    "baodauthau.vn",
    "baoxaydung.vn",
    "baodautu.vn",
    "baophapluat.vn",
    "baohaiquanvietnam.vn",
    "nhandan.vn",
    "vnexpress.net",
    "tuoitre.vn",
    "thanhnien.vn",
    "vietnamnet.vn",
    "dantri.com.vn",
    "nhipcaudautu.vn",
    "reatimes.vn",
    "vneconomy.vn",
    "cafef.vn",
    "enternews.vn",
    "banduong.vn",
    "laodong.vn",
    "tienphong.vn",
    "vov.gov.vn",
    "bao",
)

# Trang doanh nghiệp / ICD (không phải gov/báo) — nhận là website cột G
COMPANY_HOST_HINTS = (
    "saigonnewport.com.vn",
    "tancang.com.vn",
    "gemadept.com.vn",
    "hatecologistics.vn",
    "hateco.vn",
    "vimc.co",
    "vimclogistics.com",
    "icdlongbinh.com",
    "icdlongbinh.com.vn",
    "icdsongthan.com.vn",
    "cangtanchi.vn",
    "transimex.com",
    "transimex.com.vn",
    "sotrans.com.vn",
    "tbs.com.vn",
    "tbslogistics",
    "dragonteam.us",
)

LOAI_WEBSITE = frozenset(
    {
        "website",
        "website_doanh_nghiep",
        "operator_network",
        "operator",
        "fanpage",
    }
)
LOAI_GOV = frozenset(
    {
        "van_ban",
        "vanban",
        "chinh_phu",
        "gov",
        "quyet_dinh",
        "cong_bao",
        "hai_quan",
    }
)
LOAI_PRESS = frozenset({"bao_chi", "bao", "press", "tin_tuc", "news"})


@dataclass
class Candidate:
    stt: int
    url: str
    loai_nguon: str = ""
    title: str = ""
    snippet: str = ""
    nguon: str = ""
    check_status: str = ""
    khop_ten: str = ""
    khop_dia_ban: str = ""
    text_path: str = ""
    screenshot: str = ""
    fetched_at: str = ""
    verify: str = ""
    source_date: date | None = None
    priority: int = 99  # 1/2/3 sau khi xếp
    notes: list[str] = field(default_factory=list)

    def to_sort_key(self) -> tuple:
        # thấp hơn = tốt hơn; ngày mới hơn (lớn hơn) tốt hơn với báo
        d = self.source_date or date.min
        return (self.priority, -d.toordinal(), self.url)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_keys(path: Path = KEYS_CSV) -> dict[int, str]:
    out: dict[int, str] = {}
    for row in _read_csv(path):
        try:
            stt = int(str(row.get("stt") or "").strip())
        except ValueError:
            continue
        out[stt] = (row.get("ten_chinh") or "").strip()
    return out


def normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    # bỏ fragment; giữ query
    p = urlparse(u)
    return f"{p.scheme}://{p.netloc.lower()}{p.path}".rstrip("/") + (
        f"?{p.query}" if p.query else ""
    )


def is_qd979_url(url: str) -> bool:
    u = (url or "").lower()
    if "docid=208522" in u.replace(" ", ""):
        return True
    try:
        p = urlparse(url)
        qs = parse_qs(p.query)
        vals = qs.get("docid") or qs.get("DocId") or []
        if any(str(v).strip() == QD979_DOCID for v in vals):
            return True
    except Exception:
        pass
    if "979-qd-ttg" in u or "979/qd-ttg" in u:
        # chỉ cấm khi rõ là QĐ 979 quy hoạch hệ thống (không phải QĐ mở riêng)
        if "cang-can" in u or "quy-hoach" in u or "thuvienphapluat" in u:
            return True
    return False


def host_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def classify_loai(loai_raw: str, url: str) -> str:
    """Trả về: website | van_ban | bao_chi | khac."""
    loai = (loai_raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if loai in LOAI_WEBSITE or loai.startswith("website") or loai.startswith("operator"):
        return "website"
    if loai in LOAI_GOV or "van_ban" in loai or loai.startswith("qd"):
        return "van_ban"
    if loai in LOAI_PRESS or "bao" in loai:
        return "bao_chi"

    host = host_of(url)
    path = (urlparse(url).path or "").lower()
    if any(h in host for h in COMPANY_HOST_HINTS) or host.startswith("icd"):
        return "website"
    if any(h in host for h in GOV_HOST_HINTS) or "/van-ban/" in path or "quyet-dinh" in path:
        # baochinhphu / báo tỉnh là báo, không phải văn bản
        if "baochinhphu" in host or host.startswith("bao") or "bao" in host.split(".")[0]:
            return "bao_chi"
        return "van_ban"
    if any(h in host for h in PRESS_HOST_HINTS) or host.startswith("bao"):
        return "bao_chi"
    return "khac"


def parse_date_guess(*texts: str) -> date | None:
    """Bóc ngày từ URL / tiêu đề / snippet / fetched_at."""
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    # ISO
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", blob)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # dd/mm/yyyy or dd-mm-yyyy
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", blob)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    # yyyymmdd in URL (baochinhphu style ...102250324...)
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", blob)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            try:
                return date(y, mo, d)
            except ValueError:
                pass
    # năm đơn
    m = re.search(r"\b(20(?:2[4-9]|[3-9]\d))\b", blob)
    if m:
        try:
            return date(int(m.group(1)), 1, 1)
        except ValueError:
            pass
    return None


def check_status_ok(status: str, khop_ten: str = "") -> bool:
    s = (status or "").strip()
    if s in OK_STATUSES:
        return True
    if s == OK_SSL_STATUS:
        # chỉ giữ khi khớp tên (match ok)
        return str(khop_ten).strip() in ("1", "true", "True", "yes")
    return False


def load_check_index(
    paths: Iterable[Path],
) -> dict[tuple[int, str], dict[str, str]]:
    """(stt, normalized_url) → row kiểm link mới nhất."""
    idx: dict[tuple[int, str], dict[str, str]] = {}
    for path in paths:
        for row in _read_csv(path):
            url = (row.get("url") or row.get("final_url") or "").strip()
            if not url:
                continue
            stt_raw = (row.get("stt") or "").strip()
            if not stt_raw.isdigit():
                continue
            stt = int(stt_raw)
            key = (stt, normalize_url(url))
            idx[key] = row
            # cũng index theo URL không kèm stt để fallback
            idx[(0, normalize_url(url))] = row
    return idx


def load_verify_index(path: Path = WEBSITE_VERIFY_CSV) -> dict[tuple[int, str], str]:
    """(stt, norm_url) → kết luận xác minh."""
    out: dict[tuple[int, str], str] = {}
    for row in _read_csv(path):
        url = (row.get("url") or "").strip()
        if not url:
            continue
        stt_raw = (row.get("stt") or "").strip()
        stt = int(stt_raw) if stt_raw.isdigit() else 0
        ket = (
            row.get("ket_luan")
            or row.get("trang_thai_verify")
            or row.get("trang_thai")
            or row.get("conclusion")
            or ""
        ).strip()
        if ket:
            out[(stt, normalize_url(url))] = ket
            out[(0, normalize_url(url))] = ket
    return out


def _lookup(
    idx: dict[tuple[int, str], Any], stt: int, url: str
) -> Any | None:
    nu = normalize_url(url)
    if (stt, nu) in idx:
        return idx[(stt, nu)]
    if (0, nu) in idx:
        return idx[(0, nu)]
    return None


def collect_candidates(
    *,
    ung_vien_path: Path = UNG_VIEN_CSV,
    check_paths: list[Path] | None = None,
    verify_path: Path = WEBSITE_VERIFY_CSV,
) -> dict[int, list[Candidate]]:
    if check_paths is None:
        check_paths = [LINK_CHECK_CSV, UNG_VIEN_CHECK_CSV]
    check_idx = load_check_index(check_paths)
    verify_idx = load_verify_index(verify_path)

    by_stt: dict[int, list[Candidate]] = {}
    seen: set[tuple[int, str]] = set()

    for row in _read_csv(ung_vien_path):
        stt_raw = (row.get("stt") or "").strip()
        if not stt_raw.isdigit():
            continue
        stt = int(stt_raw)
        url = (row.get("url") or "").strip()
        if not url:
            continue
        nu = normalize_url(url)
        key = (stt, nu)
        if key in seen:
            continue
        seen.add(key)

        chk = _lookup(check_idx, stt, url) or {}
        status = (chk.get("status") or "").strip()
        khop = (chk.get("khop_ten") or "").strip()
        khop_db = (chk.get("khop_dia_ban") or "").strip()
        verify = (_lookup(verify_idx, stt, url) or "").strip()
        loai = classify_loai(row.get("loai_nguon") or "", url)
        # Không dùng fetched_at làm ngày nguồn bài (chỉ là lúc kiểm link)
        src_date = parse_date_guess(
            row.get("title") or "",
            row.get("snippet") or "",
            url,
        )
        cand = Candidate(
            stt=stt,
            url=url,
            loai_nguon=loai,
            title=(row.get("title") or chk.get("title") or "").strip(),
            snippet=(row.get("snippet") or "").strip(),
            nguon=(row.get("nguon") or chk.get("nguon") or "").strip(),
            check_status=status,
            khop_ten=khop,
            khop_dia_ban=khop_db,
            text_path=(chk.get("text_path") or "").strip(),
            screenshot=(chk.get("screenshot") or "").strip(),
            fetched_at=(chk.get("fetched_at") or row.get("fetched_at") or "").strip(),
            verify=verify,
            source_date=src_date,
        )
        by_stt.setdefault(stt, []).append(cand)

    # Ứng viên chỉ có trong link_check (không nằm ung_vien) — vẫn xét nếu khớp STT
    for path in check_paths:
        for row in _read_csv(path):
            stt_raw = (row.get("stt") or "").strip()
            if not stt_raw.isdigit():
                continue
            stt = int(stt_raw)
            url = (row.get("url") or "").strip()
            if not url:
                continue
            nu = normalize_url(url)
            if (stt, nu) in seen:
                continue
            seen.add((stt, nu))
            loai = classify_loai(row.get("nguon") or "", url)
            verify = (_lookup(verify_idx, stt, url) or "").strip()
            cand = Candidate(
                stt=stt,
                url=url,
                loai_nguon=loai,
                title=(row.get("title") or "").strip(),
                nguon=(row.get("nguon") or "").strip(),
                check_status=(row.get("status") or "").strip(),
                khop_ten=(row.get("khop_ten") or "").strip(),
                khop_dia_ban=(row.get("khop_dia_ban") or "").strip(),
                text_path=(row.get("text_path") or "").strip(),
                screenshot=(row.get("screenshot") or "").strip(),
                fetched_at=(row.get("fetched_at") or "").strip(),
                verify=verify,
                source_date=parse_date_guess(row.get("title") or "", url),
            )
            by_stt.setdefault(stt, []).append(cand)

    return by_stt


def _title_focuses_icd(c: Candidate, ten: str) -> bool:
    """Tiêu đề/URL có vẻ nói riêng về ICD (không chỉ danh mục chung)."""
    blob = f"{c.title} {c.url}".lower()
    # loại bài danh mục / tổng hợp nhiều cảng
    ban_phrases = (
        "danh mục",
        "danh sach",
        "danh sách",
        "19 cảng",
        "17 cảng",
        "14 cảng",
        "cong bo danh muc",
        "công bố danh mục",
        "bo sung danh muc",
        "bổ sung danh mục",
        "them cang can",
        "thêm cảng cạn",
        "bo sung",
        "bổ sung",
        "2 cảng cạn",
        "hai cảng cạn",
        "cac cang can",
        "các cảng cạn",
    )
    if any(p in blob for p in ban_phrases):
        return False
    core = re.sub(
        r"^(cảng\s*cạn|icd|cang\s*can)\s*",
        "",
        (ten or "").lower(),
        flags=re.I,
    )
    core = re.sub(r"\s*\(.*?\)\s*", " ", core).strip()
    tokens = [t for t in re.split(r"[\s\-–,]+", core) if t]
    weak = {
        "tan",
        "tân",
        "cang",
        "cảng",
        "can",
        "icd",
        "giai",
        "doan",
        "đoạn",
        "moi",
        "mới",
        "pha",
    }
    # Token đặc trưng (≥3 ký tự, không phải từ chung) — tránh "Tân" khớp nhầm Tân Chi
    strong = [t for t in tokens if len(t) >= 3 and t not in weak]
    if not strong:
        return False
    hit = sum(1 for t in strong if t in blob)
    # Ưu tiên cụm 2 token cuối (vd. "hà nam", "thạnh phước")
    if len(tokens) >= 2:
        pair = f"{tokens[-2]} {tokens[-1]}"
        if pair in blob:
            hit += 1
    return hit >= 1 and ("cảng cạn" in blob or "icd" in blob or "cang can" in blob)


def assign_priority(
    c: Candidate, today: date | None = None, *, ten: str = ""
) -> int | None:
    """Gán do_uu_tien 1/2/3 hoặc None nếu không đủ điều kiện cột G."""
    today = today or datetime.now(VN_TZ).date()

    if is_qd979_url(c.url):
        c.notes.append("cấm QĐ 979")
        return None

    chi_khop_exception = False
    if c.check_status == BANNED_STATUS:
        # Bài/VB tiêu đề riêng ICD + khớp tên/địa bàn: sidebar danh mục hay
        # kích hoạt CHỈ_KHỚP_CHUNG giả — vẫn cho vào G kèm ghi chú P4.
        if (
            c.khop_ten in ("1", "true", "True")
            and c.khop_dia_ban in ("1", "true", "True")
            and ten
            and _title_focuses_icd(c, ten)
        ):
            chi_khop_exception = True
            c.notes.append("CHỈ_KHỚP_CHUNG nhưng tiêu đề riêng ICD – cần P4")
        else:
            c.notes.append("CHỈ_KHỚP_CHUNG")
            return None
    elif not check_status_ok(c.check_status, c.khop_ten):
        c.notes.append(f"status={c.check_status or 'chưa kiểm'}")
        return None

    # Website: ưu tiên 1 chỉ khi đã xác minh chính thức.
    # "có khả năng"/chưa verify → không thắng văn bản/báo; fallback ở pick_for_stt.
    if c.loai_nguon == "website":
        v = c.verify.lower()
        if VERIFY_OFFICIAL in v or v in ("chinh_thuc", "official", "da_xac_minh"):
            return 1
        if VERIFY_REJECT in v or v == "loai":
            c.notes.append("website loại")
            return None
        c.notes.append(f"website chưa xác minh ({c.verify or 'chưa verify'})")
        return None

    if c.loai_nguon == "van_ban":
        # Chỉ lọc khi có tiêu đề thật (tránh phá fixture/test và URL không title)
        if ten and len(c.title or "") >= 25 and not _title_focuses_icd(c, ten):
            c.notes.append("tiêu đề VB không khớp ICD đích")
            return None
        return 2

    if c.loai_nguon == "bao_chi":
        if ten and len(c.title or "") >= 25 and not _title_focuses_icd(c, ten):
            c.notes.append("tiêu đề báo không khớp ICD đích")
            return None
        if c.source_date and c.source_date >= today - MONTHS_24:
            return 3
        if c.source_date:
            c.notes.append(f"báo cũ hơn 24 tháng ({c.source_date.isoformat()})")
        else:
            c.notes.append("báo không rõ ngày")
        return 3

    # khac đã khớp: không ưu tiên G trừ fallback
    c.notes.append("loại nguồn khác")
    return None


def pick_for_stt(
    stt: int,
    ten: str,
    candidates: list[Candidate],
    *,
    today: date | None = None,
) -> dict[str, str]:
    today = today or datetime.now(VN_TZ).date()
    eligible: list[Candidate] = []
    evidence: list[Candidate] = []

    for c in candidates:
        prio = assign_priority(c, today=today, ten=ten)
        if prio is None:
            # vẫn có thể đưa vào nguồn kiểm chứng nếu status ok (trừ QĐ979 / CHỈ_KHỚP_CHUNG)
            if (
                not is_qd979_url(c.url)
                and c.check_status != BANNED_STATUS
                and check_status_ok(c.check_status, c.khop_ten)
            ):
                evidence.append(c)
            elif (
                not is_qd979_url(c.url)
                and c.check_status
                and c.check_status != BANNED_STATUS
            ):
                # chưa kiểm / không khớp — không vào kiểm chứng cột G
                pass
            continue
        c.priority = prio
        eligible.append(c)

    if not eligible and not candidates:
        return {
            "stt": str(stt),
            "ten": ten,
            "url_chon": "",
            "loai_nguon": "",
            "do_uu_tien": "",
            "trang_thai_verify": "",
            "ly_do": "chưa có ứng viên",
            "nguon_kiem_chung": "",
            "ghi_chu": "",
        }

    if not eligible and evidence:
        # Fallback: MỞ_ĐƯỢC_KHỚP nhưng website chưa verify chính thức / loại khác.
        # Ưu tiên website công ty → còn lại; Phase 4 cần xác nhận.
        def _ev_key(c: Candidate) -> tuple:
            is_web = 0 if c.loai_nguon == "website" else 1
            maybe = 0 if (VERIFY_MAYBE in (c.verify or "") or "có khả năng" in (c.verify or "")) else 1
            return (is_web, maybe, c.url)

        evidence.sort(key=_ev_key)
        best = evidence[0]
        best.priority = 1 if best.loai_nguon == "website" else 3
        rest = [c.url for c in evidence[1:]]
        note = "; ".join(best.notes) if best.notes else (best.verify or "đã khớp")
        return {
            "stt": str(stt),
            "ten": ten,
            "url_chon": best.url,
            "loai_nguon": best.loai_nguon,
            "do_uu_tien": str(best.priority),
            "trang_thai_verify": best.verify,
            "ly_do": f"fallback MỞ_ĐƯỢC_KHỚP – {note} (cần P4)",
            "nguon_kiem_chung": "|".join(dict.fromkeys(rest)),
            "ghi_chu": "chọn từ evidence vì chưa có website đã xác minh / VB / báo đủ điều kiện",
        }

    if not eligible:
        # có ứng viên nhưng không đạt điều kiện cột G
        reasons = []
        for c in candidates[:5]:
            note = "; ".join(c.notes) if c.notes else (c.check_status or "không đạt")
            reasons.append(f"{c.url[:60]}→{note}")
        ly = "không có link MỞ_ĐƯỢC_KHỚP đủ điều kiện cột G"
        if all(
            not c.check_status or c.check_status == "chưa kiểm"
            for c in candidates
        ):
            ly = "chưa có ứng viên đạt kiểm link"
        return {
            "stt": str(stt),
            "ten": ten,
            "url_chon": "",
            "loai_nguon": "",
            "do_uu_tien": "",
            "trang_thai_verify": "",
            "ly_do": ly,
            "nguon_kiem_chung": "|".join(
                dict.fromkeys(c.url for c in evidence)
            ),
            "ghi_chu": "; ".join(reasons)[:500],
        }

    eligible.sort(key=lambda c: c.to_sort_key())
    best = eligible[0]
    rest_urls = [
        c.url
        for c in eligible[1:] + evidence
        if normalize_url(c.url) != normalize_url(best.url)
    ]
    # unique preserve order
    seen_u: set[str] = set()
    uniq_rest: list[str] = []
    for u in rest_urls:
        nu = normalize_url(u)
        if nu in seen_u:
            continue
        seen_u.add(nu)
        uniq_rest.append(u)

    ly = {
        1: "website chính thức đã xác minh (trang riêng ICD)",
        2: "văn bản nhà nước riêng về ICD",
        3: "báo chí chính thống riêng về ICD",
    }.get(best.priority, "đã chọn")
    if best.priority == 3 and best.source_date:
        ly += f"; ngày nguồn {best.source_date.isoformat()}"
    if best.notes:
        ly += " | " + "; ".join(best.notes)

    return {
        "stt": str(stt),
        "ten": ten,
        "url_chon": best.url,
        "loai_nguon": best.loai_nguon,
        "do_uu_tien": str(best.priority),
        "trang_thai_verify": best.verify,
        "ly_do": ly,
        "nguon_kiem_chung": "|".join(uniq_rest),
        "ghi_chu": best.check_status
        + (f"; ssl_ok_khớp" if best.check_status == OK_SSL_STATUS else ""),
    }


def run_pick(
    *,
    keys_path: Path = KEYS_CSV,
    ung_vien_path: Path = UNG_VIEN_CSV,
    check_paths: list[Path] | None = None,
    verify_path: Path = WEBSITE_VERIFY_CSV,
    out_path: Path = OUT_CSV,
    today: date | None = None,
) -> list[dict[str, str]]:
    keys = load_keys(keys_path)
    if not keys:
        # fallback 1..128 nếu thiếu keys
        keys = {i: "" for i in range(1, 129)}
    by_stt = collect_candidates(
        ung_vien_path=ung_vien_path,
        check_paths=check_paths,
        verify_path=verify_path,
    )
    rows: list[dict[str, str]] = []
    for stt in range(1, 129):
        ten = keys.get(stt, "")
        rows.append(
            pick_for_stt(stt, ten, by_stt.get(stt, []), today=today)
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in COLUMNS})
    return rows


# ---------- tests ----------


class PickLinksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="pick_links_"))
        self.keys = self.tmp / "icd_keys.csv"
        with self.keys.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["stt", "ten_chinh"])
            w.writeheader()
            for i in range(1, 129):
                w.writerow({"stt": str(i), "ten_chinh": f"ICD {i}"})

    def _write(self, name: str, fieldnames: list[str], rows: list[dict]) -> Path:
        p = self.tmp / name
        with p.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        return p

    def test_empty_ung_vien_gives_128_chua_co(self) -> None:
        out = self.tmp / "link_chon.csv"
        rows = run_pick(
            keys_path=self.keys,
            ung_vien_path=self.tmp / "missing_ung_vien.csv",
            check_paths=[self.tmp / "missing_check.csv"],
            verify_path=self.tmp / "missing_verify.csv",
            out_path=out,
        )
        self.assertEqual(len(rows), 128)
        self.assertTrue(all(r["ly_do"] == "chưa có ứng viên" for r in rows))
        self.assertTrue(all(r["url_chon"] == "" for r in rows))

    def test_never_pick_qd979_or_chi_khop_chung(self) -> None:
        ung = self._write(
            "ung_vien.csv",
            ["stt", "url", "loai_nguon", "title", "snippet"],
            [
                {
                    "stt": "20",
                    "url": "https://vanban.chinhphu.vn/?docid=208522&pageid=27160",
                    "loai_nguon": "van_ban",
                    "title": "QĐ 979",
                    "snippet": "",
                },
                {
                    "stt": "20",
                    "url": "https://example.com/chung-nhieu-icd",
                    "loai_nguon": "van_ban",
                    "title": "danh sách",
                    "snippet": "",
                },
            ],
        )
        chk = self._write(
            "check.csv",
            ["stt", "url", "status", "khop_ten", "title", "fetched_at"],
            [
                {
                    "stt": "20",
                    "url": "https://vanban.chinhphu.vn/?docid=208522&pageid=27160",
                    "status": "MỞ_ĐƯỢC_KHỚP",
                    "khop_ten": "1",
                    "title": "QĐ 979",
                    "fetched_at": "2026-10-01",
                },
                {
                    "stt": "20",
                    "url": "https://example.com/chung-nhieu-icd",
                    "status": "CHỈ_KHỚP_CHUNG",
                    "khop_ten": "1",
                    "title": "chung",
                    "fetched_at": "2026-10-01",
                },
            ],
        )
        out = self.tmp / "out.csv"
        rows = run_pick(
            keys_path=self.keys,
            ung_vien_path=ung,
            check_paths=[chk],
            verify_path=self.tmp / "no_verify.csv",
            out_path=out,
        )
        r20 = next(r for r in rows if r["stt"] == "20")
        self.assertEqual(r20["url_chon"], "")
        self.assertNotIn("208522", r20["nguon_kiem_chung"])

    def test_priority_website_over_gov_over_press(self) -> None:
        ung = self._write(
            "ung_vien.csv",
            ["stt", "url", "loai_nguon", "title", "snippet"],
            [
                {
                    "stt": "5",
                    "url": "https://baochinhphu.vn/bo-gtvt-cong-bo-20250115.htm",
                    "loai_nguon": "bao_chi",
                    "title": "Báo 15/01/2025",
                    "snippet": "sản lượng",
                },
                {
                    "stt": "5",
                    "url": "https://mt.gov.vn/van-ban/qd-2200.html",
                    "loai_nguon": "van_ban",
                    "title": "QĐ 2200",
                    "snippet": "",
                },
                {
                    "stt": "5",
                    "url": "https://icd-hoangthanh.vn/gioi-thieu",
                    "loai_nguon": "website",
                    "title": "Website ICD",
                    "snippet": "",
                },
            ],
        )
        chk = self._write(
            "check.csv",
            ["stt", "url", "status", "khop_ten", "title", "fetched_at"],
            [
                {
                    "stt": "5",
                    "url": "https://baochinhphu.vn/bo-gtvt-cong-bo-20250115.htm",
                    "status": "MỞ_ĐƯỢC_KHỚP",
                    "khop_ten": "1",
                    "title": "Báo",
                    "fetched_at": "2026-10-01",
                },
                {
                    "stt": "5",
                    "url": "https://mt.gov.vn/van-ban/qd-2200.html",
                    "status": "MỞ_ĐƯỢC_KHỚP",
                    "khop_ten": "1",
                    "title": "QĐ",
                    "fetched_at": "2026-10-01",
                },
                {
                    "stt": "5",
                    "url": "https://icd-hoangthanh.vn/gioi-thieu",
                    "status": "MỞ_ĐƯỢC_KHỚP",
                    "khop_ten": "1",
                    "title": "Web",
                    "fetched_at": "2026-10-01",
                },
            ],
        )
        ver = self._write(
            "verify.csv",
            ["stt", "url", "ket_luan"],
            [
                {
                    "stt": "5",
                    "url": "https://icd-hoangthanh.vn/gioi-thieu",
                    "ket_luan": VERIFY_OFFICIAL,
                }
            ],
        )
        rows = run_pick(
            keys_path=self.keys,
            ung_vien_path=ung,
            check_paths=[chk],
            verify_path=ver,
            out_path=self.tmp / "out.csv",
            today=date(2026, 10, 30),
        )
        r5 = next(r for r in rows if r["stt"] == "5")
        self.assertEqual(r5["url_chon"], "https://icd-hoangthanh.vn/gioi-thieu")
        self.assertEqual(r5["do_uu_tien"], "1")
        self.assertIn("mt.gov.vn", r5["nguon_kiem_chung"])
        self.assertIn("baochinhphu", r5["nguon_kiem_chung"])

        # bỏ verify → chọn văn bản
        rows2 = run_pick(
            keys_path=self.keys,
            ung_vien_path=ung,
            check_paths=[chk],
            verify_path=self.tmp / "no_v.csv",
            out_path=self.tmp / "out2.csv",
            today=date(2026, 10, 30),
        )
        r5b = next(r for r in rows2 if r["stt"] == "5")
        self.assertEqual(r5b["url_chon"], "https://mt.gov.vn/van-ban/qd-2200.html")
        self.assertEqual(r5b["do_uu_tien"], "2")

    def test_ssl_ok_when_khop_ten(self) -> None:
        ung = self._write(
            "ung_vien.csv",
            ["stt", "url", "loai_nguon", "title", "snippet"],
            [
                {
                    "stt": "1",
                    "url": "https://vimawa.gov.vn/vi/node/999",
                    "loai_nguon": "van_ban",
                    "title": "QĐ riêng",
                    "snippet": "",
                }
            ],
        )
        chk = self._write(
            "check.csv",
            ["stt", "url", "status", "khop_ten", "title", "fetched_at"],
            [
                {
                    "stt": "1",
                    "url": "https://vimawa.gov.vn/vi/node/999",
                    "status": OK_SSL_STATUS,
                    "khop_ten": "1",
                    "title": "ok",
                    "fetched_at": "2026-10-01",
                }
            ],
        )
        rows = run_pick(
            keys_path=self.keys,
            ung_vien_path=ung,
            check_paths=[chk],
            verify_path=self.tmp / "nv.csv",
            out_path=self.tmp / "out.csv",
        )
        r1 = next(r for r in rows if r["stt"] == "1")
        self.assertEqual(r1["url_chon"], "https://vimawa.gov.vn/vi/node/999")
        self.assertEqual(r1["do_uu_tien"], "2")

    def test_is_qd979_helper(self) -> None:
        self.assertTrue(
            is_qd979_url("https://vanban.chinhphu.vn/?docid=208522&pageid=27160")
        )
        self.assertFalse(is_qd979_url("https://mt.gov.vn/van-ban/1549.html"))


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "test":
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromTestCase(PickLinksTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        print(
            f"\n{result.testsRun} tests, "
            f"{len(result.failures)} failures, "
            f"{len(result.errors)} errors",
            flush=True,
        )
        return 0 if result.wasSuccessful() else 1

    rows = run_pick()
    n_pick = sum(1 for r in rows if r["url_chon"])
    n_empty = 128 - n_pick
    print(f"Wrote {OUT_CSV} — {n_pick} có link, {n_empty} trống", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
