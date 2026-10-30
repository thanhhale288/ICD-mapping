"""
P3.6 (light) — Trích thông tin bổ sung cho ô đang trống → data/tra_cuu.csv.

Chỉ điền ô trống; không có nguồn thì không điền (R3).
Skeleton: đọc hạng mục trống từ icd_hien_trang + evidence từ link_chon/link_check,
thử pattern đơn giản; phần lớn còn để Phase 3.6 đầy đủ / duyệt tay.

Cột: stt,hang_muc,gia_tri,url,ngay_nguon,cau_trich

Usage:
  python3 scripts/extract_tra_cuu.py
  python3 scripts/extract_tra_cuu.py test
"""

from __future__ import annotations

import csv
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

HIEN_TRANG = ROOT / "data" / "icd_hien_trang.csv"
LINK_CHON_CSV = ROOT / "data" / "link_chon.csv"
LINK_CHECK_CSV = ROOT / "data" / "link_check.csv"
UNG_VIEN_CHECK_CSV = ROOT / "data" / "ung_vien_check.csv"
OUT_CSV = ROOT / "data" / "tra_cuu.csv"

# Hạng mục Phase 3.6 quan tâm (khớp hang_muc trong icd_hien_trang)
TARGET_HANG_MUC = (
    "Chủ đầu tư",
    "Đơn vị khai thác",
    "Quy mô",
    "Dịch vụ cung cấp",
    "Các hãng tàu đã mở code khai thác",
    "Kết nối các phương thức vận tải",
    "Nhóm khách hàng chính",
)

COLUMNS = [
    "stt",
    "hang_muc",
    "gia_tri",
    "url",
    "ngay_nguon",
    "cau_trich",
]

# Pattern nhẹ — chỉ điền khi bắt được rõ ràng
EXTRACTORS: dict[str, list[tuple[str, int]]] = {
    "Chủ đầu tư": [
        (r"(?:Chủ đầu tư|chủ đầu tư)\s*[:\-–]\s*(.+?)(?:\.|;|\n|$)", 1),
        (r"(?:do|Do)\s+(Công ty[^.;\n]{5,80})\s+(?:làm chủ đầu tư|đầu tư)", 1),
    ],
    "Đơn vị khai thác": [
        (r"(?:Đơn vị khai thác|đơn vị khai thác|Nhà khai thác)\s*[:\-–]\s*(.+?)(?:\.|;|\n|$)", 1),
    ],
    "Quy mô": [
        (r"(?:Diện tích|diện tích)\s*[:\-–]?\s*([\d.,]+\s*(?:ha|m²|m2))", 1),
        (r"(?:công suất|Công suất).{0,20}?([\d.,]+\s*(?:TEU|teu)[^\n.;]{0,40})", 1),
    ],
    "Dịch vụ cung cấp": [
        (r"(?:Dịch vụ|dịch vụ)\s*[:\-–]\s*(.+?)(?:\.|;|\n|$)", 1),
    ],
    "Các hãng tàu đã mở code khai thác": [
        (r"(?:hãng tàu|Hãng tàu).{0,30}?(?:mở code|khai thác)\s*[:\-–]?\s*(.+?)(?:\.|;|\n|$)", 1),
    ],
    "Kết nối các phương thức vận tải": [
        (r"(?:Kết nối|kết nối).{0,40}?(đường bộ[^.\n]{0,80}|đường sắt[^.\n]{0,80}|đường thủy[^.\n]{0,80})", 1),
    ],
    "Nhóm khách hàng chính": [
        (r"(?:Khách hàng|nhóm khách hàng)\s*[:\-–]\s*(.+?)(?:\.|;|\n|$)", 1),
    ],
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def is_empty_value(val: str) -> bool:
    s = (val or "").strip()
    if not s:
        return True
    low = s.lower()
    if low in {"n/a", "na", "-", "—", "chưa có", "không có"}:
        return True
    return False


def discover_empty(hien_trang: Path = HIEN_TRANG) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {i: [] for i in range(1, 129)}
    rows = _read_csv(hien_trang)
    if not rows:
        # không có hien_trang → không điền gì (mọi STT coi như chưa biết ô trống)
        return {i: [] for i in range(1, 129)}

    # xác định tên cột giá trị (icd_hien_trang dùng noi_dung)
    sample = rows[0]
    value_key = "noi_dung"
    for k in ("noi_dung", "gia_tri", "gia_tri_hien_tai"):
        if k in sample:
            value_key = k
            break
    else:
        keys = list(sample.keys())
        if "hang_muc" in keys:
            idx = keys.index("hang_muc")
            if idx + 1 < len(keys):
                value_key = keys[idx + 1]

    for row in rows:
        if (row.get("loai") or "") != "chi_tiet":
            continue
        hm = (row.get("hang_muc") or "").strip()
        if hm not in TARGET_HANG_MUC:
            continue
        stt_raw = (row.get("stt") or "").strip()
        if not stt_raw.isdigit():
            continue
        stt = int(stt_raw)
        if is_empty_value(row.get(value_key) or ""):
            out.setdefault(stt, []).append(hm)
    return out


def normalize_url(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def read_text(path_str: str) -> str:
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


def parse_date_guess(*texts: str) -> str:
    blob = " ".join(t for t in texts if t)
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", blob)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", blob)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return ""


def try_extract(hang_muc: str, text: str) -> tuple[str, str] | None:
    """Trả (gia_tri, cau_trich) hoặc None."""
    patterns = EXTRACTORS.get(hang_muc) or []
    for pat, group in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        val = re.sub(r"\s+", " ", m.group(group)).strip(" .;,-")
        if len(val) < 3 or len(val) > 200:
            continue
        start = max(0, m.start() - 20)
        end = min(len(text), m.end() + 40)
        snip = re.sub(r"\s+", " ", text[start:end]).strip()[:240]
        return val, snip
    return None


def sources_for_stt(
    stt: int,
    chon_by: dict[int, dict[str, str]],
    check_idx: dict[str, dict[str, str]],
) -> list[tuple[str, str, str]]:
    """list of (url, text, ngay)."""
    chon = chon_by.get(stt) or {}
    urls: list[str] = []
    if chon.get("url_chon"):
        urls.append(chon["url_chon"])
    for u in (chon.get("nguon_kiem_chung") or "").split("|"):
        if u.strip():
            urls.append(u.strip())
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for url in urls:
        nu = normalize_url(url)
        if nu in seen:
            continue
        seen.add(nu)
        row = check_idx.get(nu) or {}
        text = read_text(row.get("text_path") or "")
        if not text:
            continue
        ngay = parse_date_guess(row.get("fetched_at") or "", url, text[:400])
        out.append((url, text, ngay))
    return out


def run_extract(
    *,
    hien_trang: Path = HIEN_TRANG,
    link_chon: Path = LINK_CHON_CSV,
    check_paths: list[Path] | None = None,
    out_path: Path = OUT_CSV,
) -> list[dict[str, str]]:
    if check_paths is None:
        check_paths = [LINK_CHECK_CSV, UNG_VIEN_CHECK_CSV]

    empty = discover_empty(hien_trang)
    chon_by: dict[int, dict[str, str]] = {}
    for row in _read_csv(link_chon):
        s = (row.get("stt") or "").strip()
        if s.isdigit():
            chon_by[int(s)] = row

    check_idx: dict[str, dict[str, str]] = {}
    for path in check_paths:
        for row in _read_csv(path):
            url = (row.get("url") or "").strip()
            if url:
                check_idx[normalize_url(url)] = row

    filled: list[dict[str, str]] = []
    # Đảm bảo file luôn tồn tại; có thể 0 dòng dữ liệu nếu chưa có nguồn
    for stt in range(1, 129):
        need = empty.get(stt) or []
        if not need:
            continue
        sources = sources_for_stt(stt, chon_by, check_idx)
        if not sources:
            # không có nguồn → không điền (R3); không ghi dòng
            continue
        for hm in need:
            got = None
            used_url = ""
            used_ngay = ""
            for url, text, ngay in sources:
                got = try_extract(hm, text)
                if got:
                    used_url, used_ngay = url, ngay
                    break
            if not got:
                continue
            gia_tri, cau_trich = got
            filled.append(
                {
                    "stt": str(stt),
                    "hang_muc": hm,
                    "gia_tri": gia_tri,
                    "url": used_url,
                    "ngay_nguon": used_ngay,
                    "cau_trich": cau_trich,
                }
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for row in filled:
            w.writerow(row)
    return filled


# ---------- tests ----------


class ExtractTraCuuTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="extract_tra_cuu_"))

    def test_no_source_writes_header_only(self) -> None:
        out = self.tmp / "tra_cuu.csv"
        rows = run_extract(
            hien_trang=self.tmp / "missing_ht.csv",
            link_chon=self.tmp / "missing_chon.csv",
            check_paths=[self.tmp / "missing_check.csv"],
            out_path=out,
        )
        self.assertEqual(rows, [])
        self.assertTrue(out.exists())
        text = out.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("stt,hang_muc,"))

    def test_only_empty_fields_filled(self) -> None:
        ht = self.tmp / "ht.csv"
        with ht.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f, fieldnames=["loai", "stt", "ten", "sheet", "hang_muc", "noi_dung"]
            )
            w.writeheader()
            w.writerow(
                {
                    "loai": "chi_tiet",
                    "stt": "1",
                    "ten": "A",
                    "sheet": "01",
                    "hang_muc": "Đơn vị khai thác",
                    "noi_dung": "",
                }
            )
            w.writerow(
                {
                    "loai": "chi_tiet",
                    "stt": "1",
                    "ten": "A",
                    "sheet": "01",
                    "hang_muc": "Chủ đầu tư",
                    "noi_dung": "Công ty CP VIMC Logistics",
                }
            )
        text_path = self.tmp / "ev.txt"
        text_path.write_text(
            "Chủ đầu tư: Công ty Fake. Đơn vị khai thác: Công ty TNHH ABC Logistics.",
            encoding="utf-8",
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
            w.writerow(
                {
                    "stt": "1",
                    "ten": "A",
                    "url_chon": "https://example.com/icd",
                    "loai_nguon": "website",
                    "do_uu_tien": "1",
                    "trang_thai_verify": "",
                    "ly_do": "ok",
                    "nguon_kiem_chung": "",
                    "ghi_chu": "",
                }
            )
        chk = self.tmp / "check.csv"
        with chk.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f, fieldnames=["stt", "url", "status", "text_path", "fetched_at"]
            )
            w.writeheader()
            w.writerow(
                {
                    "stt": "1",
                    "url": "https://example.com/icd",
                    "status": "MỞ_ĐƯỢC_KHỚP",
                    "text_path": str(text_path),
                    "fetched_at": "2026-10-01",
                }
            )
        rows = run_extract(
            hien_trang=ht,
            link_chon=chon,
            check_paths=[chk],
            out_path=self.tmp / "out.csv",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hang_muc"], "Đơn vị khai thác")
        self.assertIn("ABC", rows[0]["gia_tri"])
        self.assertTrue(rows[0]["url"])
        self.assertTrue(rows[0]["cau_trich"])

    def test_try_extract_quy_mo(self) -> None:
        got = try_extract("Quy mô", "Diện tích: 5,2 ha trong khu công nghiệp.")
        self.assertIsNotNone(got)
        assert got
        self.assertIn("5,2", got[0])


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "test":
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ExtractTraCuuTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        print(
            f"\n{result.testsRun} tests, "
            f"{len(result.failures)} failures, "
            f"{len(result.errors)} errors",
            flush=True,
        )
        return 0 if result.wasSuccessful() else 1

    rows = run_extract()
    print(f"Wrote {OUT_CSV} — {len(rows)} giá trị bổ sung", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
