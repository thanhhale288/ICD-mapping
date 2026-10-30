"""
P1.3 / P3.3 — Kiểm link: fetch.py → match.py → CSV kết quả.

Cột: STT, URL, nguồn, tầng mở được, mã HTTP, URL cuối, tiêu đề,
loại nội dung, trạng thái, lý do, khớp tên, khớp địa bàn,
số ICD khác được nhắc, ảnh chụp, thời điểm.

Usage:
  python3 scripts/check_links.py test
  python3 scripts/check_links.py tong-hop [--limit N] [--no-cache]
  python3 scripts/check_links.py ung-vien [--limit N] [--per-stt K]
      [--loai operator_network|web_search|all] [--stt 70,72,...]
      [--no-cache] [--max-tier T]
  python3 scripts/check_links.py <stt> <url> [nguon]
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch import FetchResult, fetch  # noqa: E402
from match import MatchResult, load_keys, match_text  # noqa: E402

OUT_CSV = ROOT / "data" / "link_check.csv"
UNG_VIEN_CSV = ROOT / "data" / "ung_vien.csv"
UNG_VIEN_CHECK_CSV = ROOT / "data" / "ung_vien_check.csv"
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
    max_tier: int = 3,
) -> LinkCheckRow:
    stt_s = str(stt).strip()
    fr = fetch(url, stt=stt_s, use_cache=use_cache, max_tier=max_tier)
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
    max_tier: int = 3,
    keep_rows: list[dict[str, Any]] | None = None,
) -> list[LinkCheckRow]:
    """items: (stt, url, nguon).

    keep_rows: existing CSV dicts to preserve (written first), e.g. prior
    ung-vien checks when appending a filtered --loai run.
    """
    keys = load_keys()
    rows: list[LinkCheckRow] = []
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        if keep_rows:
            for d in keep_rows:
                writer.writerow({c: d.get(c, "") for c in COLUMNS})
            f.flush()
        for stt, url, nguon in items:
            print(f"→ [{stt}] {url}", flush=True)
            row = check_one(
                url,
                stt=stt,
                nguon=nguon,
                use_cache=use_cache,
                keys=keys,
                max_tier=max_tier,
            )
            print(
                f"  {row.status} tier={row.tang} http={row.http_code} "
                f"ten={row.khop_ten} dia={row.khop_dia_ban} others={row.so_icd_khac}",
                flush=True,
            )
            writer.writerow(row.to_dict())
            f.flush()
            rows.append(row)
    return rows


def is_gov_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host.endswith(".gov.vn") or host == "gov.vn":
        return True
    if "chinhphu" in host:
        return True
    if "luatvietnam" in host or "thuvienphapluat" in host:
        return True
    return False


def _priority_rank(loai_nguon: str, url: str) -> tuple[int, int]:
    """Thấp hơn = ưu tiên hơn. (nhóm, phụ)."""
    loai = (loai_nguon or "").strip().lower()
    if loai == "operator_network":
        return (0, 0)
    if is_gov_url(url):
        return (1, 0)
    return (2, 0)


def _already_checked_keys(check_path: Path = UNG_VIEN_CHECK_CSV) -> set[tuple[str, str]]:
    if not check_path.exists():
        return set()
    out: set[tuple[str, str]] = set()
    with check_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            url = (row.get("url") or "").strip()
            if not url:
                continue
            out.add(((row.get("stt") or "").strip(), url))
    return out


def load_ung_vien_links(
    path: Path = UNG_VIEN_CSV,
    *,
    loai: str = "all",
    per_stt: int = 3,
    limit: int | None = None,
    only_stts: set[str] | None = None,
    unchecked_only: bool = False,
    check_path: Path = UNG_VIEN_CHECK_CSV,
) -> list[tuple[str, str, str]]:
    """Đọc ung_vien.csv → (stt, url, nguon) đã dedupe + ưu tiên + per-stt.

    Dedup: theo (stt, url); trong cùng STT chỉ giữ 1 bản mỗi URL.
    Ưu tiên: operator_network → gov (.gov.vn / chinhphu / luatvietnam) → khác.
    only_stts: nếu có, chỉ lấy các STT trong tập (vd. --stt 70,72).
    per_stt=0: không giới hạn số URL / STT.
    unchecked_only: bỏ URL đã có trong ung_vien_check.csv.
    """
    if not path.exists():
        return []

    skip = _already_checked_keys(check_path) if unchecked_only else set()
    loai_f = (loai or "all").strip().lower()
    raw: list[dict[str, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            url = (row.get("url") or "").strip()
            if not url:
                continue
            stt = (row.get("stt") or "").strip()
            if only_stts is not None and stt not in only_stts:
                continue
            if unchecked_only and (stt, url) in skip:
                continue
            loai_row = (row.get("loai_nguon") or "").strip()
            if loai_f != "all" and loai_row.lower() != loai_f:
                continue
            raw.append(
                {
                    "stt": stt,
                    "url": url,
                    "nguon": (row.get("nguon") or loai_row or "ung_vien").strip(),
                    "loai_nguon": loai_row,
                }
            )

    # Dedup (stt, url) — giữ bản có ưu tiên cao hơn
    best: dict[tuple[str, str], dict[str, str]] = {}
    for row in raw:
        key = (row["stt"], row["url"])
        prev = best.get(key)
        if prev is None or _priority_rank(row["loai_nguon"], row["url"]) < _priority_rank(
            prev["loai_nguon"], prev["url"]
        ):
            best[key] = row

    by_stt: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in best.values():
        by_stt[row["stt"]].append(row)

    items: list[tuple[str, str, str]] = []
    # STT số trước, rồi STT rỗng / khác
    def _stt_sort(s: str) -> tuple[int, str]:
        return (0, f"{int(s):06d}") if s.isdigit() else (1, s)

    for stt in sorted(by_stt.keys(), key=_stt_sort):
        group = by_stt[stt]
        group.sort(key=lambda r: (_priority_rank(r["loai_nguon"], r["url"]), r["url"]))
        # Dedup URL trong cùng STT (phòng khi url khác normalize)
        seen_url: set[str] = set()
        picked = 0
        for row in group:
            if row["url"] in seen_url:
                continue
            seen_url.add(row["url"])
            items.append((row["stt"], row["url"], row["nguon"]))
            picked += 1
            if per_stt > 0 and picked >= per_stt:
                break

    if limit is not None:
        items = items[:limit]
    return items


def _load_existing_check_rows(
    path: Path,
    *,
    exclude_keys: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    exclude_keys = exclude_keys or set()
    kept: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            stt = (row.get("stt") or "").strip()
            url = (row.get("url") or "").strip()
            if not url:
                continue
            if (stt, url) in exclude_keys:
                continue
            kept.append(dict(row))
    return kept


def run_ung_vien(
    *,
    loai: str = "all",
    per_stt: int = 3,
    limit: int | None = None,
    use_cache: bool = True,
    max_tier: int = 3,
    only_stts: set[str] | None = None,
    unchecked_only: bool = False,
    out_path: Path = UNG_VIEN_CHECK_CSV,
) -> list[LinkCheckRow]:
    items = load_ung_vien_links(
        UNG_VIEN_CSV,
        loai=loai,
        per_stt=per_stt,
        limit=limit,
        only_stts=only_stts,
        unchecked_only=unchecked_only,
        check_path=out_path,
    )
    exclude = {(stt, url) for stt, url, _ in items}
    keep = _load_existing_check_rows(out_path, exclude_keys=exclude)
    stt_note = f" stt={','.join(sorted(only_stts, key=lambda s: int(s) if s.isdigit() else 10**9))}" if only_stts else ""
    unchecked_note = " unchecked-only" if unchecked_only else ""
    print(
        f"ung-vien: loai={loai} per_stt={per_stt}{stt_note}{unchecked_note} "
        f"max_tier={max_tier} → check {len(items)} URL "
        f"(giữ {len(keep)} dòng cũ) → {out_path}",
        flush=True,
    )
    return check_many(
        items,
        use_cache=use_cache,
        out_path=out_path,
        max_tier=max_tier,
        keep_rows=keep,
    )


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


def _parse_int_flag(argv: list[str], name: str, default: int | None = None) -> int | None:
    if name not in argv:
        return default
    i = argv.index(name)
    if i + 1 >= len(argv):
        raise SystemExit(f"Missing value for {name}")
    return int(argv[i + 1])


def _parse_str_flag(argv: list[str], name: str, default: str) -> str:
    if name not in argv:
        return default
    i = argv.index(name)
    if i + 1 >= len(argv):
        raise SystemExit(f"Missing value for {name}")
    return argv[i + 1]


def _parse_stt_set(argv: list[str]) -> set[str] | None:
    """Parse --stt 70,72,75 or --stt 70 --stt 72 into a set of STT strings."""
    values: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--stt":
            if i + 1 >= len(argv):
                raise SystemExit("Missing value for --stt")
            values.append(argv[i + 1])
            i += 2
            continue
        i += 1
    if not values:
        return None
    out: set[str] = set()
    for chunk in values:
        for part in chunk.split(","):
            s = part.strip()
            if s:
                out.add(s)
    return out or None


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "test":
        return run_stability_test()
    if len(argv) >= 2 and argv[1] == "tong-hop":
        items = load_tong_hop_links()
        limit = _parse_int_flag(argv, "--limit")
        if limit is not None:
            items = items[:limit]
        use_cache = "--no-cache" not in argv
        max_tier = _parse_int_flag(argv, "--max-tier", 3) or 3
        print(f"Checking {len(items)} unique cột-E links", flush=True)
        check_many(items, use_cache=use_cache, max_tier=max_tier)
        return 0
    if len(argv) >= 2 and argv[1] == "ung-vien":
        loai = _parse_str_flag(argv, "--loai", "all")
        if loai not in ("operator_network", "web_search", "all"):
            print(
                "Invalid --loai; use operator_network|web_search|all",
                file=sys.stderr,
            )
            return 2
        per_stt = _parse_int_flag(argv, "--per-stt", 3)
        if per_stt is None:
            per_stt = 3
        limit = _parse_int_flag(argv, "--limit")
        use_cache = "--no-cache" not in argv
        max_tier = _parse_int_flag(argv, "--max-tier", 3)
        if max_tier is None:
            max_tier = 3
        only_stts = _parse_stt_set(argv)
        unchecked_only = "--unchecked-only" in argv
        run_ung_vien(
            loai=loai,
            per_stt=per_stt,
            limit=limit,
            use_cache=use_cache,
            max_tier=max_tier,
            only_stts=only_stts,
            unchecked_only=unchecked_only,
        )
        return 0
    if len(argv) >= 3 and argv[1] not in ("test", "tong-hop", "ung-vien"):
        stt, url = argv[1], argv[2]
        nguon = argv[3] if len(argv) > 3 and not argv[3].startswith("--") else "cli"
        max_tier = _parse_int_flag(argv, "--max-tier", 3) or 3
        row = check_one(
            url,
            stt=stt,
            nguon=nguon,
            use_cache="--no-cache" not in argv,
            max_tier=max_tier,
        )
        print(row.to_dict())
        return 0
    print("Usage: python scripts/check_links.py test")
    print("       python scripts/check_links.py tong-hop [--limit N] [--no-cache]")
    print(
        "       python scripts/check_links.py ung-vien [--limit N] [--per-stt K] "
        "[--loai operator_network|web_search|all] [--stt 70,72,...] "
        "[--unchecked-only] [--no-cache] [--max-tier T]\n"
        "         (per-stt 0 = không giới hạn / STT; --unchecked-only = chỉ URL chưa có trong ung_vien_check)"
    )
    print("       python scripts/check_links.py <stt> <url> [nguon]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
