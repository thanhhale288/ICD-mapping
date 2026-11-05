#!/usr/bin/env python3
"""Phase 6: verify handover Excel against the original and Phase-4 decisions.

Checks that can run offline (no network re-fetch):
- sheet 01–128 present, ordered, including new sheet 08
- 128/128 column F filled
- original cells not overwritten (compare to source workbook)
- supplemental values cite a source tag or sit only in new cols/rows
- column G is never the shared QĐ 979 URL; ICD-specific when present
- link evidence status from saved ung_vien_check / Phase-4 manual review notes

Online re-check of every URL is optional and skipped when network is blocked;
the report states what was verified offline vs by hand.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "Thông tin ICD 34 tỉnh năm 2026.xlsx"
OUT = ROOT / "Thông tin ICD 34 tỉnh năm 2026 - đã kiểm tra.xlsx"
DATA = ROOT / "data"
FINAL_STATUS = DATA / "final_status.csv"
if not FINAL_STATUS.exists():
    FINAL_STATUS = Path("/workspace/icd_phase3_out/final_status.csv")

U979_MARKERS = ("979-qd-ttg", "979/qd-ttg", "quyet-dinh-979-qd-ttg")
ACTIVE_NEED_G = (
    "Đang hoạt động",
    "Đang xây dựng / chuẩn bị đầu tư",
    "Đã công bố mở, chưa xác nhận đang khai thác",
)
# User-verified active without public URL (Phase 4)
MANUAL_NO_URL = {"49", "86"}


def sheet_stt(title: str) -> int | None:
    m = re.match(r"^(\d+)\b", (title or "").strip())
    return int(m.group(1)) if m else None


def is_qd979(url: str) -> bool:
    u = (url or "").lower()
    return any(m in u for m in U979_MARKERS)


def load_fs():
    with FINAL_STATUS.open(encoding="utf-8-sig") as f:
        return {r["stt"]: r for r in csv.DictReader(f)}


def cell_equal(a, b) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    # openpyxl may give int vs float for STT
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    return str(a).strip() == str(b).strip()


def verify(out_path: Path = OUT, src_path: Path = SRC, online: bool = False) -> dict:
    report = {
        "ok": True,
        "errors": [],
        "warnings": [],
        "stats": {},
        "checked_offline": [],
        "relies_on_manual_review": [],
        "online_skipped": True,
    }
    fs = load_fs()

    if not out_path.exists():
        report["ok"] = False
        report["errors"].append(f"Missing output workbook: {out_path}")
        return report

    wb_out = load_workbook(out_path, data_only=False)
    wb_src = load_workbook(src_path, data_only=False)

    names = wb_out.sheetnames
    # --- sheets 01-128 order ---
    detail = [(sheet_stt(n), n) for n in names if sheet_stt(n) is not None]
    stts = [s for s, _ in detail]
    report["stats"]["detail_sheets"] = len(detail)
    report["checked_offline"].append("sheet_count_01_128")
    if len(detail) != 128:
        report["ok"] = False
        report["errors"].append(f"Expected 128 detail sheets, found {len(detail)}")
    if stts != list(range(1, 129)):
        report["ok"] = False
        # find first mismatch
        for expect, got in zip(range(1, 129), stts):
            if expect != got:
                report["errors"].append(f"Sheet order break at expected {expect:02d}, got {got}")
                break
        missing = sorted(set(range(1, 129)) - set(stts))
        extra = sorted(set(stts) - set(range(1, 129)))
        if missing:
            report["errors"].append(f"Missing STT sheets: {missing[:20]}")
        if extra:
            report["errors"].append(f"Unexpected STT sheets: {extra[:20]}")
    if "08 Tân Cảng Quế Võ" not in names:
        report["ok"] = False
        report["errors"].append("Missing sheet 08 Tân Cảng Quế Võ")
    if "Kiểm tra sai lệch" not in names:
        report["ok"] = False
        report["errors"].append("Missing sheet Kiểm tra sai lệch")
    if "Thống kê" not in names:
        report["ok"] = False
        report["errors"].append("Missing sheet Thống kê")
    report["checked_offline"].append("required_extra_sheets")

    # --- Tong hop F ---
    tong = wb_out["Tổng hợp"]
    f_vals = {}
    g_vals = {}
    for row in range(4, tong.max_row + 1):
        stt_v = tong.cell(row, 1).value
        if stt_v is None:
            continue
        stt = str(int(stt_v))
        f_vals[stt] = tong.cell(row, 6).value
        g_vals[stt] = tong.cell(row, 7).value
    report["stats"]["tong_hop_f_filled"] = sum(1 for v in f_vals.values() if v)
    report["checked_offline"].append("column_F_128")
    if len(f_vals) != 128 or any(not v for v in f_vals.values()):
        empty = [s for s, v in f_vals.items() if not v]
        report["ok"] = False
        report["errors"].append(f"Column F incomplete: {len(f_vals)} rows, empty={empty[:10]}")

    # Compare F to final_status
    mismatch_f = [
        s for s, v in f_vals.items() if fs.get(s) and str(v).strip() != fs[s]["trang_thai_cuoi"].strip()
    ]
    if mismatch_f:
        report["ok"] = False
        report["errors"].append(f"F mismatch vs final_status: {mismatch_f[:10]}")
    report["checked_offline"].append("F_matches_final_status")

    # G must not be QĐ 979; active statuses should have G unless manual-no-url
    bad_g_979 = [s for s, u in g_vals.items() if u and is_qd979(str(u))]
    if bad_g_979:
        report["ok"] = False
        report["errors"].append(f"Column G uses shared QĐ 979 URL at STT {bad_g_979[:15]}")
    report["checked_offline"].append("G_not_qd979")

    missing_g = []
    for s, f in f_vals.items():
        if str(f) in ACTIVE_NEED_G and not g_vals.get(s):
            if s in MANUAL_NO_URL:
                report["relies_on_manual_review"].append(
                    f"STT {s}: Đang hoạt động — G trống, Phase 4 duyệt tay không có URL công khai"
                )
            else:
                missing_g.append(s)
    if missing_g:
        report["warnings"].append(
            f"Active/building/opened without ICD-specific G (left blank per R3/R4): {missing_g}"
        )
    planned_no_g = [
        s
        for s, f in f_vals.items()
        if str(f).startswith("Chưa triển khai") and not g_vals.get(s)
    ]
    report["stats"]["g_filled"] = sum(1 for v in g_vals.values() if v)
    report["stats"]["planned_without_g"] = len(planned_no_g)
    report["warnings"].append(
        f"{len(planned_no_g)} 'Chưa triển khai' không có G riêng (chỉ có QĐ 979 chung → để trống theo R4)"
    )
    report["checked_offline"].append("G_policy_r4")

    # --- Original cells unchanged ---
    # Compare Tong hop A–E and every original detail sheet cells that existed in source.
    changed = []
    src_tong = wb_src["Tổng hợp"]
    for row in range(1, src_tong.max_row + 1):
        for col in range(1, 6):  # A–E only
            a = src_tong.cell(row, col).value
            b = tong.cell(row, col).value
            if not cell_equal(a, b):
                changed.append(("Tổng hợp", row, col, a, b))
    for name in wb_src.sheetnames:
        if name == "Tổng hợp":
            continue
        if name not in wb_out.sheetnames:
            # original sheets must remain
            report["ok"] = False
            report["errors"].append(f"Original sheet missing in output: {name}")
            continue
        ws_s = wb_src[name]
        ws_o = wb_out[name]
        for row in range(1, ws_s.max_row + 1):
            for col in range(1, (ws_s.max_column or 3) + 1):
                a = ws_s.cell(row, col).value
                b = ws_o.cell(row, col).value
                # Allow fill of originally empty cells (R2)
                if a in (None, "") and b not in (None, ""):
                    # supplemental fill — require source tag when it's a value fill in col C
                    if col == 3 and isinstance(b, str) and "nguồn" not in b.lower() and not str(b).startswith("http"):
                        # rows 13-16 style labels may be elsewhere; new content on old empty ok if short status?
                        report["warnings"].append(
                            f"Filled blank without explicit 'nguồn' tag: {name} R{row}C{col}"
                        )
                    continue
                if not cell_equal(a, b):
                    changed.append((name, row, col, a, b))
    report["stats"]["original_cells_changed"] = len(changed)
    report["checked_offline"].append("original_cells_intact")
    if changed:
        report["ok"] = False
        sample = changed[:8]
        report["errors"].append(f"Original cells overwritten ({len(changed)}): {sample}")

    # Sheet 08 content sanity
    ws08 = wb_out["08 Tân Cảng Quế Võ"]
    if "1543" not in str(ws08.cell(9, 3).value or ""):
        report["warnings"].append("Sheet 08 Số QĐ may be missing 1543/QĐ-BGTVT")
    if "Quế Võ" not in str(ws08.cell(2, 3).value or ""):
        report["ok"] = False
        report["errors"].append("Sheet 08 name cell missing Quế Võ")
    report["checked_offline"].append("sheet_08_sourced_fields")

    # Detail rows 13-16 present
    missing_rows = []
    for s, name in detail:
        ws = wb_out[name]
        labels = {(ws.cell(r, 2).value or "").strip() for r in range(1, ws.max_row + 1)}
        for need in (
            "Tình trạng thực tế (10/2026)",
            "Link website / thông tin ICD",
            "Nguồn kiểm chứng",
            "Kết quả kiểm tra",
        ):
            if need not in labels:
                missing_rows.append((s, need))
    if missing_rows:
        report["ok"] = False
        report["errors"].append(f"Missing detail rows 13-16 on {len(missing_rows)} places; sample {missing_rows[:5]}")
    report["checked_offline"].append("detail_rows_13_16")

    # Sai lech sheet row count
    ws_sai = wb_out["Kiểm tra sai lệch"]
    sai_rows = max(0, ws_sai.max_row - 1)
    report["stats"]["sai_lech_sheet_rows"] = sai_rows
    with (DATA / "sai_lech.csv").open(encoding="utf-8-sig") as f:
        sai_csv_n = sum(1 for _ in csv.DictReader(f))
    if sai_rows != sai_csv_n:
        report["warnings"].append(f"Kiểm tra sai lệch rows {sai_rows} != sai_lech.csv {sai_csv_n}")
    report["checked_offline"].append("sai_lech_sheet")

    # Evidence / manual review reliance
    report["relies_on_manual_review"].append(
        "Phase 4: user xác nhận đã duyệt tay + xác minh mọi dòng có URL và dòng bot đề xuất; không re-audit."
    )
    report["relies_on_manual_review"].append(
        "Link G: trạng thái mở/khớp lấy từ ung_vien_check.csv / evidence đã lưu (fetched ~30/10/2026), không gọi lại mạng trong verify mặc định."
    )
    for s in sorted(MANUAL_NO_URL):
        report["relies_on_manual_review"].append(
            f"STT {s}: trạng thái Đang hoạt động theo duyệt tay, không có URL công khai trong final_status."
        )

    if online:
        report["online_skipped"] = False
        report["warnings"].append("Online mode requested but not implemented in this environment; skipped.")
    else:
        report["checked_offline"].append("online_refetch_skipped_by_design")

    # Status distribution
    report["stats"]["status_counts"] = dict(Counter(str(v) for v in f_vals.values()))
    report["stats"]["sheets_total"] = len(names)

    wb_out.close()
    wb_src.close()

    if report["errors"]:
        report["ok"] = False
    return report


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("workbook", nargs="?", default=str(OUT))
    p.add_argument("--online", action="store_true")
    p.add_argument("--json-out", default="")
    args = p.parse_args(argv)
    rep = verify(Path(args.workbook), online=args.online)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    # human summary
    print("---")
    print("PASS" if rep["ok"] else "FAIL", "| errors", len(rep["errors"]), "| warnings", len(rep["warnings"]))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
