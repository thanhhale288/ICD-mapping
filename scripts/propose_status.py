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
]

PLANNED_PATTERNS = [
    r"quy hoạch",
    r"quy hoach",
    r"định hướng đến năm 2030",
    r"trong quy hoạch",
]

STOPPED_PATTERNS = [
    r"đã ngừng",
    r"da ngung",
    r"ngừng hoạt động",
    r"ngung hoat dong",
    r"di dời",
    r"di doi",
    r"giải thể",
    r"giai the",
]


@dataclass
class Evidence:
    url: str
    text: str
    text_path: str
    screenshot: str
    source_date: date | None
    check_status: str = ""


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
            if url:
                idx[normalize_url(url)] = row
            final_u = (row.get("final_url") or "").strip()
            if final_u:
                idx[normalize_url(final_u)] = row
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
    }
    for ev in evidences:
        t = ev.text or ""
        if not t:
            continue
        if _has_any(t, STOPPED_PATTERNS):
            flags["stopped"].append(ev)
        if _has_any(t, BUILDING_PATTERNS):
            flags["building"].append(ev)
        if _has_any(t, ACTIVE_PATTERNS) and _year_in_active_ok(t, ev.source_date, today):
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

    if flags["planned"] and had_search_rounds:
        ev = flags["planned"][0]
        return pack(
            STATUS_PLANNED,
            ev,
            PLANNED_PATTERNS,
            "chỉ thấy quy hoạch; đã có lượt tìm",
            "trung_binh",
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
        row = check_idx.get(nu) or {}
        status = (row.get("status") or "").strip()
        # ưu tiên text đã khớp; vẫn đọc nếu có text_path
        text_path = (row.get("text_path") or "").strip()
        text = read_evidence_text(text_path)
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
            prop = propose_from_texts(evidences, today=today, had_search_rounds=had)
        rows.append(
            {
                "stt": str(stt),
                "ten": ten or (chon or {}).get("ten", ""),
                **prop,
            }
        )

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


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "test":
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ProposeStatusTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        print(
            f"\n{result.testsRun} tests, "
            f"{len(result.failures)} failures, "
            f"{len(result.errors)} errors",
            flush=True,
        )
        return 0 if result.wasSuccessful() else 1

    rows = run_propose()
    from collections import Counter

    c = Counter(r["trang_thai"] for r in rows)
    print(f"Wrote {OUT_CSV}", flush=True)
    for k, v in c.most_common():
        print(f"  {v:3}  {k}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
