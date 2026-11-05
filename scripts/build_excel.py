#!/usr/bin/env python3
"""Phase 5: build handover Excel from the original workbook.

Rules (plan-final.md):
- Never overwrite original cells (R1/R2); only fill blanks or new cols/rows.
- Column G must be ICD-specific (R4); never the shared QĐ 979 URL.
- Sheet 08 is created from the QĐ 428 template (clone of sheet 09), content only with sources.
"""
from __future__ import annotations

import csv
import re
import shutil
import sys
from copy import copy
from pathlib import Path
from urllib.parse import urlparse

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.hyperlink import Hyperlink

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "Thông tin ICD 34 tỉnh năm 2026.xlsx"
OUT = ROOT / "Thông tin ICD 34 tỉnh năm 2026 - đã kiểm tra.xlsx"
DATA = ROOT / "data"
FINAL_STATUS = Path("/workspace/icd_phase3_out/final_status.csv")
U979 = (
    "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/"
    "Quyet-dinh-979-QD-TTg-2023-phe-duyet-Quy-hoach-phat-trien-he-thong-cang-can-2021-2030-576467.aspx"
)
SRC_TAG = "(nguồn: {host}, 10/2026)"

# Sheet 08 content — only facts with saved evidence / Phase-2 cross-check.
SHEET08 = {
    "ten": "Cảng cạn Tân Cảng Quế Võ",
    "tinh_trang": (
        "Trong danh mục 19 cảng cạn theo QĐ 428/QĐ-BXD ngày 31/3/2026. "
        "QĐ công bố mở: 1543/QĐ-BGTVT ngày 19/8/2021. "
        "Không đồng nhất công bố mở với sản lượng thực tế."
    ),
    "vi_tri": (
        "Xã Đức Long, Châu Phong, huyện Quế Võ, tỉnh Bắc Ninh; "
        "cảng nội địa trên hạ lưu sông Đuống, giáp quốc lộ 18 "
        "(nguồn: thuonghieucongluan.com.vn / saigonnewport.com.vn, 10/2026)."
    ),
    "loi_the": (
        "Cảng đích / trung tâm kiểm hoá tập trung phục vụ XNK Bắc Ninh và lân cận; "
        "kết nối đường thủy sông Cấm – Kinh Thầy – Đuống "
        "(nguồn: saigonnewport.com.vn, 10/2026)."
    ),
    "ket_noi": (
        "Đường thủy nội địa (sà lan) và đường bộ (QL18); "
        "liên kết cảng nước sâu Tân Cảng – HICT "
        "(nguồn: saigonnewport.com.vn, 10/2026)."
    ),
    "chu_dau_tu": "Công ty Cổ phần Tân Cảng Quế Võ (nguồn: thuonghieucongluan.com.vn, 10/2026).",
    "don_vi_khai_thac": "Tổng công ty Tân Cảng Sài Gòn (nguồn: saigonnewport.com.vn, 10/2026).",
    "so_qd": "1543/QĐ-BGTVT ngày 19/8/2021 (nguồn: saigonnewport.com.vn / baoxaydung.vn, 10/2026).",
    "quy_mo": (
        "Quy mô khoảng 10 ha; cầu tàu ~650 m, 5 cẩu bờ Liebherr; "
        "đón sà lan tối đa ~160 TEU "
        "(nguồn: hungdong.com.vn / thuonghieucongluan.com.vn, 10/2026)."
    ),
    "dich_vu": (
        "Khai thác cảng cạn, thủ tục XNK theo NĐ 38/2017/NĐ-CP; "
        "M&R; kho CFS / bãi container lạnh / vận tải đa phương thức theo phạm vi công bố "
        "(nguồn: saigonnewport.com.vn / thuonghieucongluan.com.vn, 10/2026)."
    ),
    "khach_hang": (
        "Doanh nghiệp XNK Bắc Ninh, Bắc Giang và các tỉnh lân cận "
        "(nguồn: saigonnewport.com.vn, 10/2026)."
    ),
    "canh_tranh": None,  # no sourced statement → leave blank
    "hang_tau": (
        "Maersk, HMM, Wanhai, SITC, SM Line, Dongjin… "
        "(nguồn: saigonnewport.com.vn, 10/2026)."
    ),
}

NEW_ROWS = [
    (13, "Tình trạng thực tế (10/2026)"),
    (14, "Link website / thông tin ICD"),
    (15, "Nguồn kiểm chứng"),
    (16, "Kết quả kiểm tra"),
]


def _host(url: str) -> str:
    if not url:
        return ""
    return urlparse(url).netloc.replace("www.", "")


def _is_qd979(url: str) -> bool:
    if not url:
        return False
    u = url.lower()
    return "979-qd-ttg" in u or "979/qd-ttg" in u or u.rstrip("/") == U979.lower().rstrip("/")


def _copy_cell_style(src, dst):
    if src.has_style:
        dst.font = copy(src.font)
        dst.border = copy(src.border)
        dst.fill = copy(src.fill)
        dst.number_format = src.number_format
        dst.protection = copy(src.protection)
        dst.alignment = copy(src.alignment)


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_inputs():
    fs = {r["stt"]: r for r in _read_csv(FINAL_STATUS)}
    lc = {r["stt"]: r for r in _read_csv(DATA / "link_chon.csv")}
    ov = {r["stt"]: r for r in _read_csv(DATA / "trang_thai_override.csv")}
    tc_rows = _read_csv(DATA / "tra_cuu.csv")
    sai = _read_csv(DATA / "sai_lech.csv")
    # ung_vien_check index for link evidence status
    uv = {}
    for r in _read_csv(DATA / "ung_vien_check.csv"):
        key = (r.get("stt") or "", (r.get("url") or "").rstrip("/"))
        if key[1]:
            uv[key] = r
    return fs, lc, ov, tc_rows, sai, uv


def pick_g(stt: str, fs_row: dict, lc_row: dict | None) -> tuple[str, str]:
    """Return (url_g, reason). Prefer link_chon, then final_status; never QĐ 979."""
    candidates = []
    if lc_row and lc_row.get("url_chon"):
        candidates.append((lc_row["url_chon"].strip(), "link_chon"))
    if fs_row.get("url"):
        candidates.append((fs_row["url"].strip(), "final_status"))
    for url, src in candidates:
        if url and not _is_qd979(url):
            return url, src
    return "", "empty_r4_or_missing"


def ket_qua_kiem_tra(stt: str, fs_row: dict, sai_rows: list[dict], g_url: str, uv: dict) -> str:
    issues = [r for r in sai_rows if r.get("stt") == stt and (r.get("ket_luan") or "") in ("sai", "ghi_nhan")]
    sai_only = [r for r in issues if r.get("ket_luan") == "sai"]
    status = ""
    if g_url:
        hit = uv.get((stt, g_url.rstrip("/")))
        if hit:
            status = hit.get("status") or ""
    if fs_row.get("nguon") == "duyet_tay":
        base = "ĐÃ_XÁC_MINH_TAY (duyệt thủ công Phase 4)"
    elif status in ("MỞ_ĐƯỢC_KHỚP", "LỖI_SSL_MỞ_ĐƯỢC"):
        base = status
    elif status:
        base = f"Có nguồn ({status}); đã duyệt Phase 4"
    elif g_url:
        base = "Có URL đính kèm; dựa vào xác minh tay / evidence đã lưu (không re-fetch online)"
    else:
        base = "Không có URL công khai riêng; kết luận theo duyệt tay Phase 4" if fs_row.get("nguon") == "duyet_tay" else "Chưa có URL riêng (R4)"
    if sai_only:
        base += f"; {len(sai_only)} phát hiện sai lệch (xem sheet Kiểm tra sai lệch)"
    elif issues:
        base += f"; {len(issues)} ghi nhận đối chiếu"
    return base


def ghi_chu(stt: str, fs_row: dict, ov_row: dict | None, g_src: str) -> str:
    parts = []
    if ov_row and ov_row.get("ly_do"):
        parts.append(ov_row["ly_do"].strip())
    elif fs_row.get("cau_trich"):
        parts.append(f'Trích: "{fs_row["cau_trich"][:180]}"')
    parts.append(f"Nguồn trạng thái: {fs_row.get('nguon') or '?'}")
    if g_src:
        parts.append(f"G từ: {g_src}")
    if stt in ("49", "86"):
        parts.append("User duyệt tay xác nhận Đang hoạt động; chưa có nguồn công khai → G để trống (R3/R4)")
    if stt == "126":
        parts.append("Chưa đủ thông tin; không có trong QĐ 979 và chưa có nguồn công khai")
    return " | ".join(p for p in parts if p)


def create_sheet_08(wb):
    template = wb["09 Tiên Sơn"]
    # Clone by copying workbook sheet
    ws = wb.copy_worksheet(template)
    ws.title = "08 Tân Cảng Quế Võ"
    # Move after sheet 07
    idx_07 = wb.sheetnames.index("07 Nam Đình Vũ giai đoạn 1")
    # copy_worksheet appends at end; relocate
    current = wb.sheetnames.index(ws.title)
    offset = idx_07 + 1 - current
    wb.move_sheet(ws, offset=offset)

    values = {
        2: SHEET08["ten"],  # Tên
        3: SHEET08["tinh_trang"],
        4: SHEET08["vi_tri"],
        5: SHEET08["loi_the"],
        6: SHEET08["ket_noi"],
        7: SHEET08["chu_dau_tu"],
        8: SHEET08["don_vi_khai_thac"],
        9: SHEET08["so_qd"],
        10: SHEET08["quy_mo"],
        11: SHEET08["dich_vu"],
        12: SHEET08["khach_hang"],
        13: SHEET08["canh_tranh"],
        14: SHEET08["hang_tau"],
    }
    for row, val in values.items():
        cell = ws.cell(row, 3)
        cell.value = val
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    return ws


def extend_tong_hop(ws, fs, lc, ov, sai, uv):
    # Unmerge A1:E1 and remarge A1:I1
    merged = [str(r) for r in ws.merged_cells.ranges]
    if "A1:E1" in merged:
        ws.unmerge_cells("A1:E1")
    ws.merge_cells("A1:I1")
    title = ws["A1"]
    title.value = "TỔNG HỢP ICD 34 TỈNH THÀNH"
    title.font = Font(name="Times New Roman", size=14, bold=True)
    title.alignment = Alignment(horizontal="center", vertical="center")

    headers = {
        6: "Tình trạng hoạt động (10/2026)",
        7: "Link website / thông tin ICD",
        8: "Kết quả kiểm tra thông tin",
        9: "Ghi chú kiểm tra",
    }
    ref = ws.cell(3, 5)
    for col, text in headers.items():
        c = ws.cell(3, col, text)
        _copy_cell_style(ref, c)
        c.font = Font(name=ref.font.name or "Times New Roman", size=ref.font.size or 11, bold=True)
        c.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")

    for col, width in zip(range(6, 10), (32, 45, 40, 50)):
        ws.column_dimensions[get_column_letter(col)].width = width

    sai_by_stt = {}
    for r in sai:
        sai_by_stt.setdefault(r["stt"], []).append(r)

    n = 0
    for row in range(4, ws.max_row + 1):
        stt_val = ws.cell(row, 1).value
        if stt_val is None:
            continue
        stt = str(int(stt_val))
        fs_row = fs[stt]
        lc_row = lc.get(stt)
        ov_row = ov.get(stt)
        g_url, g_src = pick_g(stt, fs_row, lc_row)
        h = ket_qua_kiem_tra(stt, fs_row, sai_by_stt.get(stt, []), g_url, uv)
        i = ghi_chu(stt, fs_row, ov_row, g_src)

        vals = {
            6: fs_row["trang_thai_cuoi"],
            7: g_url or None,
            8: h,
            9: i,
        }
        ref_row = ws.cell(row, 5)
        for col, v in vals.items():
            c = ws.cell(row, col, v)
            _copy_cell_style(ref_row, c)
            c.alignment = Alignment(wrap_text=True, vertical="top")
        if g_url:
            cell_g = ws.cell(row, 7)
            cell_g.hyperlink = g_url
            cell_g.style = "Hyperlink"
            cell_g.value = g_url
        n += 1
    return n


def fill_blank_from_tra_cuu(ws, stt: str, tc_for_stt: list[dict]) -> int:
    """Fill empty C cells when tra_cuu has matching hang_muc + url + quote."""
    if not tc_for_stt:
        return 0
    filled = 0
    for row in range(2, min(ws.max_row, 14) + 1):
        hm = (ws.cell(row, 2).value or "").strip()
        cell = ws.cell(row, 3)
        if cell.value not in (None, ""):
            continue
        # Never overwrite Tình trạng legal layer
        if hm == "Tình trạng":
            continue
        for t in tc_for_stt:
            th = (t.get("hang_muc") or "").strip()
            if not th or not t.get("url") or not t.get("gia_tri"):
                continue
            if th.lower() == hm.lower() or th.lower() in hm.lower() or hm.lower() in th.lower():
                host = _host(t["url"])
                cell.value = f"{t['gia_tri'].strip()} {SRC_TAG.format(host=host or 'nguồn')}"
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                filled += 1
                break
    return filled


def append_detail_rows(ws, stt: str, fs_row: dict, g_url: str, h_text: str, i_text: str):
    """Append hạng mục 13–16 after existing content (do not overwrite rows 1–14)."""
    # Find last used row among 1..14 content; append after max_row of template block
    base = 14
    # If sheet already has more rows from a prior run, don't duplicate labels
    existing_labels = {
        (ws.cell(r, 2).value or "").strip() for r in range(1, ws.max_row + 1)
    }
    ref = ws.cell(base, 2)
    ref_c = ws.cell(base, 3)
    values = {
        13: fs_row["trang_thai_cuoi"],
        14: g_url or None,
        15: (
            f"{fs_row.get('url') or g_url or '(không có URL)'} — "
            f"{(fs_row.get('cau_trich') or i_text or '')[:240]}"
        ),
        16: h_text,
    }
    for stt_no, label in NEW_ROWS:
        if label in existing_labels:
            # update existing
            for r in range(1, ws.max_row + 1):
                if (ws.cell(r, 2).value or "").strip() == label:
                    target = r
                    break
        else:
            target = ws.max_row + 1
            ws.cell(target, 1).value = stt_no
            ws.cell(target, 2).value = label
            _copy_cell_style(ws.cell(base, 1), ws.cell(target, 1))
            _copy_cell_style(ref, ws.cell(target, 2))
        c = ws.cell(target, 3)
        c.value = values[stt_no]
        _copy_cell_style(ref_c, c)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if stt_no == 14 and g_url:
            c.hyperlink = g_url
            c.style = "Hyperlink"
            c.value = g_url
        ws.row_dimensions[target].height = 45


def add_sai_lech_sheet(wb, sai):
    if "Kiểm tra sai lệch" in wb.sheetnames:
        del wb["Kiểm tra sai lệch"]
    ws = wb.create_sheet("Kiểm tra sai lệch")
    headers = [
        "STT",
        "Tên ICD",
        "Sheet",
        "Hạng mục",
        "Nội dung hiện tại",
        "Phát hiện",
        "Link nguồn",
        "Loại",
        "Đề xuất sửa",
    ]
    thin = Side(style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_fill = PatternFill("solid", fgColor="D9E2F3")
    for i, h in enumerate(headers, 1):
        c = ws.cell(1, i, h)
        c.font = Font(name="Times New Roman", bold=True, size=11)
        c.fill = header_fill
        c.border = border
        c.alignment = Alignment(wrap_text=True, horizontal="center")
    for col, w in enumerate([6, 28, 18, 22, 40, 40, 40, 18, 40], 1):
        ws.column_dimensions[get_column_letter(col)].width = w

    for i, r in enumerate(sai, 2):
        vals = [
            int(r["stt"]) if str(r.get("stt", "")).isdigit() else r.get("stt"),
            r.get("ten"),
            r.get("sheet"),
            r.get("hang_muc"),
            r.get("noi_dung_hien_tai"),
            r.get("phat_hien"),
            r.get("link_nguon") or r.get("nguon_thay_the"),
            r.get("loai"),
            r.get("de_xuat_sua"),
        ]
        for j, v in enumerate(vals, 1):
            c = ws.cell(i, j, v)
            c.font = Font(name="Times New Roman", size=10)
            c.border = border
            c.alignment = Alignment(wrap_text=True, vertical="top")
        link = vals[6]
        if link and str(link).startswith("http"):
            ws.cell(i, 7).hyperlink = str(link)
    return len(sai)


def add_thong_ke_sheet(wb, fs, lc, sai):
    if "Thống kê" in wb.sheetnames:
        del wb["Thống kê"]
    ws = wb.create_sheet("Thống kê")
    from collections import Counter

    status_c = Counter(r["trang_thai_cuoi"] for r in fs.values())
    nguon_c = Counter(r["nguon"] for r in fs.values())
    loai_c = Counter(r.get("loai") or "?" for r in sai)
    g_filled = sum(1 for s, r in fs.items() if pick_g(s, r, lc.get(s))[0])
    g_empty = 128 - g_filled
    ket_luan_c = Counter(r.get("ket_luan") or "?" for r in sai)

    ws["A1"] = "THỐNG KÊ KẾT QUẢ KIỂM TRA ICD (Phase 5)"
    ws["A1"].font = Font(name="Times New Roman", size=14, bold=True)
    ws.merge_cells("A1:C1")

    row = 3
    ws.cell(row, 1, "1. Số ICD theo trạng thái hoạt động (cột F)").font = Font(bold=True)
    row += 1
    ws.cell(row, 1, "Trạng thái")
    ws.cell(row, 2, "Số lượng")
    row += 1
    for k, v in status_c.most_common():
        ws.cell(row, 1, k)
        ws.cell(row, 2, v)
        row += 1
    ws.cell(row, 1, "Tổng")
    ws.cell(row, 2, sum(status_c.values()))
    row += 2

    ws.cell(row, 1, "2. Nguồn kết luận trạng thái").font = Font(bold=True)
    row += 1
    for k, v in nguon_c.most_common():
        ws.cell(row, 1, k)
        ws.cell(row, 2, v)
        row += 1
    row += 1

    ws.cell(row, 1, "3. Cột G (link ICD-specific, không dùng URL chung QĐ 979)").font = Font(bold=True)
    row += 1
    ws.cell(row, 1, "Có URL G")
    ws.cell(row, 2, g_filled)
    row += 1
    ws.cell(row, 1, "Để trống (R3/R4 hoặc chưa có nguồn riêng)")
    ws.cell(row, 2, g_empty)
    row += 2

    ws.cell(row, 1, "4. Sai lệch theo loại (từ data/sai_lech.csv)").font = Font(bold=True)
    row += 1
    for k, v in loai_c.most_common():
        ws.cell(row, 1, k)
        ws.cell(row, 2, v)
        row += 1
    row += 1
    ws.cell(row, 1, "5. Kết luận sai lệch").font = Font(bold=True)
    row += 1
    for k, v in ket_luan_c.most_common():
        ws.cell(row, 1, k)
        ws.cell(row, 2, v)
        row += 1
    row += 2
    ws.cell(row, 1, "Ghi chú").font = Font(bold=True)
    row += 1
    ws.cell(
        row,
        1,
        "Số liệu trạng thái lấy từ final_status.csv đã chốt sau Phase 4 (user duyệt tay). "
        "Không re-fetch toàn bộ link online trong Phase 5; kiểm chứng dựa trên evidence/ và xác minh tay.",
    )
    ws.column_dimensions["A"].width = 70
    ws.column_dimensions["B"].width = 12
    return dict(status_c), g_filled


def sheet_stt(title: str) -> str | None:
    m = re.match(r"^(\d+)\b", title.strip())
    return str(int(m.group(1))) if m else None


def build(dest: Path | None = None) -> dict:
    dest = dest or OUT
    fs, lc, ov, tc_rows, sai, uv = load_inputs()
    assert len(fs) == 128, len(fs)

    # Always start from pristine original
    shutil.copy2(SRC, dest)
    wb = load_workbook(dest)

    # P5.1 sheet 08
    create_sheet_08(wb)

    # P5.2 Tong hop F–I
    tong = wb["Tổng hợp"]
    n_th = extend_tong_hop(tong, fs, lc, ov, sai, uv)

    # Index tra_cuu
    tc_by = {}
    for r in tc_rows:
        tc_by.setdefault(r["stt"], []).append(r)

    sai_by = {}
    for r in sai:
        sai_by.setdefault(r["stt"], []).append(r)

    filled_blanks = 0
    detail_sheets = 0
    for ws in wb.worksheets:
        stt = sheet_stt(ws.title)
        if not stt or stt not in fs:
            continue
        if ws.title == "Tổng hợp":
            continue
        fs_row = fs[stt]
        g_url, g_src = pick_g(stt, fs_row, lc.get(stt))
        h = ket_qua_kiem_tra(stt, fs_row, sai_by.get(stt, []), g_url, uv)
        i = ghi_chu(stt, fs_row, ov.get(stt), g_src)
        filled_blanks += fill_blank_from_tra_cuu(ws, stt, tc_by.get(stt, []))
        append_detail_rows(ws, stt, fs_row, g_url, h, i)
        detail_sheets += 1

    n_sai = add_sai_lech_sheet(wb, sai)
    status_c, g_filled = add_thong_ke_sheet(wb, fs, lc, sai)

    wb.save(dest)
    wb.close()

    # Also sync final_status into repo data/
    dest_fs = DATA / "final_status.csv"
    shutil.copy2(FINAL_STATUS, dest_fs)

    return {
        "out": str(dest),
        "tong_hop_rows": n_th,
        "detail_sheets": detail_sheets,
        "filled_blanks": filled_blanks,
        "sai_lech_rows": n_sai,
        "status_counts": status_c,
        "g_filled": g_filled,
        "sheet_count": None,
    }


def main():
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    info = build(dest)
    # recount sheets
    wb = load_workbook(dest, read_only=True)
    info["sheet_count"] = len(wb.sheetnames)
    info["sheetnames_head"] = wb.sheetnames[:12]
    info["has_08"] = "08 Tân Cảng Quế Võ" in wb.sheetnames
    info["has_sai"] = "Kiểm tra sai lệch" in wb.sheetnames
    info["has_tk"] = "Thống kê" in wb.sheetnames
    wb.close()
    print(info)


if __name__ == "__main__":
    main()
