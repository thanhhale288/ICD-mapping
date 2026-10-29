"""
P1.3 — Kiểm link: fetch.py → match.py → data/link_check.csv.

Cột: STT, URL, nguồn, tầng mở được, mã HTTP, URL cuối, tiêu đề,
loại nội dung, trạng thái, lý do, khớp tên, khớp địa bàn,
số ICD khác được nhắc, ảnh chụp, thời điểm.
"""

from __future__ import annotations

import csv
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch import FetchResult, fetch  # noqa: E402
from match import MatchResult, load_keys, match_text  # noqa: E402

OUT_CSV = ROOT / "data" / "link_check.csv"
HIEN_TRANG = ROOT / "data" / "icd_hien_trang.csv"

COLUMNS = [
    "stt",
    "url",
    "nguon",
    "tang",
    "http_code",
    "final_url",
    "title",
    "content_type",
    "status",
    "ly_do",
    "khop_ten",
    "khop_dia_ban",
    "so_icd_khac",
    "suggested_stt",
    "screenshot",
    "text_path",
    "fetched_at",
    "ssl_insecure",
    "from_cache",
]


@dataclass
class LinkCheckRow:
    stt: str
    url: str
    nguon: str
    tang: int
    http_code: int | None
    final_url: str
    title: str
    content_type: str
    status: str
    ly_do: str
    khop_ten: str
    khop_dia_ban: str
    so_icd_khac: int
    suggested_stt: str
    screenshot: str
    text_path: str
    fetched_at: str
    ssl_insecure: str
    from_cache: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _combine_status(fr: FetchResult, mr: MatchResult | None) -> tuple[str, str]:
    """Gộp trạng thái fetch + match theo Phụ lục B."""
    open_ok = fr.status in ("MỞ_ĐƯỢC", "LỖI_SSL_MỞ_ĐƯỢC")

    if fr.status == "LINK_CHẾT":
        return "LINK_CHẾT", fr.reason
    if fr.status == "BỊ_CHẶN":
        return "BỊ_CHẶN", fr.reason
    if fr.status == "CẦN_MỞ_TAY":
        return "BỊ_CHẶN", f"cần mở tay: {fr.reason}"

    if not open_ok:
        return fr.status or "BỊ_CHẶN", fr.reason

    if mr is None:
        # mở được nhưng không có STT để chấm
        if fr.ssl_insecure or fr.status == "LỖI_SSL_MỞ_ĐƯỢC":
            return "LỖI_SSL_MỞ_ĐƯỢC", fr.reason or "mở được (SSL), chưa chấm khớp"
        return "MỞ_ĐƯỢC_KHÔNG_KHỚP", fr.reason or "mở được, chưa chấm khớp"

    reasons = [x for x in (fr.reason, mr.reason) if x]
    reason = " | ".join(reasons)

    if mr.status == "CHỈ_KHỚP_CHUNG":
        return "CHỈ_KHỚP_CHUNG", reason
    if mr.status == "MỞ_ĐƯỢC_KHỚP":
        if fr.ssl_insecure or fr.status == "LỖI_SSL_MỞ_ĐƯỢC":
            return "LỖI_SSL_MỞ_ĐƯỢC", reason
        return "MỞ_ĐƯỢC_KHỚP", reason
    # không khớp
    if fr.ssl_insecure or fr.status == "LỖI_SSL_MỞ_ĐƯỢC":
        return "LỖI_SSL_MỞ_ĐƯỢC", reason
    return "MỞ_ĐƯỢC_KHÔNG_KHỚP", reason


def check_one(
    url: str,
    *,
    stt: str | int = "",
    nguon: str = "",
    use_cache: bool = True,
    keys: dict | None = None,
) -> LinkCheckRow:
    stt_s = str(stt).strip()
    fr = fetch(url, stt=stt_s, use_cache=use_cache)
    mr: MatchResult | None = None
    if stt_s.isdigit() and fr.status in ("MỞ_ĐƯỢC", "LỖI_SSL_MỞ_ĐƯỢC"):
        mr = match_text(fr.text or "", int(stt_s), keys)

    status, ly_do = _combine_status(fr, mr)
    return LinkCheckRow(
        stt=stt_s,
        url=url,
        nguon=nguon,
        tang=fr.tier,
        http_code=fr.http_code,
        final_url=fr.final_url,
        title=fr.title,
        content_type=fr.content_type,
        status=status,
        ly_do=ly_do,
        khop_ten=("1" if mr and mr.name_matched else "0") if mr else "",
        khop_dia_ban=("1" if mr and mr.dia_ban_matched else "0") if mr else "",
        so_icd_khac=mr.other_icd_count if mr else 0,
        suggested_stt=str(mr.suggested_stt) if mr and mr.suggested_stt else "",
        screenshot=fr.screenshot_path,
        text_path=fr.text_path,
        fetched_at=fr.fetched_at,
        ssl_insecure="1" if fr.ssl_insecure else "0",
        from_cache="1" if fr.from_cache else "0",
    )


def check_many(
    items: Iterable[tuple[str, str, str]],
    *,
    use_cache: bool = True,
    out_path: Path = OUT_CSV,
) -> list[LinkCheckRow]:
    """items: (stt, url, nguon)."""
    keys = load_keys()
    rows: list[LinkCheckRow] = []
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for stt, url, nguon in items:
            print(f"→ [{stt}] {url}", flush=True)
            row = check_one(url, stt=stt, nguon=nguon, use_cache=use_cache, keys=keys)
            print(
                f"  {row.status} tier={row.tang} http={row.http_code} "
                f"ten={row.khop_ten} dia={row.khop_dia_ban} others={row.so_icd_khac}",
                flush=True,
            )
            writer.writerow(row.to_dict())
            f.flush()
            rows.append(row)
    return rows


def load_tong_hop_links(path: Path = HIEN_TRANG) -> list[tuple[str, str, str]]:
    """Lấy link cột E từ dòng tong_hop (dedupe theo URL, giữ STT đầu)."""
    seen: set[str] = set()
    items: list[tuple[str, str, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("loai") or "") != "tong_hop":
                continue
            url = (row.get("link") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            items.append((row.get("stt") or "", url, "cot_E"))
    return items


def run_stability_test() -> int:
    """Chạy 2 lần cùng URL (có cache lần 2) — status phải giống nhau."""
    samples = [
        ("5", "https://baochinhphu.vn/bo-gtvt-cong-bo-mo-cang-can-dau-tien-tai-hai-phong-102246365.htm", "test"),
        ("1", "https://mt.gov.vn/cntt/tin-tuc/858/94903/cong-bo-mo-cang-can-dong-pho-moi-%28lao-cai%29.aspx", "test"),
    ]
    print("=== P1.3 stability (pass 1, no cache write reuse) ===", flush=True)
    # pass 1: allow cache from prior P1.1 runs
    r1 = [check_one(u, stt=s, nguon=n, use_cache=True) for s, u, n in samples]
    print("=== pass 2 (must hit cache) ===", flush=True)
    r2 = [check_one(u, stt=s, nguon=n, use_cache=True) for s, u, n in samples]

    ok = True
    for a, b in zip(r1, r2):
        same = (
            a.status == b.status
            and a.tang == b.tang
            and a.http_code == b.http_code
            and a.khop_ten == b.khop_ten
            and a.khop_dia_ban == b.khop_dia_ban
            and a.so_icd_khac == b.so_icd_khac
        )
        # lần 2 phải from_cache
        cached = b.from_cache == "1"
        print(
            f"{'PASS' if same and cached else 'FAIL'} stt={a.stt} "
            f"status={a.status}/{b.status} cache2={b.from_cache}",
            flush=True,
        )
        ok = ok and same and cached

    # ghi CSV mẫu
    out = ROOT / "data" / "link_check_stability.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for row in r1 + r2:
            w.writerow(row.to_dict())
    print(f"Wrote {out}", flush=True)
    print("ALL PASS" if ok else "SOME FAILED", flush=True)
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "test":
        return run_stability_test()
    if len(argv) >= 2 and argv[1] == "tong-hop":
        items = load_tong_hop_links()
        limit = None
        if "--limit" in argv:
            i = argv.index("--limit")
            limit = int(argv[i + 1])
            items = items[:limit]
        use_cache = "--no-cache" not in argv
        print(f"Checking {len(items)} unique cột-E links", flush=True)
        check_many(items, use_cache=use_cache)
        return 0
    if len(argv) >= 3:
        stt, url = argv[1], argv[2]
        nguon = argv[3] if len(argv) > 3 else "cli"
        row = check_one(url, stt=stt, nguon=nguon, use_cache="--no-cache" not in argv)
        print(row.to_dict())
        return 0
    print("Usage: python scripts/check_links.py test")
    print("       python scripts/check_links.py tong-hop [--limit N] [--no-cache]")
    print("       python scripts/check_links.py <stt> <url> [nguon]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
