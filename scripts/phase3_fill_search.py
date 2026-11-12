"""
P3.2-fill — tìm lại cho STT chưa có ứng viên, dùng query mới (tỉnh, chủ đầu tư, số QĐ, địa bàn).
Tái dùng helper của phase3_search.py; resume-safe theo (stt, query). Chỉ ghi kết quả thật từ API.

Usage: python3 scripts/phase3_fill_search.py --stt 22,32,... [--sleep 1.6] [--max-queries N]
"""
from __future__ import annotations
import argparse, json, re, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import phase3_search as ps  # noqa: E402
import search as search_mod  # noqa: E402

FILL_PROGRESS = ROOT / "data" / "phase3_fill_progress.json"

def first(v: str) -> str:
    return (v or "").split(";")[0].strip()

def build_fill_queries(row):
    ten = ps.short_name(row)
    tinh = ps.clean_province(row.get("tinh_moi") or "") or ps.clean_province(row.get("tinh_cu") or "")
    tinh_cu = ps.clean_province(row.get("tinh_cu") or "")
    cdt = re.sub(r"\s*\(.*?\)\s*", " ", first(row.get("chu_dau_tu") or "")).strip()
    qds = [q.strip() for q in (row.get("so_qd") or "").split(";") if q.strip() and "428" not in q]
    dia = [d.strip() for d in (row.get("khoa_dia_ban") or "").split(";") if d.strip() and d.strip() != tinh]
    qs = []
    qs.append(f"cảng cạn {ten} {tinh}".strip())                      # không ngoặc kép, rộng hơn
    if cdt:
        qs.append(f'"{cdt}" cảng cạn {tinh}'.strip())
    if qds:
        qs.append(f"{qds[0]} cảng cạn {ten}")
    if dia:
        qs.append(f"ICD {ten} {dia[0]} {tinh_cu or tinh}".strip())
    qs.append(f"quy hoạch cảng cạn {tinh} {ten}".strip())
    out, seen = [], set()
    for q in qs:
        q = re.sub(r"\s+", " ", q).strip()
        if q not in seen:
            seen.add(q); out.append(q)
    return out[:5]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stt", required=True)
    ap.add_argument("--sleep", type=float, default=1.6)
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--max-queries", type=int)
    a = ap.parse_args()
    keys = {int(r["stt"]): r for r in ps.load_keys()}
    stts = ps.parse_stt_list(a.stt)
    ps.ensure_ung_vien_header()
    _, done, seen = ps.load_existing_ung_vien()
    prog = {"mode": "fill", "selected_stts": stts, "queries_ran": 0, "hits_written": 0,
            "queries_skipped": 0, "stts_with_new_hits": [], "stopped_reason": None, "errors": []}
    ran = 0
    for stt in stts:
        row = keys[stt]; ten = row.get("ten_chinh", "")
        new_for_stt = 0
        for q in build_fill_queries(row):
            if (str(stt), q) in done:
                prog["queries_skipped"] += 1; continue
            if a.max_queries and ran >= a.max_queries:
                prog["stopped_reason"] = "max-queries"; break
            try:
                for att in range(3):
                    try:
                        hits, prov = search_mod.search(q, count=a.count); break
                    except RuntimeError:
                        raise
                    except Exception as e:
                        time.sleep(5 * (att + 1))
                else:
                    raise RuntimeError("transient x3")
            except RuntimeError as e:
                prog["stopped_reason"] = "search API unavailable"; prog["errors"].append(str(e)[:300])
                FILL_PROGRESS.write_text(json.dumps(prog, ensure_ascii=False, indent=2)); print(e, file=sys.stderr); return 1
            ran += 1; done.add((str(stt), q))
            now = ps.utc_now_iso(); batch = []
            for h in hits:
                u = (h.url or "").strip()
                if not u or (str(stt), u) in seen: continue
                seen.add((str(stt), u))
                batch.append({"stt": str(stt), "ten_icd": ten, "url": u, "nguon": prov, "loai_nguon": "web_search",
                              "query": q, "provider": prov, "title": h.title or "", "snippet": h.snippet or "",
                              "operator": "", "fetched_at": now})
            if not batch:
                batch = [{"stt": str(stt), "ten_icd": ten, "url": "", "nguon": prov, "loai_nguon": "web_search",
                          "query": q, "provider": prov, "title": "", "snippet": "(no results)", "operator": "", "fetched_at": now}]
            else:
                new_for_stt += len(batch)
            ps.append_hits(batch)
            prog["hits_written"] += sum(1 for b in batch if b["url"])
            prog["queries_ran"] = ran
            print(f"[STT {stt}] {q!r} -> {len(hits)} hits, {new_for_stt} new", flush=True)
            time.sleep(a.sleep)
        if new_for_stt: prog["stts_with_new_hits"].append(stt)
        prog["updated_at"] = ps.utc_now_iso()
        FILL_PROGRESS.write_text(json.dumps(prog, ensure_ascii=False, indent=2))
    FILL_PROGRESS.write_text(json.dumps(prog, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
