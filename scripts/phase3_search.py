#!/usr/bin/env python3
"""
P3.2 – Tìm link ứng viên theo 3 lô (A/B/C).

Dùng scripts/search.py (Brave → Google cascade). Không cào SERP HTML.
Ghi append vào data/ung_vien.csv; resume-safe theo (stt, query).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import search as search_mod  # noqa: E402

KEYS_PATH = ROOT / "data" / "icd_keys.csv"
UNG_VIEN_PATH = ROOT / "data" / "ung_vien.csv"
PROGRESS_PATH = ROOT / "data" / "phase3_search_progress.json"
OPERATOR_NETWORKS_PATH = ROOT / "data" / "operator_networks.json"

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

# Keyword rotation for the 3rd/4th query templates
EXTRA_KEYWORDS = ("công bố mở", "khánh thành", "khởi công", "chủ đầu tư", "website")

# Duplicate-name + likely-active ICDs explicitly listed in the phase plan
LO_B_EXPLICIT = {
    15,
    98,
    126,  # Long Bình
    58,
    121,  # Tân Lập
    21,
    71,  # Thanh Thủy
    18,
    116,  # Thạnh Phước / Thanh Phước
    17,
    115,  # Cái Mép / Phước Hòa
    106,  # Sóng Thần
    107,  # TBS Tân Vạn
}

RATE_LIMIT_SEC = 1.5


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_keys() -> list[dict[str, str]]:
    with KEYS_PATH.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def short_name(row: dict[str, str]) -> str:
    """Tên ngắn để nhét vào query: ưu tiên alias thương hiệu; bỏ tiền tố Cảng cạn / ICD."""
    ten_chinh = (row.get("ten_chinh") or "").strip()
    aliases = [a.strip() for a in (row.get("ten_goi_khac") or "").split(";") if a.strip()]

    # Ngoặc thương hiệu (vd. Bình Hòa (Tân Cảng Sóng Thần)) — bỏ qua "(ICD)" thuần
    m = re.search(
        r"\(([^)]*(?:Tân Cảng|TBS|Gemadept|Hateco|VIMC|Transimex|Sóng Thần)[^)]*)\)",
        ten_chinh,
        re.I,
    )
    if m:
        inner = m.group(1).strip()
        if inner.upper() != "ICD":
            return inner

    # Ưu tiên alias có thương hiệu (không lấy alias chỉ là "ICD")
    brandish = [
        a
        for a in aliases
        if a.upper() != "ICD"
        and re.search(r"Tân Cảng|TBS|Gemadept|Hateco|VIMC|Transimex|Sóng Thần|Cảng", a, re.I)
    ]
    if brandish:
        name = brandish[0]
    elif aliases:
        name = aliases[0]
    else:
        name = ten_chinh

    # Bỏ tiền tố "Cảng cạn" / "Cảng cạn (ICD)" / "ICD "
    name = re.sub(
        r"^(?:Cảng cạn\s*(?:\(\s*ICD\s*\))?\s*|ICD\s+)",
        "",
        name,
        flags=re.I,
    ).strip()
    name = name.strip(" ,;")
    name = re.sub(r"\s*\(giai đoạn[^)]*\)\s*$", "", name, flags=re.I).strip()
    # Nếu còn sót "(ICD)" ở giữa tên → xóa
    name = re.sub(r"\(\s*ICD\s*\)\s*", "", name, flags=re.I).strip()
    # "Khu kinh tế cửa khẩu Thanh Thủy" → "Thanh Thủy"
    name = re.sub(r"^Khu kinh tế cửa khẩu\s+", "", name, flags=re.I).strip()
    return name or ten_chinh


def clean_province(value: str) -> str:
    v = (value or "").strip().rstrip(".")
    # Bỏ placeholder không dùng được trong query địa bàn
    bad = {
        "",
        "địa danh tài liệu quy hoạch",
        "địa giới",
        "địa danh",
        "địa danh tài liệu quy hoạch (cũ)",
        "địa giới (cũ)",
        "địa danh (cũ)",
    }
    if v.lower() in {b.lower() for b in bad}:
        return ""
    return v


def build_queries(row: dict[str, str]) -> list[str]:
    """
    3–4 queries / ICD:
      1. "cảng cạn <tên>" <tỉnh mới>
      2. "ICD <tên>" <tỉnh cũ>  (fallback tỉnh mới nếu thiếu tỉnh cũ)
      3. "cảng cạn <tên>" <tỉnh> <keyword>
      4. "ICD <tên>" <tỉnh> <keyword_alt>  (chỉ khi có tỉnh phụ khác hoặc STT chẵn → đủ 4)
    """
    ten = short_name(row)
    tinh_moi = clean_province(row.get("tinh_moi") or "")
    tinh_cu = clean_province(row.get("tinh_cu") or "")
    tinh_for_icd = tinh_cu or tinh_moi
    tinh_for_extra = tinh_moi or tinh_cu

    stt = int(row["stt"])
    kw1 = EXTRA_KEYWORDS[stt % len(EXTRA_KEYWORDS)]
    kw2 = EXTRA_KEYWORDS[(stt + 2) % len(EXTRA_KEYWORDS)]

    queries: list[str] = []
    if tinh_moi:
        queries.append(f'"cảng cạn {ten}" {tinh_moi}')
    else:
        queries.append(f'"cảng cạn {ten}"')

    if tinh_for_icd:
        queries.append(f'"ICD {ten}" {tinh_for_icd}')
    else:
        queries.append(f'"ICD {ten}"')

    if tinh_for_extra:
        queries.append(f'"cảng cạn {ten}" {tinh_for_extra} {kw1}')
    else:
        queries.append(f'"cảng cạn {ten}" {kw1}')

    # Query thứ 4 khi có tỉnh cũ khác tỉnh mới, hoặc luôn thêm website/chủ đầu tư xen kẽ
    if tinh_cu and tinh_cu != tinh_moi:
        queries.append(f'"ICD {ten}" {tinh_cu} {kw2}')
    elif stt % 2 == 0:
        loc = tinh_for_extra or ""
        q4 = f'"ICD {ten}" {loc} {kw2}'.strip()
        if q4 not in queries:
            queries.append(q4)

    # Dedup giữ thứ tự
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        q = re.sub(r"\s+", " ", q).strip()
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out[:4]


def lo_a_stts(rows: list[dict[str, str]]) -> set[int]:
    return {int(r["stt"]) for r in rows if "QĐ 428" in (r.get("phap_ly") or "")}


def operator_network_stts() -> set[int]:
    if not OPERATOR_NETWORKS_PATH.exists():
        return set()
    try:
        data = json.loads(OPERATOR_NETWORKS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    found: set[int] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k.lower() in {"stt", "icd_stt", "stt_icd"} and v is not None:
                    try:
                        found.add(int(v))
                    except (TypeError, ValueError):
                        pass
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return found


def lo_b_stts(rows: list[dict[str, str]]) -> set[int]:
    # All STTs that share a nhom_trung with the duplicate-name groups in the plan
    by_group: dict[str, list[int]] = {}
    for r in rows:
        g = (r.get("nhom_trung") or "").strip()
        if g:
            by_group.setdefault(g, []).append(int(r["stt"]))
    dup_groups = {
        "Long Bình",
        "Tân Lập",
        "Thanh Thủy",
        "Thạnh Phước/Thanh Phước",
        "Cái Mép",
    }
    stts = set(LO_B_EXPLICIT)
    for g in dup_groups:
        stts.update(by_group.get(g, []))
    stts |= operator_network_stts()
    return stts


def select_stts(
    rows: list[dict[str, str]],
    lo: str | None,
    stt_arg: list[int] | None,
) -> list[int]:
    all_stts = [int(r["stt"]) for r in rows]
    a = lo_a_stts(rows)
    b = lo_b_stts(rows)
    # Lô B excludes A for batch partitioning; Lô C = remaining
    b_only = b - a
    c = set(all_stts) - a - b_only

    if stt_arg:
        wanted = set(stt_arg)
        return [s for s in all_stts if s in wanted]

    if lo is None or lo == "all":
        # A then B then C order
        ordered = sorted(a) + sorted(b_only) + sorted(c)
        return ordered
    if lo == "A":
        return sorted(a)
    if lo == "B":
        return sorted(b_only | (b & a))  # include overlap names that are also in A
    if lo == "C":
        return sorted(c)
    raise ValueError(f"Lô không hợp lệ: {lo!r}")


def load_existing_ung_vien() -> tuple[list[dict[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
    """
    Returns (rows, done_queries as (stt,query), seen_urls as (stt,url)).
    """
    if not UNG_VIEN_PATH.exists():
        return [], set(), set()
    with UNG_VIEN_PATH.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    done: set[tuple[str, str]] = set()
    seen_urls: set[tuple[str, str]] = set()
    for r in rows:
        stt = (r.get("stt") or "").strip()
        q = (r.get("query") or "").strip()
        url = (r.get("url") or "").strip()
        if stt and q:
            done.add((stt, q))
        if stt and url:
            seen_urls.add((stt, url))
    return rows, done, seen_urls


def ensure_ung_vien_header() -> None:
    UNG_VIEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if UNG_VIEN_PATH.exists() and UNG_VIEN_PATH.stat().st_size > 0:
        return
    with UNG_VIEN_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=UNG_VIEN_COLUMNS)
        writer.writeheader()


def append_hits(rows_out: list[dict[str, str]]) -> None:
    if not rows_out:
        return
    ensure_ung_vien_header()
    with UNG_VIEN_PATH.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=UNG_VIEN_COLUMNS, extrasaction="ignore")
        for row in rows_out:
            writer.writerow({c: row.get(c, "") for c in UNG_VIEN_COLUMNS})


def write_progress(payload: dict[str, Any]) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_stt_list(raw: str) -> list[int]:
    parts = re.split(r"[,;\s]+", raw.strip())
    out: list[int] = []
    for p in parts:
        if not p:
            continue
        out.append(int(p))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P3.2 – tìm link ứng viên theo lô A/B/C")
    parser.add_argument("--lo", choices=["A", "B", "C", "all"], default=None, help="Chọn lô")
    parser.add_argument("--stt", type=str, default=None, help="Danh sách STT, ví dụ 1,2,8")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ in queries, không gọi API")
    parser.add_argument("--max-queries", type=int, default=None, help="Giới hạn số query API trong lần chạy")
    parser.add_argument("--count", type=int, default=10, help="Số kết quả / query (mặc định 10)")
    parser.add_argument("--sleep", type=float, default=RATE_LIMIT_SEC, help="Giây nghỉ giữa các request")
    args = parser.parse_args(argv)

    if args.lo is None and args.stt is None:
        parser.error("Cần --lo A|B|C|all hoặc --stt 1,2,8")

    keys = load_keys()
    by_stt = {int(r["stt"]): r for r in keys}
    stt_list = select_stts(
        keys,
        lo=args.lo,
        stt_arg=parse_stt_list(args.stt) if args.stt else None,
    )

    a_set = lo_a_stts(keys)
    b_set = lo_b_stts(keys)
    b_only = b_set - a_set
    c_set = set(by_stt) - a_set - b_only

    plan: list[tuple[int, str, list[str]]] = []
    for stt in stt_list:
        row = by_stt[stt]
        qs = build_queries(row)
        plan.append((stt, row.get("ten_chinh") or "", qs))

    if args.dry_run:
        total_q = 0
        for stt, ten, qs in plan:
            print(f"\n# STT {stt} — {ten}")
            for q in qs:
                print(f"  {q}")
                total_q += 1
        print(f"\n# Tổng: {len(plan)} ICD, {total_q} queries")
        print(f"# Lô A={len(a_set)} B(excl A)={len(b_only)} C={len(c_set)}")
        write_progress(
            {
                "mode": "dry-run",
                "updated_at": utc_now_iso(),
                "selected_stts": stt_list,
                "planned_queries": total_q,
                "lo_sizes": {"A": len(a_set), "B": len(b_only), "C": len(c_set)},
            }
        )
        return 0

    _, done_queries, seen_urls = load_existing_ung_vien()
    ensure_ung_vien_header()

    queries_ran = 0
    hits_written = 0
    queries_skipped = 0
    providers_used: dict[str, int] = {}
    errors: list[str] = []
    completed_stts: list[int] = []
    stopped_reason: str | None = None

    progress: dict[str, Any] = {
        "mode": "run",
        "started_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "lo": args.lo,
        "stt_filter": args.stt,
        "max_queries": args.max_queries,
        "selected_stts": stt_list,
        "lo_sizes": {"A": len(a_set), "B": len(b_only), "C": len(c_set)},
        "queries_ran": 0,
        "hits_written": 0,
        "queries_skipped": 0,
        "providers_used": {},
        "completed_stts": [],
        "stopped_reason": None,
        "errors": [],
    }
    write_progress(progress)

    for stt, ten, qs in plan:
        row_done_for_stt = True
        for q in qs:
            key = (str(stt), q)
            if key in done_queries:
                queries_skipped += 1
                continue

            if args.max_queries is not None and queries_ran >= args.max_queries:
                stopped_reason = f"Đạt --max-queries={args.max_queries}"
                row_done_for_stt = False
                break

            try:
                # Retry transient network/TLS timeouts; quota/provider exhaustion
                # still surfaces as RuntimeError from search_mod.search.
                hits, provider = None, None  # type: ignore[assignment]
                last_transient: Exception | None = None
                for attempt in range(1, 4):
                    try:
                        hits, provider = search_mod.search(q, count=args.count)
                        break
                    except RuntimeError:
                        raise
                    except Exception as e:
                        last_transient = e
                        wait = attempt * 5
                        print(
                            f"[STT {stt}] transient error attempt {attempt}/3: {e}; "
                            f"retry in {wait}s",
                            flush=True,
                        )
                        time.sleep(wait)
                else:
                    assert last_transient is not None
                    raise last_transient
            except RuntimeError as e:
                msg = str(e)
                errors.append(msg)
                stopped_reason = "Không còn search API khả dụng"
                progress.update(
                    {
                        "updated_at": utc_now_iso(),
                        "queries_ran": queries_ran,
                        "hits_written": hits_written,
                        "queries_skipped": queries_skipped,
                        "providers_used": providers_used,
                        "completed_stts": completed_stts,
                        "stopped_reason": stopped_reason,
                        "errors": errors[-5:],
                    }
                )
                write_progress(progress)
                print(msg, file=sys.stderr)
                print(
                    f"Dừng sau {queries_ran} queries, {hits_written} hits ghi mới.",
                    file=sys.stderr,
                )
                return 1
            except Exception as e:
                msg = f"Lỗi mạng/search không phục hồi: {e}"
                errors.append(msg)
                stopped_reason = "Lỗi mạng tạm thời — chạy lại --lo C để resume"
                progress.update(
                    {
                        "updated_at": utc_now_iso(),
                        "queries_ran": queries_ran,
                        "hits_written": hits_written,
                        "queries_skipped": queries_skipped,
                        "providers_used": providers_used,
                        "completed_stts": completed_stts,
                        "stopped_reason": stopped_reason,
                        "errors": errors[-5:],
                    }
                )
                write_progress(progress)
                print(msg, file=sys.stderr)
                print(
                    f"Dừng sau {queries_ran} queries, {hits_written} hits ghi mới.",
                    file=sys.stderr,
                )
                return 1

            queries_ran += 1
            providers_used[provider] = providers_used.get(provider, 0) + 1
            done_queries.add(key)

            batch: list[dict[str, str]] = []
            fetched_at = utc_now_iso()
            for h in hits:
                url = (h.url or "").strip()
                if not url:
                    continue
                url_key = (str(stt), url)
                if url_key in seen_urls:
                    continue
                seen_urls.add(url_key)
                batch.append(
                    {
                        "stt": str(stt),
                        "ten_icd": ten,
                        "url": url,
                        "nguon": h.provider or provider,
                        "loai_nguon": "web_search",
                        "query": q,
                        "provider": h.provider or provider,
                        "title": h.title or "",
                        "snippet": h.snippet or "",
                        "operator": "",
                        "fetched_at": fetched_at,
                    }
                )
            append_hits(batch)
            hits_written += len(batch)

            # Đánh dấu query đã chạy ngay cả khi 0 hit (ghi 1 dòng marker? — không;
            # resume dựa trên query trong CSV. Nếu 0 hit, cần marker để không lặp.)
            if not batch:
                # Ghi dòng marker không có URL để resume skip query này
                marker = {
                    "stt": str(stt),
                    "ten_icd": ten,
                    "url": "",
                    "nguon": provider,
                    "loai_nguon": "web_search",
                    "query": q,
                    "provider": provider,
                    "title": "",
                    "snippet": "(no results)",
                    "operator": "",
                    "fetched_at": fetched_at,
                }
                append_hits([marker])

            progress.update(
                {
                    "updated_at": utc_now_iso(),
                    "queries_ran": queries_ran,
                    "hits_written": hits_written,
                    "queries_skipped": queries_skipped,
                    "providers_used": providers_used,
                    "completed_stts": completed_stts,
                    "last_stt": stt,
                    "last_query": q,
                    "last_provider": provider,
                    "last_hits": len(hits),
                    "stopped_reason": stopped_reason,
                    "errors": errors[-5:],
                }
            )
            write_progress(progress)

            print(
                f"[STT {stt}] provider={provider} hits={len(hits)} written={len(batch)} q={q!r}",
                flush=True,
            )
            time.sleep(args.sleep)

        if stopped_reason:
            break
        if row_done_for_stt:
            completed_stts.append(stt)
            progress["completed_stts"] = completed_stts
            write_progress(progress)

    if stopped_reason is None:
        stopped_reason = "hoàn tất"

    progress.update(
        {
            "updated_at": utc_now_iso(),
            "finished_at": utc_now_iso(),
            "queries_ran": queries_ran,
            "hits_written": hits_written,
            "queries_skipped": queries_skipped,
            "providers_used": providers_used,
            "completed_stts": completed_stts,
            "stopped_reason": stopped_reason,
            "errors": errors[-5:],
        }
    )
    write_progress(progress)

    print(
        f"\nXong: queries_ran={queries_ran} hits_written={hits_written} "
        f"skipped={queries_skipped} providers={providers_used} reason={stopped_reason}"
    )
    print(f"ung_vien: {UNG_VIEN_PATH}")
    print(f"progress: {PROGRESS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
