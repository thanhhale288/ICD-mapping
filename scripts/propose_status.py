"""
P3.7 — Máy đề xuất trạng thái hoạt động (Phụ lục A + C.5).

Đọc link_chon + text_path từ link_check / ung_vien_check, đề xuất 1/6 trạng thái.
QĐ mở đơn thuần ≠ đang hoạt động (cần bằng chứng vận hành).

Đầu ra: data/trang_thai_de_xuat.csv (128 dòng).

Usage:
  python3 scripts/propose_status.py
  python3 scripts/propose_status.py test
"""

from __future__ import annotations

import csv
import re
import sys
import tempfile
import unittest
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

KEYS_CSV = ROOT / "data" / "icd_keys.csv"
LINK_CHON_CSV = ROOT / "data" / "link_chon.csv"
LINK_CHECK_CSV = ROOT / "data" / "link_check.csv"
UNG_VIEN_CHECK_CSV = ROOT / "data" / "ung_vien_check.csv"
OUT_CSV = ROOT / "data" / "trang_thai_de_xuat.csv"
OVERRIDE_CSV = ROOT / "data" / "trang_thai_override.csv"  # sửa tay, có nguồn

VN_TZ = timezone(timedelta(hours=7))

STATUS_ACTIVE = "Đang hoạt động"
STATUS_OPENED = "Đã công bố mở, chưa xác nhận đang khai thác"
STATUS_BUILDING = "Đang xây dựng / chuẩn bị đầu tư"
STATUS_PLANNED = "Chưa triển khai (mới quy hoạch)"
STATUS_STOPPED = "Đã ngừng / di dời"
STATUS_UNKNOWN = "Chưa đủ thông tin"

COLUMNS = [
    "stt",
    "ten",
    "trang_thai",
    "cau_trich",
    "url",
    "ngay_nguon",
    "evidence_path",
    "ly_do",
    "do_tin_cay",  # cao | trung_binh | thap
]

# --- Từ khóa (Phụ lục C.5) ---

ACTIVE_PATTERNS = [
    r"đón (?:container|chuyến hàng|chuyến tàu|lô hàng)[^.]{0,30}đầu tiên",
    r"khai trương",
    r"đưa vào khai thác",
    r"đi vào hoạt động",
    r"di vao hoat dong",
    r"khánh thành",
    r"khanh thanh",
    r"sản lượng.{0,40}TEU",
    r"san luong.{0,40}teu",
    r"tiếp nhận chuyến hàng",
    r"tiep nhan chuyen hang",
    r"đang khai thác",
    r"dang khai thac",
    r"biểu giá",
    r"bieu gia",
    r"lịch khai thác",
    r"lich khai thac",
    r"địa điểm làm thủ tục",
    r"địa điểm làm thủ tục hải quan",
    r"làm thủ tục hải quan tại",
]

BUILDING_PATTERNS = [
    r"khởi công",
    r"khoi cong",
    r"chấp thuận chủ trương đầu tư",
    r"chap thuan chu truong dau tu",
    r"giải phóng mặt bằng",
    r"giai phong mat bang",
    r"đang thi công",
    r"dang thi cong",
    r"chuẩn bị đầu tư",
    r"chuan bi dau tu",
]

OPENED_PATTERNS = [
    r"công bố mở",
    r"cong bo mo",
    r"quyết định.{0,30}mở cảng cạn",
    r"quyet dinh.{0,30}mo cang can",
    r"công bố mở cảng cạn",
    # QĐ công bố theo NĐ 38/2014 (trước 2017) dùng "công bố cảng cạn <tên>" — chỉ nhận
    # dạng văn bản QĐ ("Nay công bố cảng cạn", "Quyết định … công bố cảng cạn").
    r"nay công bố cảng cạn",
    r"quyết định [0-9/]+/qđ-bgtvt công bố cảng cạn",
]

PLANNED_PATTERNS = [
    # "quy hoạch" chỉ tính khi gần ICD/cảng cạn/logistics
    r"quy ho[aạ]ch[\s\S]{0,120}?(?:ICD|cảng cạn|cang can|logistics)",
    r"(?:ICD|cảng cạn|cang can|logistics)[\s\S]{0,120}?quy ho[aạ]ch",
    # QĐ/NQ chỉ tính khi có ICD/cảng cạn/logistics trong ~150 ký tự
    r"\d+/(?:QĐ|NQ)-(?:UBND|HĐND|TTg)[\s\S]{0,150}?(?:ICD|cảng cạn|cang can|logistics)",
    r"(?:ICD|cảng cạn|cang can|logistics)[\s\S]{0,150}?\d+/(?:QĐ|NQ)-(?:UBND|HĐND|TTg)",
    r"định hướng[\s\S]{0,80}?(?:ICD|cảng cạn|cang can|logistics)",
]

ICD_CONTEXT = re.compile(r"\bICD\b|cảng cạn|cang can|logistics|cảng nội địa|kho bãi|cảng khô", re.I)

_NAME_STRIP = re.compile(r"\(.*?\)|cảng cạn|cang can|\bICD\b|[–-].*$", re.I)


def core_name(ten: str) -> str:
    n = _NAME_STRIP.sub(" ", ten or "")
    return re.sub(r"\s+", " ", n).strip()


ADJ_START = re.compile(r"^\W*(?:cảng cạn|cảng|icd)\b", re.I)


def split_sents(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])(?:\[\d+\])*\s+|\n+", text) if x.strip()]


def focus_text(text: str, ten: str, allow_adjacent: bool = False) -> str:
    """Chỉ giữ câu chứa tên ICD VÀ từ ngữ cảnh ICD/cảng cạn/logistics —
    bỏ menu/sidebar/tin không liên quan và địa danh trùng tên.
    allow_adjacent (chỉ cho link MỞ_ĐƯỢC_KHỚP): thêm đúng 1 câu NGAY SAU câu
    neo nếu câu đó bắt đầu bằng "Cảng"/"Cảng cạn"/"ICD"."""
    name = core_name(ten)
    if not text or len(re.sub(r"[^A-Za-zÀ-ỹ]", "", name)) < 3:
        return text
    sents = split_sents(text)
    keep: list[str] = []
    for i, x in enumerate(sents):
        if name.lower() in x.lower() and ICD_CONTEXT.search(x):
            keep.append(x)
            if allow_adjacent and i + 1 < len(sents) and ADJ_START.search(sents[i + 1]) \
                    and name.lower() not in sents[i + 1].lower():
                keep.append(sents[i + 1])
    return " ".join(dict.fromkeys(keep))


HEDGE = re.compile(r"(?:sẽ|dự kiến|mục tiêu|chưa|kế hoạch|phấn đấu|nhằm|kỳ vọng|đề xuất|không|đầu tư xây dựng|cùng với đó là)\W+(?:\w+\W+){0,6}$", re.I)
NEW_ACTIVE = [r"đón (?:container|chuyến hàng|chuyến tàu|lô hàng)[^.]{0,30}đầu tiên", r"khai trương", r"đưa vào khai thác"]


def active_hit(text: str, ten: str = "") -> bool:
    """Từ khóa vận hành chỉ tính khi KHÔNG có từ phủ định/tương lai ngay trước
    (sẽ, dự kiến, mục tiêu, chưa…). Cụm mới (khai trương, đưa vào khai thác,
    đón … đầu tiên) còn phải có tên ICD trong cùng câu."""
    name = core_name(ten).lower()
    for x in split_sents(text):
        for pat in ACTIVE_PATTERNS:
            for m in re.finditer(pat, x, re.I):
                if HEDGE.search(x[max(0, m.start() - 60):m.start()]):
                    continue
                clause = re.split(r"[,;:–]", x[:m.start()])[-1]
                if re.search(r"\bkhi\b|\bnếu\b", clause, re.I):
                    continue  # mệnh đề điều kiện: "nhất là khi ... đưa vào khai thác"
                if re.match(r"\W*(?:sẽ|là mục tiêu)", x[m.end():], re.I):
                    continue
                if pat in NEW_ACTIVE and name and name not in x[max(0, m.start() - 60):m.end() + 60].lower():
                    continue
                return True
    return False


_YEAR = re.compile(r"\b(20\d\d)\b")
_PHASE = re.compile(r"giai đoạn\s*(20\d\d)\s*[-–]\s*(20\d\d)", re.I)


def split_future_building(text: str, today: date) -> tuple[str, str]:
    """Tách câu có từ khóa xây dựng nhưng là kế hoạch tương lai
    (mọi năm trong câu > năm hiện tại, hoặc 'giai đoạn 20xx–20xx' bắt đầu sau năm nay).
    Trả về (text_còn_lại, các_câu_kế_hoạch_tương_lai)."""
    rest, fut = [], []
    yr = re.compile(r"\b(20\d\d)(?:\s*[-–]\s*20\d\d)?\b")
    for x in split_sents(text):
        ms = [m for p in BUILDING_PATTERNS for m in re.finditer(p, x, re.I)]
        if ms:
            def is_future(m):
                before = yr.findall(x[:m.start()])
                if before:  # mốc năm gần nhất phía trước (đầu khoảng nếu là giai đoạn)
                    return int(before[-1]) > today.year
                after = yr.findall(x[m.end():m.end() + 60])
                return bool(after) and int(after[0]) > today.year
            if all(is_future(m) for m in ms):
                fut.append(x)
                continue
        rest.append(x)
    return " ".join(rest), " ".join(fut)


MATCHED_STATUSES = {"MỞ_ĐƯỢC_KHỚP", "ĐÃ_XÁC_MINH_TAY"}


def is_matched_row(row: dict[str, str]) -> bool:
    st = (row.get("status") or "").strip()
    if st in MATCHED_STATUSES:
        return True
    if st == "LỖI_SSL_MỞ_ĐƯỢC":
        def truthy(v: str | None) -> bool:
            return (v or "").strip().lower() in ("1", "true", "yes", "có", "co")
        return truthy(row.get("khop_ten")) and truthy(row.get("khop_dia_ban"))
    return False

STOPPED_PATTERNS = [
    r"đã ngừng",
    r"da ngung",
    r"ngừng hoạt động",
    r"ngung hoat dong",
    r"di dời",
    r"di doi",
    r"giải thể(?!\s*thao)",
    r"giai the(?!\s*thao)",
]


@dataclass
class Evidence:
    url: str
    text: str
    text_path: str
    screenshot: str
    source_date: date | None
    check_status: str = ""
    # True khi link khớp ICD (MỞ_ĐƯỢC_KHỚP / xác minh tay / SSL lỗi nhưng khớp tên+địa bàn).
    matched: bool = True


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
    return (url or "").strip().rstrip("/").lower()


def parse_date_guess(*texts: str) -> date | None:
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", blob)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", blob)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", blob)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            try:
                return date(y, mo, d)
            except ValueError:
                pass
    return None


def read_evidence_text(path_str: str) -> str:
    if not path_str:
        return ""
    p = Path(path_str)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def load_check_by_url(
    paths: Iterable[Path],
) -> dict[str, dict[str, str]]:
    idx: dict[str, dict[str, str]] = {}
    for path in paths:
        for row in _read_csv(path):
            url = (row.get("url") or "").strip()
            st = (row.get("stt") or "").strip()
            # Cùng 1 URL có thể được chấm cho nhiều STT (khớp STT này, không khớp STT kia):
            # khóa (stt, url) là chính; khóa url-only chỉ là dự phòng.
            for u in {url, (row.get("final_url") or "").strip()}:
                if u:
                    idx[normalize_url(u)] = row
                    if st:
                        idx[(st, normalize_url(u))] = row
    return idx


def _find_snippet(text: str, patterns: list[str], window: int = 120) -> str:
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            start = max(0, m.start() - 40)
            end = min(len(text), m.end() + window)
            snip = re.sub(r"\s+", " ", text[start:end]).strip()
            return snip[:280]
    return ""


def _has_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE | re.DOTALL) for p in patterns)


def _year_in_active_ok(text: str, source_date: date | None, today: date) -> bool:
    """Bằng chứng vận hành: ưu tiên năm ≥ 2024 hoặc nguồn ≤24 tháng."""
    if source_date and source_date >= today - timedelta(days=730):
        return True
    if re.search(r"\b(202[4-9]|20[3-9]\d)\b", text):
        # có năm gần trong ngữ cảnh sản lượng / hoạt động
        if _has_any(text, ACTIVE_PATTERNS):
            return True
    # website có biểu giá / lịch khai thác → chấp nhận không cần năm
    if re.search(r"biểu giá|bieu gia|lịch khai thác|lich khai thac", text, re.I):
        return True
    return _has_any(text, ACTIVE_PATTERNS)


def propose_from_texts(
    evidences: list[Evidence],
    *,
    today: date | None = None,
    had_search_rounds: bool = False,
    ten: str = "",
) -> dict[str, str]:
    """
    Đề xuất trạng thái từ danh sách evidence (đã lọc MỞ_ĐƯỢC_KHỚP nếu có).
    """
    today = today or datetime.now(VN_TZ).date()
    if not evidences:
        ly = "chưa có ứng viên" if not had_search_rounds else "đã tìm nhưng không có trang khớp"
        return {
            "trang_thai": STATUS_UNKNOWN if not had_search_rounds else STATUS_PLANNED,
            "cau_trich": "",
            "url": "",
            "ngay_nguon": "",
            "evidence_path": "",
            "ly_do": ly,
            "do_tin_cay": "thap",
        }

    flags = {
        "active": [],
        "building": [],
        "opened": [],
        "planned": [],
        "stopped": [],
        "future": [],
    }
    if ten:
        evidences = [
            Evidence(e.url, focus_text(e.text or "", ten,
                                       allow_adjacent=e.check_status == "MỞ_ĐƯỢC_KHỚP"), e.text_path, e.screenshot,
                     e.source_date, e.check_status, e.matched)
            for e in evidences
        ]
    for ev in evidences:
        t = ev.text or ""
        if not t:
            continue
        if not ev.matched:
            # Link không khớp ICD: chỉ được dùng làm tín hiệu quy hoạch.
            if _has_any(t, PLANNED_PATTERNS):
                flags["planned"].append(ev)
            continue
        t, fut = split_future_building(t, today)
        if fut:
            flags["future"].append(Evidence(ev.url, fut, ev.text_path, ev.screenshot,
                                            ev.source_date, ev.check_status, ev.matched))
        if _has_any(t, STOPPED_PATTERNS):
            flags["stopped"].append(ev)
        if _has_any(t, BUILDING_PATTERNS):
            flags["building"].append(ev)
        if active_hit(t, ten) and _year_in_active_ok(t, ev.source_date, today):
            flags["active"].append(ev)
        if _has_any(t, OPENED_PATTERNS):
            flags["opened"].append(ev)
        if _has_any(t, PLANNED_PATTERNS):
            flags["planned"].append(ev)

    # Mâu thuẫn: hoạt động vs ngừng / xây dựng vs hoạt động mạnh hai phía
    conflict = bool(flags["active"] and flags["stopped"])
    if conflict:
        ev = flags["active"][0]
        return {
            "trang_thai": STATUS_UNKNOWN,
            "cau_trich": _find_snippet(ev.text, ACTIVE_PATTERNS + STOPPED_PATTERNS),
            "url": ev.url,
            "ngay_nguon": ev.source_date.isoformat() if ev.source_date else "",
            "evidence_path": ev.text_path or ev.screenshot,
            "ly_do": "nguồn mâu thuẫn (vừa có dấu hiệu hoạt động vừa có ngừng/di dời)",
            "do_tin_cay": "thap",
        }

    def pack(status: str, ev: Evidence, patterns: list[str], ly: str, conf: str) -> dict[str, str]:
        return {
            "trang_thai": status,
            "cau_trich": _find_snippet(ev.text, patterns),
            "url": ev.url,
            "ngay_nguon": ev.source_date.isoformat() if ev.source_date else "",
            "evidence_path": ev.text_path or ev.screenshot,
            "ly_do": ly,
            "do_tin_cay": conf,
        }

    if flags["stopped"]:
        ev = flags["stopped"][0]
        return pack(
            STATUS_STOPPED,
            ev,
            STOPPED_PATTERNS,
            "có nguồn xác nhận ngừng/di dời",
            "cao",
        )

    if flags["active"]:
        ev = flags["active"][0]
        return pack(
            STATUS_ACTIVE,
            ev,
            ACTIVE_PATTERNS,
            "có bằng chứng vận hành (không chỉ QĐ mở)",
            "cao",
        )

    if flags["building"]:
        ev = flags["building"][0]
        return pack(
            STATUS_BUILDING,
            ev,
            BUILDING_PATTERNS,
            "có dấu hiệu xây dựng / chuẩn bị đầu tư",
            "trung_binh",
        )

    if flags["opened"]:
        ev = flags["opened"][0]
        return pack(
            STATUS_OPENED,
            ev,
            OPENED_PATTERNS,
            "chỉ có quyết định/công bố mở — chưa có bằng chứng đang khai thác (R5)",
            "trung_binh",
        )

    if flags["future"] and not flags["planned"]:
        ev = flags["future"][0]
        return pack(
            STATUS_PLANNED,
            ev,
            BUILDING_PATTERNS,
            "khởi công/xây dựng chỉ là kế hoạch tương lai (năm > hiện tại) → chưa triển khai",
            "thap",
        )

    if flags["planned"]:
        ev = flags["planned"][0]
        return pack(
            STATUS_PLANNED,
            ev,
            PLANNED_PATTERNS,
            "chỉ thấy quy hoạch / QĐ-NQ định hướng; không có bằng chứng vận hành từ link khớp ICD",
            "trung_binh" if ev.matched else "thap",
        )

    # Có text nhưng không khớp từ khóa
    ev = evidences[0]
    return {
        "trang_thai": STATUS_UNKNOWN,
        "cau_trich": (re.sub(r"\s+", " ", ev.text)[:200] if ev.text else ""),
        "url": ev.url,
        "ngay_nguon": ev.source_date.isoformat() if ev.source_date else "",
        "evidence_path": ev.text_path or ev.screenshot,
        "ly_do": "đã có trang khớp nhưng chưa đủ tín hiệu trạng thái",
        "do_tin_cay": "thap",
    }


def gather_evidence_for_stt(
    stt: int,
    link_chon_row: dict[str, str] | None,
    check_idx: dict[str, dict[str, str]],
) -> tuple[list[Evidence], bool]:
    """Trả (evidences, had_any_candidate_signal)."""
    urls: list[str] = []
    had = False
    if link_chon_row:
        if link_chon_row.get("url_chon"):
            urls.append(link_chon_row["url_chon"])
            had = True
        for u in (link_chon_row.get("nguon_kiem_chung") or "").split("|"):
            u = u.strip()
            if u:
                urls.append(u)
                had = True
        if (link_chon_row.get("ly_do") or "") != "chưa có ứng viên":
            had = True

    evidences: list[Evidence] = []
    seen: set[str] = set()
    for url in urls:
        nu = normalize_url(url)
        if nu in seen:
            continue
        seen.add(nu)
        row = check_idx.get((str(stt), nu)) or check_idx.get(nu) or {}
        status = (row.get("status") or "").strip()
        # ưu tiên text đã khớp; vẫn đọc nếu có text_path
        text_path = (row.get("text_path") or "").strip()
        text = read_evidence_text(text_path)
        if not text:
            # file text riêng STT có thể không tồn tại (cache lưu theo STT khác) →
            # mượn text cùng URL; trạng thái khớp vẫn lấy theo (stt, url).
            alt = (check_idx.get(nu) or {}).get("text_path", "").strip()
            if alt and alt != text_path:
                text = read_evidence_text(alt)
                if text:
                    text_path = alt
        if not text and not status:
            continue
        if status and status not in (
            "MỞ_ĐƯỢC_KHỚP",
            "LỖI_SSL_MỞ_ĐƯỢC",
            "ĐÃ_XÁC_MINH_TAY",
        ):
            # vẫn bỏ CHỈ_KHỚP_CHUNG khỏi đề xuất vận hành
            if status == "CHỈ_KHỚP_CHUNG":
                continue
        evidences.append(
            Evidence(
                url=url,
                text=text,
                text_path=text_path,
                screenshot=(row.get("screenshot") or "").strip(),
                source_date=parse_date_guess(
                    row.get("title") or "", url, row.get("fetched_at") or "", text[:500]
                ),
                check_status=status,
                matched=is_matched_row(row),
            )
        )
    return evidences, had


def run_propose(
    *,
    keys_path: Path = KEYS_CSV,
    link_chon_path: Path = LINK_CHON_CSV,
    check_paths: list[Path] | None = None,
    out_path: Path = OUT_CSV,
    today: date | None = None,
    override_path: Path | None = None,
) -> list[dict[str, str]]:
    if check_paths is None:
        check_paths = [LINK_CHECK_CSV, UNG_VIEN_CHECK_CSV]
    keys = load_keys(keys_path) or {i: "" for i in range(1, 129)}
    chon_by_stt: dict[int, dict[str, str]] = {}
    for row in _read_csv(link_chon_path):
        s = (row.get("stt") or "").strip()
        if s.isdigit():
            chon_by_stt[int(s)] = row
    check_idx = load_check_by_url(check_paths)

    rows: list[dict[str, str]] = []
    for stt in range(1, 129):
        ten = keys.get(stt, "")
        chon = chon_by_stt.get(stt)
        evidences, had = gather_evidence_for_stt(stt, chon, check_idx)
        # Nếu chưa có link_chon → coi như chưa có ứng viên
        if chon is None and not evidences:
            prop = {
                "trang_thai": STATUS_UNKNOWN,
                "cau_trich": "",
                "url": "",
                "ngay_nguon": "",
                "evidence_path": "",
                "ly_do": "chưa có ứng viên",
                "do_tin_cay": "thap",
            }
        else:
            prop = propose_from_texts(evidences, today=today, had_search_rounds=had, ten=ten)
        rows.append(
            {
                "stt": str(stt),
                "ten": ten or (chon or {}).get("ten", ""),
                **prop,
            }
        )

    if override_path is not None:
        ov = {r["stt"].strip(): r for r in _read_csv(override_path) if (r.get("stt") or "").strip()}
        for row in rows:
            o = ov.get(row["stt"])
            if o:
                for c in ("trang_thai", "cau_trich", "url", "ngay_nguon", "ly_do", "do_tin_cay"):
                    row[c] = o.get(c, "")
                row["evidence_path"] = ""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in COLUMNS})
    return rows


# ---------- tests ----------


class ProposeStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="propose_status_"))
        self.keys = self.tmp / "keys.csv"
        with self.keys.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["stt", "ten_chinh"])
            w.writeheader()
            for i in range(1, 129):
                w.writerow({"stt": str(i), "ten_chinh": f"ICD {i}"})

    def _write_text(self, name: str, content: str) -> str:
        p = self.tmp / name
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_empty_gives_128_chua_co(self) -> None:
        rows = run_propose(
            keys_path=self.keys,
            link_chon_path=self.tmp / "missing_chon.csv",
            check_paths=[self.tmp / "missing_check.csv"],
            out_path=self.tmp / "out.csv",
        )
        self.assertEqual(len(rows), 128)
        self.assertTrue(all(r["ly_do"] == "chưa có ứng viên" for r in rows))
        self.assertTrue(all(r["trang_thai"] == STATUS_UNKNOWN for r in rows))

    def test_qd_mo_alone_is_not_active(self) -> None:
        text_path = self._write_text(
            "qd.txt",
            "Bộ GTVT công bố mở cảng cạn Hoàng Thành theo quyết định mở cảng cạn số 60/QĐ-BGTVT.",
        )
        chon = self.tmp / "chon.csv"
        with chon.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "stt",
                    "ten",
                    "url_chon",
                    "loai_nguon",
                    "do_uu_tien",
                    "trang_thai_verify",
                    "ly_do",
                    "nguon_kiem_chung",
                    "ghi_chu",
                ],
            )
            w.writeheader()
            for i in range(1, 129):
                url = "https://example.gov.vn/qd-60.html" if i == 6 else ""
                w.writerow(
                    {
                        "stt": str(i),
                        "ten": f"ICD {i}",
                        "url_chon": url,
                        "loai_nguon": "van_ban" if url else "",
                        "do_uu_tien": "2" if url else "",
                        "trang_thai_verify": "",
                        "ly_do": "van ban" if url else "chưa có ứng viên",
                        "nguon_kiem_chung": "",
                        "ghi_chu": "",
                    }
                )
        chk = self.tmp / "check.csv"
        with chk.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f, fieldnames=["stt", "url", "status", "text_path", "title", "fetched_at"]
            )
            w.writeheader()
            w.writerow(
                {
                    "stt": "6",
                    "url": "https://example.gov.vn/qd-60.html",
                    "status": "MỞ_ĐƯỢC_KHỚP",
                    "text_path": text_path,
                    "title": "Công bố mở",
                    "fetched_at": "2026-10-01",
                }
            )
        rows = run_propose(
            keys_path=self.keys,
            link_chon_path=chon,
            check_paths=[chk],
            out_path=self.tmp / "out.csv",
            today=date(2026, 10, 30),
        )
        r6 = next(r for r in rows if r["stt"] == "6")
        self.assertEqual(r6["trang_thai"], STATUS_OPENED)
        self.assertIn("chưa có bằng chứng đang khai thác", r6["ly_do"])

    def test_active_with_operational_evidence(self) -> None:
        text_path = self._write_text(
            "ops.txt",
            "Năm 2025 ICD Sóng Thần đi vào hoạt động với sản lượng 120.000 TEU, tiếp nhận chuyến hàng thường xuyên.",
        )
        chon = self.tmp / "chon.csv"
        with chon.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "stt",
                    "ten",
                    "url_chon",
                    "loai_nguon",
                    "do_uu_tien",
                    "trang_thai_verify",
                    "ly_do",
                    "nguon_kiem_chung",
                    "ghi_chu",
                ],
            )
            w.writeheader()
            for i in range(1, 129):
                w.writerow(
                    {
                        "stt": str(i),
                        "ten": f"ICD {i}",
                        "url_chon": "https://baoxaydung.vn/song-than-2025.htm"
                        if i == 106
                        else "",
                        "loai_nguon": "bao_chi" if i == 106 else "",
                        "do_uu_tien": "3" if i == 106 else "",
                        "trang_thai_verify": "",
                        "ly_do": "bao" if i == 106 else "chưa có ứng viên",
                        "nguon_kiem_chung": "",
                        "ghi_chu": "",
                    }
                )
        chk = self.tmp / "check.csv"
        with chk.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f, fieldnames=["stt", "url", "status", "text_path", "title", "fetched_at"]
            )
            w.writeheader()
            w.writerow(
                {
                    "stt": "106",
                    "url": "https://baoxaydung.vn/song-than-2025.htm",
                    "status": "MỞ_ĐƯỢC_KHỚP",
                    "text_path": text_path,
                    "title": "Sóng Thần 2025",
                    "fetched_at": "2026-10-01",
                }
            )
        rows = run_propose(
            keys_path=self.keys,
            link_chon_path=chon,
            check_paths=[chk],
            out_path=self.tmp / "out.csv",
            today=date(2026, 10, 30),
        )
        r = next(x for x in rows if x["stt"] == "106")
        self.assertEqual(r["trang_thai"], STATUS_ACTIVE)
        self.assertTrue(r["cau_trich"])

    def test_building_keywords(self) -> None:
        text_path = self._write_text(
            "build.txt",
            "Dự án đã khởi công và đang thi công giai đoạn giải phóng mặt bằng.",
        )
        ev = Evidence(
            url="https://example.com/x",
            text=Path(text_path).read_text(encoding="utf-8"),
            text_path=text_path,
            screenshot="",
            source_date=date(2025, 6, 1),
        )
        prop = propose_from_texts([ev], today=date(2026, 10, 30), had_search_rounds=True)
        self.assertEqual(prop["trang_thai"], STATUS_BUILDING)


class MatchedGateTests(unittest.TestCase):
    def test_active_keyword_ignored_on_unmatched_link(self) -> None:
        ev = Evidence("u", "Dự án khi đi vào hoạt động năm 2026", "", "", None,
                      "MỞ_ĐƯỢC_KHÔNG_KHỚP", matched=False)
        r = propose_from_texts([ev], today=date(2026, 10, 30), had_search_rounds=True)
        self.assertNotEqual(r["trang_thai"], STATUS_ACTIVE)

    def test_active_keyword_counts_on_matched_link(self) -> None:
        ev = Evidence("u", "ICD đã đi vào hoạt động năm 2025", "", "", None,
                      "MỞ_ĐƯỢC_KHỚP", matched=True)
        r = propose_from_texts([ev], today=date(2026, 10, 30), had_search_rounds=True)
        self.assertEqual(r["trang_thai"], STATUS_ACTIVE)

    def test_planning_only_maps_to_planned(self) -> None:
        ev = Evidence("u", "Cảng cạn X theo Quyết định 979/QĐ-TTg, quy hoạch đến 2030",
                      "", "", None, "CHỈ_KHỚP_CHUNG", matched=False)
        r = propose_from_texts([ev], today=date(2026, 10, 30), had_search_rounds=False)
        self.assertEqual(r["trang_thai"], STATUS_PLANNED)

    def test_unmatched_operational_plus_planning_is_planned(self) -> None:
        evs = [Evidence("a", "khánh thành cảng cá năm 2025", "", "", None, "MỞ_ĐƯỢC_KHÔNG_KHỚP", matched=False),
               Evidence("b", "NQ 01/NQ-HĐND định hướng ICD", "", "", None, "MỞ_ĐƯỢC_KHÔNG_KHỚP", matched=False)]
        r = propose_from_texts(evs, today=date(2026, 10, 30), had_search_rounds=True)
        self.assertEqual(r["trang_thai"], STATUS_PLANNED)

    def test_override_applied(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        ov = tmp / "ov.csv"
        ov.write_text("stt,trang_thai,cau_trich,url,ngay_nguon,ly_do,do_tin_cay\n5,%s,x,u,,sửa tay,trung_binh\n" % STATUS_PLANNED, encoding="utf-8")
        rows = run_propose(keys_path=tmp / "k.csv", link_chon_path=tmp / "c.csv", check_paths=[tmp / "x.csv"],
                           out_path=tmp / "o.csv", override_path=ov)
        self.assertEqual(rows[4]["trang_thai"], STATUS_PLANNED)
        self.assertEqual(rows[5]["trang_thai"], STATUS_UNKNOWN)

    def test_sidebar_keyword_far_from_name_ignored(self) -> None:
        txt = ("Mở cảng cạn ICD Phúc Lộc tại Ninh Bình. ICD Phúc Lộc phục vụ hàng hóa.\n"
               "Tin khác: doanh nghiệp ngừng hoạt động kinh doanh chưa đóng mã số thuế.")
        ev = Evidence("u", txt, "", "", None, "MỞ_ĐƯỢC_KHỚP", matched=True)
        r = propose_from_texts([ev], today=date(2026, 10, 30), had_search_rounds=True,
                               ten="Cảng cạn (ICD) Phúc Lộc – Ninh Bình")
        self.assertNotEqual(r["trang_thai"], STATUS_STOPPED)

    def test_keyword_near_name_counts(self) -> None:
        txt = "Menu. ICD Phúc Lộc đã đi vào hoạt động năm 2025. Liên hệ."
        ev = Evidence("u", txt, "", "", None, "MỞ_ĐƯỢC_KHỚP", matched=True)
        r = propose_from_texts([ev], today=date(2026, 10, 30), had_search_rounds=True, ten="ICD Phúc Lộc")
        self.assertEqual(r["trang_thai"], STATUS_ACTIVE)

    def test_qd_number_without_icd_context_not_planned(self) -> None:
        ev = Evidence("u", "Hoàng Thành: Số 50/QĐ-UBND ngày 09/01/2026 danh sách thôn vùng DTTS",
                      "", "", None, "MỞ_ĐƯỢC_KHÔNG_KHỚP", matched=False)
        r = propose_from_texts([ev], today=date(2026, 10, 30), had_search_rounds=True, ten="Cảng cạn Hoàng Thành")
        self.assertNotEqual(r["trang_thai"], STATUS_PLANNED)

    def test_qd_number_with_icd_context_planned(self) -> None:
        ev = Evidence("u", "Cảng cạn Hà Tiên theo 979/QĐ-TTg, công suất 50.000 TEU",
                      "", "", None, "CHỈ_KHỚP_CHUNG", matched=False)
        r = propose_from_texts([ev], today=date(2026, 10, 30), had_search_rounds=True, ten="Hà Tiên")
        self.assertEqual(r["trang_thai"], STATUS_PLANNED)

    def test_core_name(self) -> None:
        self.assertEqual(core_name("Cảng cạn (ICD) Phúc Lộc – Ninh Bình"), "Phúc Lộc")
        self.assertEqual(core_name("Châu Thành (Hậu Giang cũ)"), "Châu Thành")

    def test_ssl_row_needs_name_and_area(self) -> None:
        self.assertTrue(is_matched_row({"status": "LỖI_SSL_MỞ_ĐƯỢC", "khop_ten": "1", "khop_dia_ban": "1"}))
        self.assertFalse(is_matched_row({"status": "LỖI_SSL_MỞ_ĐƯỢC", "khop_ten": "1", "khop_dia_ban": "0"}))
        self.assertFalse(is_matched_row({"status": "MỞ_ĐƯỢC_KHÔNG_KHỚP"}))


class V4Tests(unittest.TestCase):
    def test_old_style_cong_bo(self):
        t = "Quyết định 3882/QĐ-BGTVT công bố cảng cạn Km3 4 Móng Cái. Nay công bố cảng cạn Km3+4 Móng Cái, tỉnh Quảng Ninh với nội dung cơ bản sau đây."
        r = propose_from_texts([Evidence(url="u", text=t, matched=True, check_status="MỞ_ĐƯỢC_KHỚP", text_path="", screenshot="", source_date=date(2015, 10, 30))], today=date(2026, 10, 30), had_search_rounds=True, ten="Cảng cạn Km3+4 Móng Cái, tỉnh Quảng Ninh")
        self.assertEqual(r["trang_thai"], STATUS_OPENED)
        r2 = propose_from_texts([Evidence(url="u", text="Tỉnh sẽ công bố cảng cạn Km3+4 Móng Cái trong năm tới.", matched=True, check_status="MỞ_ĐƯỢC_KHỚP", text_path="", screenshot="", source_date=date(2015, 10, 30))], today=date(2026, 10, 30), had_search_rounds=True, ten="Cảng cạn Km3+4 Móng Cái, tỉnh Quảng Ninh")
        self.assertNotEqual(r2["trang_thai"], STATUS_OPENED)

    def test_check_idx_per_stt(self):
        import tempfile
        d = Path(tempfile.mkdtemp()) / "c.csv"
        d.write_text("stt,url,status,final_url\n18,http://x/a,MỞ_ĐƯỢC_KHỚP,\n116,http://x/a,MỞ_ĐƯỢC_KHÔNG_KHỚP,\n", encoding="utf-8")
        idx = load_check_by_url([d])
        self.assertEqual(idx[("18", normalize_url("http://x/a"))]["status"], "MỞ_ĐƯỢC_KHỚP")
        self.assertEqual(idx[("116", normalize_url("http://x/a"))]["status"], "MỞ_ĐƯỢC_KHÔNG_KHỚP")

    def test_hedged_active_ignored(self):
        for t in ["Cảng cạn Long Biên dự kiến năm 2026 sẽ đưa vào khai thác.",
                  "Cảng cạn Long Biên: chưa có cảng container được đưa vào khai thác.",
                  "Mục tiêu đầu tư xây dựng, đưa vào khai thác cảng cạn Long Biên."]:
            self.assertNotEqual(self._r(t)["trang_thai"], STATUS_ACTIVE, t)

    def test_future_after_phrase_ignored(self):
        r = self._r("Cảng cạn Long Biên được công bố mở. Cảng đi vào hoạt động sẽ là điểm thông quan quan trọng.")
        self.assertNotEqual(r["trang_thai"], STATUS_ACTIVE)

    def test_conditional_khi_ignored(self):
        r = self._r("Cảng cạn Long Biên là trọng điểm, nhất là khi cao tốc được hoàn thiện và Hà Nội đưa vào khai thác cảng cạn Long Biên.")
        self.assertNotEqual(r["trang_thai"], STATUS_ACTIVE)

    def test_citation_marker_splits_sentence(self):
        self.assertEqual(len(split_sents("Cảng A khởi công.[4] Giai đoạn đầu logistics.")), 2)

    def test_new_phrase_other_port_ignored(self):
        r = self._r("Cảng cạn Long Biên của Hateco. Cảng Hateco đã đưa vào khai thác cảng HHIT tại Lạch Huyện.")
        self.assertNotEqual(r["trang_thai"], STATUS_ACTIVE)

    D = date(2026, 10, 30)

    def _r(self, txt, st="MỞ_ĐƯỢC_KHỚP", ten="Cảng cạn Long Biên"):
        ev = Evidence("u", txt, "", "", None, st, matched=st == "MỞ_ĐƯỢC_KHỚP")
        return propose_from_texts([ev], today=self.D, ten=ten)

    def test_adjacent_cang_sentence_counts(self):
        r = self._r("Cảng cạn Long Biên nằm ở Hà Nội. Cảng chính thức đi vào hoạt động năm 2017.")
        self.assertEqual(r["trang_thai"], STATUS_ACTIVE)

    def test_adjacent_unrelated_sentence_ignored(self):
        r = self._r("Cảng cạn Long Biên nằm ở Hà Nội. Nhà máy bia khánh thành năm 2020.")
        self.assertNotEqual(r["trang_thai"], STATUS_ACTIVE)

    def test_non_adjacent_cang_sentence_ignored(self):
        r = self._r("Cảng cạn Long Biên nằm ở Hà Nội. Thời tiết đẹp. Cảng đi vào hoạt động.")
        self.assertNotEqual(r["trang_thai"], STATUS_ACTIVE)

    def test_adjacent_not_allowed_on_ssl_or_unmatched(self):
        r = self._r("Cảng cạn Long Biên nằm ở Hà Nội. Cảng đi vào hoạt động.", st="MỞ_ĐƯỢC_KHÔNG_KHỚP")
        self.assertNotEqual(r["trang_thai"], STATUS_ACTIVE)

    def test_sidebar_still_ignored(self):
        r = self._r("Tin khác\nICD Tiên Sơn khai trương kho mới\nCảng cạn Long Biên là đầu mối logistics.")
        self.assertNotEqual(r["trang_thai"], STATUS_ACTIVE)

    def test_first_container_is_active(self):
        r = self._r("ICD Tân Cảng Hải Phòng đón container hàng đầu tiên.", ten="Cảng cạn Tân Cảng Hải Phòng")
        self.assertEqual(r["trang_thai"], STATUS_ACTIVE)

    def test_future_groundbreaking_is_planned(self):
        r = self._r("Năm 2028 – 2032, khởi công khu logistics cảng cạn Long Biên.")
        self.assertEqual(r["trang_thai"], STATUS_PLANNED)

    def test_future_phase_is_planned(self):
        r = self._r("Cảng cạn Long Biên giai đoạn 2030–2035 sẽ khởi công.")
        self.assertEqual(r["trang_thai"], STATUS_PLANNED)

    def test_multi_phase_sentence(self):
        r = self._r("Giai đoạn 2025 - 2028, lập quy hoạch; năm 2028 - 2032, khởi công khu logistics cảng cạn Long Biên.")
        self.assertEqual(r["trang_thai"], STATUS_PLANNED)

    def test_past_groundbreaking_is_building(self):
        r = self._r("Năm 2025 khởi công cảng cạn Long Biên.")
        self.assertEqual(r["trang_thai"], STATUS_BUILDING)


class FinalTableTests(unittest.TestCase):
    """Bảng cuối (data/trang_thai_de_xuat.csv) + file override phải nhất quán."""

    def _load(self):
        if not OUT_CSV.exists():
            self.skipTest("chưa có bảng cuối; chạy script trước")
        with open(OUT_CSV, encoding="utf-8") as fh:
            out = list(csv.DictReader(fh))
        ov = []
        if OVERRIDE_CSV.exists():
            with open(OVERRIDE_CSV, encoding="utf-8-sig") as fh:
                ov = list(csv.DictReader(fh))
        return out, ov

    def test_exactly_128_rows(self):
        out, _ = self._load()
        self.assertEqual(len(out), 128)

    def test_no_duplicate_stt(self):
        out, ov = self._load()
        stts = [r["stt"] for r in out]
        self.assertEqual(len(stts), len(set(stts)))
        ostts = [r["stt"] for r in ov]
        self.assertEqual(len(ostts), len(set(ostts)))

    def test_override_matches_final_table(self):
        out, ov = self._load()
        by = {r["stt"]: r for r in out}
        for o in ov:
            self.assertIn(o["stt"], by)
            for k in ("trang_thai", "cau_trich", "url"):
                self.assertEqual((o.get(k) or "").strip(), (by[o["stt"]].get(k) or "").strip(), f"stt {o['stt']} {k}")


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "test":
        suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (ProposeStatusTests, MatchedGateTests, V4Tests, FinalTableTests)])
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        print(
            f"\n{result.testsRun} tests, "
            f"{len(result.failures)} failures, "
            f"{len(result.errors)} errors",
            flush=True,
        )
        return 0 if result.wasSuccessful() else 1

    rows = run_propose(override_path=OVERRIDE_CSV)
    from collections import Counter

    c = Counter(r["trang_thai"] for r in rows)
    print(f"Wrote {OUT_CSV}", flush=True)
    for k, v in c.most_common():
        print(f"  {v:3}  {k}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
