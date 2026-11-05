"""Phase 5–6 offline tests: build_excel + verify (no network)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "Thông tin ICD 34 tỉnh năm 2026.xlsx"
SCRIPTS = ROOT / "scripts"


@pytest.fixture(scope="module")
def built_workbook(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("phase56")
    dest = out_dir / "handover.xlsx"
    import sys
    sys.path.insert(0, str(SCRIPTS))
    import build_excel

    # Ensure final_status is available inside repo for build
    fs_src = Path("/workspace/icd_phase3_out/final_status.csv")
    fs_dst = ROOT / "data" / "final_status.csv"
    if fs_src.exists():
        shutil.copy2(fs_src, fs_dst)
    info = build_excel.build(dest)
    assert dest.exists()
    return dest, info


def test_build_creates_sheet_08_and_extras(built_workbook):
    dest, info = built_workbook
    assert dest.exists()
    from openpyxl import load_workbook

    wb = load_workbook(dest, read_only=True)
    names = wb.sheetnames
    assert "08 Tân Cảng Quế Võ" in names
    assert names.index("08 Tân Cảng Quế Võ") == names.index("07 Nam Đình Vũ giai đoạn 1") + 1
    assert "Kiểm tra sai lệch" in names
    assert "Thống kê" in names
    assert sum(1 for n in names if n[:1].isdigit() or (len(n) > 1 and n[:2].isdigit())) == 128
    wb.close()


def test_verify_pass(built_workbook):
    dest, _ = built_workbook
    import sys
    sys.path.insert(0, str(SCRIPTS))
    import verify

    rep = verify.verify(dest, SRC, online=False)
    assert rep["ok"] is True, rep["errors"]
    assert rep["stats"]["detail_sheets"] == 128
    assert rep["stats"]["tong_hop_f_filled"] == 128
    assert rep["stats"]["original_cells_changed"] == 0
    assert "online_refetch_skipped_by_design" in rep["checked_offline"]


def test_column_g_never_qd979(built_workbook):
    dest, _ = built_workbook
    from openpyxl import load_workbook

    wb = load_workbook(dest, read_only=True)
    tong = wb["Tổng hợp"]
    for row in tong.iter_rows(min_row=4, max_col=7, values_only=True):
        g = row[6]
        if g:
            assert "979-QD-TTg" not in str(g) and "979-qd-ttg" not in str(g).lower()
    wb.close()


def test_original_a_to_e_unchanged(built_workbook):
    dest, _ = built_workbook
    from openpyxl import load_workbook

    src = load_workbook(SRC, read_only=True, data_only=True)
    out = load_workbook(dest, read_only=True, data_only=True)
    s, o = src["Tổng hợp"], out["Tổng hợp"]
    for r in range(1, s.max_row + 1):
        for c in range(1, 6):
            assert s.cell(r, c).value == o.cell(r, c).value
    src.close()
    out.close()
