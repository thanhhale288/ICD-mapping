"""Tạo lại data/phase3_summary.json và data/phase3_report.html từ dữ liệu hiện tại.

Chỉ đọc CSV trong data/ (không gọi mạng). Giữ nguyên các trường lịch sử không
tính lại được (`notes`, `recheck_bi_chan_tier2`) từ summary cũ.

    python scripts/phase3_summary.py
"""
from __future__ import annotations

import csv
import html
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SUMMARY = DATA / "phase3_summary.json"
REPORT = DATA / "phase3_report.html"
CHUA_DU = "Chưa đủ thông tin"
VN = timezone(timedelta(hours=7))


def _rows(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build_summary(old: dict | None = None) -> dict:
    old = old or {}
    uv = _rows("ung_vien.csv")
    chk = _rows("ung_vien_check.csv")
    wv = _rows("website_verify.csv")
    lc = _rows("link_chon.csv")
    tc = _rows("tra_cuu.csv")
    tt = _rows("trang_thai_de_xuat.csv")
    keys = _rows("icd_keys.csv")
    cdt = _rows("can_duyet_tay_trang_thai.csv")

    uv_urls = {r["url"].strip() for r in uv if r.get("url", "").strip()}
    uv_pairs = {(r["stt"].strip(), r["url"].strip()) for r in uv if r.get("stt", "").strip() and r.get("url", "").strip()}
    chk_pairs = {(r["stt"].strip(), r["url"].strip()) for r in chk}
    qd428 = sorted(int(r["stt"]) for r in keys if "428" in (r.get("phap_ly") or ""))
    lc_url = {r["stt"].strip() for r in lc if r.get("url_chon", "").strip()}
    non_cdtt = [r for r in tt if r["trang_thai"] != CHUA_DU]

    s = {
        "generated_at": datetime.now(VN).isoformat(timespec="seconds"),
        "phase": "3-fill",
        "trang_thai_rows": len(tt),
        "ung_vien_rows": len(uv),
        "ung_vien_unique_urls": len(uv_urls),
        "ung_vien_unique_pairs": len(uv_pairs),
        "ung_vien_stts_with_url": len({p[0] for p in uv_pairs}),
        "ung_vien_empty_stt_rows": sum(1 for r in uv if not r.get("stt", "").strip()),
        "unchecked_urls": len(uv_pairs - chk_pairs),
        "checked": len(chk),
        "checked_stts": len({r["stt"].strip() for r in chk}),
        "ung_vien_check_status": dict(Counter(r["status"] for r in chk).most_common()),
        "stts_with_MO_DUOC_KHOP": len({r["stt"].strip() for r in chk if r["status"] == "MỞ_ĐƯỢC_KHỚP"}),
        "website_verify_rows": len(wv),
        "website_verify_by_conclusion": dict(Counter(r["conclusion"] for r in wv).most_common()),
        "link_chon_rows": len(lc),
        "link_chon_with_url": len(lc_url),
        "link_chon_empty": len(lc) - len(lc_url),
        "qd428_with_link": sum(1 for s_ in qd428 if str(s_) in lc_url),
        "qd428_missing": [s_ for s_ in qd428 if str(s_) not in lc_url],
        "trang_thai_distribution": dict(Counter(r["trang_thai"] for r in tt).most_common()),
        "trang_thai_confidence": dict(Counter(r.get("do_tin_cay", "") for r in tt).most_common()),
        "trang_thai_no_source": sum(1 for r in tt if not r.get("url", "").strip()),
        "non_chua_du_missing_url": [r["stt"] for r in non_cdtt if not r.get("url", "").strip()],
        "non_chua_du_missing_cau_trich": [r["stt"] for r in non_cdtt if not r.get("cau_trich", "").strip()],
        "tra_cuu_fills": len(tc),
        "tra_cuu_stts": len({r["stt"] for r in tc}),
        "tra_cuu_missing_url_or_quote": sum(1 for r in tc if not r["url"].strip() or not r["cau_trich"].strip()),
        "can_duyet_tay": len(cdt),
    }
    for k in ("recheck_bi_chan_tier2", "notes"):
        if k in old:
            s[k] = old[k]
    return s


def render_html(s: dict) -> str:
    e = html.escape
    cards = [
        (s["ung_vien_unique_urls"], "URL ứng viên (unique)"),
        (s["checked"], "Cặp (stt,url) đã kiểm"),
        (s["unchecked_urls"], "Chưa kiểm"),
        (s["ung_vien_check_status"].get("MỞ_ĐƯỢC_KHỚP", 0), "MỞ_ĐƯỢC_KHỚP"),
        (s["link_chon_with_url"], "Link chọn G"),
        (f'{s["qd428_with_link"]}/{s["qd428_with_link"] + len(s["qd428_missing"])}', "QĐ428 có G"),
        (s["tra_cuu_fills"], "Tra cứu"),
    ]

    def table(title: str, d: dict, h: str) -> str:
        body = "".join(f"<tr><td>{e(str(k))}</td><td>{v}</td></tr>" for k, v in d.items())
        return f"<h2>{e(title)}</h2><table><thead><tr><th>{e(h)}</th><th>Số</th></tr></thead><tbody>{body}</tbody></table>"

    gaps = (
        f"Khác 'Chưa đủ thông tin' nhưng thiếu URL: {', '.join(s['non_chua_du_missing_url']) or 'không'}; "
        f"thiếu câu trích: {', '.join(s['non_chua_du_missing_cau_trich']) or 'không'}."
    )
    return (
        "<!DOCTYPE html><html lang=vi><head><meta charset=utf-8>"
        "<meta name=viewport content=\"width=device-width,initial-scale=1\"><title>Báo cáo Phase 3</title><style>"
        "body{font-family:\"Segoe UI\",Helvetica,Arial,sans-serif;background:#f6f4ef;color:#1c1917;margin:0;padding:24px;line-height:1.45}"
        ".cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:16px 0}"
        ".card{background:#fff;border:1px solid #d6d3d1;border-radius:8px;padding:14px;text-align:center}"
        ".num{font-size:1.7rem;font-weight:700;color:#0f766e}.lbl{color:#57534e;font-size:.85rem}"
        "table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #d6d3d1;font-size:.9rem;margin:12px 0}"
        "th,td{border-bottom:1px solid #d6d3d1;padding:8px 10px;text-align:left}th{background:#ebe8e2}"
        ".note{background:#ecfdf5;border:1px solid #99f6e4;border-radius:8px;padding:12px;margin-top:12px}.meta{color:#57534e}"
        "</style></head><body><h1>Báo cáo Phase 3</h1>"
        f"<p class=meta>Tạo lúc {e(s['generated_at'])} · {s['trang_thai_rows']} ICD · unchecked: <b>{s['unchecked_urls']}</b></p>"
        "<div class=cards>" + "".join(f"<div class=card><div class=num>{v}</div><div class=lbl>{e(l)}</div></div>" for v, l in cards) + "</div>"
        f"<div class=note>{e(gaps)}</div>"
        + table("Trạng thái đề xuất", s["trang_thai_distribution"], "Trạng thái")
        + table("Độ tin cậy", s["trang_thai_confidence"], "Mức")
        + table("Kiểm link (ung_vien_check)", s["ung_vien_check_status"], "Status")
        + table("Xác minh website", s["website_verify_by_conclusion"], "Kết luận")
        + "</body></html>\n"
    )


def main(argv: list[str]) -> int:
    old = json.loads(SUMMARY.read_text(encoding="utf-8")) if SUMMARY.exists() else {}
    s = build_summary(old)
    SUMMARY.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT.write_text(render_html(s), encoding="utf-8")
    print(json.dumps({k: v for k, v in s.items() if k != "notes"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
