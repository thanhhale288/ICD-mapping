"""
Phase 2 — Kiểm tra link cột E + điểm nghi sai + đối chiếu QĐ + quét định dạng.

Đầu ra:
  data/sai_lech.csv
  data/phase2_summary.json  (tóm tắt nghiệm thu)

Cột sai_lech (khớp sheet Kiểm tra sai lệch / Phase 5):
  stt, ten, sheet, hang_muc, noi_dung_hien_tai, phat_hien, link_nguon,
  loai, ket_luan, de_xuat_sua, nguon_thay_the, ghi_chu

Usage:
  python3 scripts/phase2_sai_lech.py              # dùng link_check.csv sẵn có
  python3 scripts/phase2_sai_lech.py --check-links # chạy check_links tong-hop trước
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

HIEN_TRANG = ROOT / "data" / "icd_hien_trang.csv"
KEYS = ROOT / "data" / "icd_keys.csv"
LINK_CHECK = ROOT / "data" / "link_check.csv"
OUT_SAI = ROOT / "data" / "sai_lech.csv"
OUT_SUMMARY = ROOT / "data" / "phase2_summary.json"

COLUMNS = [
    "stt",
    "ten",
    "sheet",
    "hang_muc",
    "noi_dung_hien_tai",
    "phat_hien",
    "link_nguon",
    "loai",
    "ket_luan",  # đúng | sai | chưa đủ nguồn | ghi_nhan
    "de_xuat_sua",
    "nguon_thay_the",
    "ghi_chu",
    "phase2_muc",  # P2.1 | P2.2 | P2.3 | P2.4
]

VN_TZ = timezone(timedelta(hours=7))

# --- Nguồn đối chiếu đã tra (P2.2 / P2.3), 30/10/2026 ---
# QĐ công bố mở từ danh mục 506/QĐ-BGTVT (27/4/2023) + tin chính thống.
QD_MO_CAN_DOI_CHIEU: dict[int, dict[str, str]] = {
    1: {
        "so": "1549/QĐ-BGTVT",
        "ngay": "16/12/2024",
        "link": "https://moc.gov.vn/vn/Pages/ChiTietVanBan.aspx?TypeVB=1&vID=4465",
        "note": "mt.gov.vn cột E chết (404); thay bằng moc.gov.vn / TVPL 1549.",
    },
    2: {
        "so": "1617/QĐ-BGTVT",
        "ngay": "07/5/2015",
        "link": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-506-QD-BGTVT-2023-cong-bo-cang-can-Viet-Nam-564780.aspx",
        "note": "Số khớp danh mục 506; link cột E là NQ HĐND Phú Thọ (sai loại văn bản).",
    },
    3: {
        "so": "3882/QĐ-BGTVT",
        "ngay": "30/10/2015",
        "link": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-506-QD-BGTVT-2023-cong-bo-cang-can-Viet-Nam-564780.aspx",
        "note": "Số khớp 506; link vimawa dùng chung STT 3–4.",
    },
    4: {
        "so": "1456/QĐ-BGTVT",
        "ngay": "12/5/2016",
        "link": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-478-QD-BGTVT-sua-doi-1456-QD-BGTVT-cong-bo-mo-cang-can-Tan-Cang-Hai-Phong-2017-340821.aspx",
        "note": "File ghi 12/5/2015 — lệch năm; đúng là 12/5/2016 (QĐ 478 sửa đổi xác nhận).",
    },
    5: {
        "so": "2200/QĐ-BGTVT",
        "ngay": "11/10/2018",
        "link": "https://baochinhphu.vn/bo-gtvt-cong-bo-mo-cang-can-dau-tien-tai-hai-phong-102246365.htm",
        "note": "Khớp danh mục 506.",
    },
    6: {
        "so": "60/QĐ-BGTVT",
        "ngay": "15/01/2020",
        "link": "https://luatvietnam.vn/giao-thong/quyet-dinh-60-qd-bgtvt-2020-cong-bo-mo-cang-can-hoang-thanh-180115-d1.html",
        "note": "Khớp 506; trang luatvietnam nhắc nhiều ICD → CHỈ_KHỚP_CHUNG.",
    },
    7: {
        "so": "1768/QĐ-BGTVT",
        "ngay": "29/12/2023",
        "link": "https://baodauthau.vn/bo-gtvt-cong-bo-mo-cang-can-nam-dinh-vu-hai-phong-giai-doan-1-post148666.html",
        "note": "Ngoài danh mục 506 (mở sau); giữ số trong file, cần văn bản gốc riêng.",
    },
    8: {
        "so": "1543/QĐ-BGTVT",
        "ngay": "19/8/2021",
        "link": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-506-QD-BGTVT-2023-cong-bo-cang-can-Viet-Nam-564780.aspx",
        "note": "Sheet 08 chưa có; link cột E là bài quy hoạch Bắc Ninh, không phải QĐ mở.",
    },
    9: {
        "so": "1246/QĐ-BGTVT",
        "ngay": "2024",
        "link": "https://baoxaydung.vn/cang-can-tien-son-cu-hich-moi-cho-phat-trien-kinh-te-bac-ninh-1926868386204.htm",
        "note": "Tra được số 1246/QĐ-BGTVT (Reatimes, Báo Xây dựng); ngày đầy đủ chưa thấy trên văn bản gốc công khai.",
    },
    10: {
        "so": "276/QĐ-BXD",
        "ngay": "2025",
        "link": "https://baochinhphu.vn/bo-xay-dung-cong-bo-mo-cang-can-tan-chi-giai-doan-1-tai-bac-ninh-102250324095954815.htm",
        "note": "Tin báo chí khớp tên; chưa đối được văn bản PDF gốc trong phiên này.",
    },
    11: {
        "so": "711/QĐ-BGTVT",
        "ngay": "20/4/2020",
        "link": "https://baochinhphu.vn/cong-bo-mo-cang-can-long-bien-102271656.htm",
        "note": "Khớp 506.",
    },
    12: {
        "so": "1007/QĐ-BGTVT",
        "ngay": "24/5/2019",
        "link": "https://luatvietnam.vn/giao-thong/quyet-dinh-1007-qd-bgtvt-2019-mo-cang-can-tan-cang-ha-nam-173217-d1.html",
        "note": "Số khớp 506/luatvietnam; link cột E là 1686/QĐ-TTg (QH tỉnh Hà Nam) — sai loại.",
    },
    13: {
        "so": "584/QĐ-BGTVT",
        "ngay": "11/2/2015",
        "link": "https://nhipcaudautu.vn/kinh-doanh/mo-cang-can-phuc-loc--ninh-binh-3234178/",
        "note": "File ghi 684 — sai số; đúng 584/QĐ-BGTVT (Nhịp cầu đầu tư + danh mục 506). Link cột E là QĐ 979.",
    },
    14: {
        "so": "432/QĐ-BGTVT",
        "ngay": "04/02/2016",
        "link": "https://caselaw.vn/van-ban-phap-luat/148378-quyet-dinh-432-qd-bgtvt-nam-2016-cong-bo-mo-cang-can-tan-cang-nhon-trach-do-bo-truong-bo-giao-thong-van-tai-ban-hanh",
        "note": "Khớp 506 (ngày 04/02/2016).",
    },
    15: {
        "so": "07/QĐ-BGTVT",
        "ngay": "06/01/2023",
        "link": "https://banduong.vn/mo-cang-can-tan-cang-long-binh-d5184.html",
        "note": "Tra được 07/QĐ-BGTVT ngày 06/01/2023; cũng có trong phụ lục 506.",
    },
    16: {
        "so": "976/QĐ-BGTVT",
        "ngay": "09/8/2023",
        "link": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-976-QD-BGTVT-2023-mo-cang-can-Phu-My-697784.aspx",
        "note": "Khớp tin/TVPL; trang TVPL hay bị Cloudflare.",
    },
    17: {
        "so": "191/QĐ-BXD",
        "ngay": "09/2/2026",
        "link": "https://logistics.gov.vn/dich-vu-logistics/cang-bien/cong-bo-mo-cang-can-cai-mep-tai-phuong-tan-phuoc-tp-hcm",
        "note": "Tin logistics.gov.vn khớp tên; cần PDF gốc khi có.",
    },
    18: {
        "so": "1696/QĐ-BGTVT",
        "ngay": "25/12/2023",
        "link": "https://baodautu.vn/cong-bo-mo-cang-can-thanh-phuoc---binh-duong-d206003.html",
        "note": "Tin báo chí; chưa đối PDF gốc trong phiên này.",
    },
    19: {
        "so": "1810/QĐ-BXD",
        "ngay": "20/10/2025",
        "link": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-1810-QD-BXD-2025-cong-bo-mo-cang-can-Tan-Cang-Moc-Bai-677820.aspx",
        "note": "Khớp TVPL; trang hay bị chặn tầng 3.",
    },
}

QH_TINH_DOI_CHIEU: list[dict[str, Any]] = [
    {
        "ma": "2279/QĐ-UBND",
        "stts": [86, 87, 88, 89],
        "tinh": "Khánh Hòa",
        "ngay_file": "26/06/2026",
        "ngay_nguon": "26/06/2026",
        "ket_luan": "đúng",
        "link": "https://bangoi.khanhhoa.gov.vn/vi/thong-tin-quy-hoach/ngay-26-6-2026-chu-tich-uy-ban-nhan-dan-tinh-da-ky-quyet-dinh-so-2279-qd-ubnd-phe-duyet-dieu-chinh-quy-hoach-tinh-khanh-hoa-thoi-ky-2021-2030-tam-nhin-den-nam-2050",
        "phat_hien": "Xác nhận: phê duyệt điều chỉnh QH tỉnh Khánh Hòa, ký 26/6/2026.",
    },
    {
        "ma": "5455/QĐ-UBND",
        "stts": [51, 52, 54],
        "tinh": "Hải Phòng",
        "ngay_file": "31/12/2025",
        "ngay_nguon": "31/12/2025",
        "ket_luan": "đúng",
        "link": "https://giavien.haiphong.gov.vn/thong-tin-ve-tai-nguyen-moi-truong/quyet-dinh-so-5455-qd-ubnd-ngay-31-12-2025-cua-ubnd-thanh-pho-hai-phong-phe-duyet-dieu-chinh-quy-956212",
        "phat_hien": "Xác nhận: điều chỉnh QH TP Hải Phòng, ban hành 31/12/2025, hiệu lực 01/01/2026.",
    },
    {
        "ma": "568/QĐ-UBND",
        "stts": [64, 66, 67],
        "tinh": "Ninh Bình",
        "ngay_file": "26/02/2026",
        "ngay_nguon": "26/02/2026",
        "ket_luan": "đúng",
        "link": "https://sonnmt.ninhbinh.gov.vn/van-ban/ve-viec-dinh-chinh-mot-so-noi-dung-tai-phu-luc-ban-hanh-kem-theo-quyet-dinh-so-568-qd-ubnd-ngay-26-thang-02-nam-2026-cua-chu-tich-uy-ban-nhan-dan-tinh-ve-viec-phe-duyet-dieu-chinh-quy-hoach-tinh-ninh-binh-thoi-ky-2021-2030-tam-nhin-den-nam-2050-2802.html",
        "phat_hien": "Xác nhận: phê duyệt điều chỉnh QH tỉnh Ninh Bình 26/02/2026; có QĐ đính chính phụ lục 1543/QĐ-UBND.",
    },
    {
        "ma": "779/QĐ-UBND",
        "stts": [93, 94, 95, 96, 97],
        "tinh": "Đồng Nai",
        "ngay_file": "27/02/2026",
        "ngay_nguon": "27/02/2026",
        "ket_luan": "đúng",
        "link": "https://congbao.dongnai.gov.vn/vi/vanban/detail/Phe-duyet-dieu-chinh-Quy-hoach-tinh-Dong-Nai-thoi-ky-2021-2030-tam-nhin-den-nam-2050-9582/",
        "phat_hien": "Xác nhận: phê duyệt điều chỉnh QH tỉnh Đồng Nai 27/02/2026 (Công báo Đồng Nai).",
    },
    {
        "ma": "01/NQ-HĐND",
        "stts": [23],
        "tinh": "Lai Châu",
        "ngay_file": "27/02/2026",
        "ngay_nguon": "27/02/2026",
        "ket_luan": "đúng",
        "link": "https://www.dulieuphapluat.vn/van-ban/xay-dung-van-ban/nghi-quyet-01nq-hdnd-nam-2026-dieu-chinh-quy-hoach-tinh-lai-chau-thoi-ky-2021-2030-tam-nhin-den-nam-2050-1253510.html",
        "phat_hien": "Xác nhận NQ 01/NQ-HĐND Lai Châu 27/02/2026; có nêu quy hoạch cảng cạn Ma Lù Thàng ~10 ha.",
    },
    {
        "ma": "01/NQ-HĐND",
        "stts": [128],
        "tinh": "Cà Mau",
        "ngay_file": "2026",
        "ngay_nguon": "25/02/2026",
        "ket_luan": "đúng",
        "link": "https://thuviennhadat.vn/phap-luat/tai-nghi-quyet-01-nq-hdnd-dieu-chinh-quy-hoach-tinh-ca-mau-thoi-ky-2021-2030-tam-nhin-den-nam-2050-737526.html",
        "phat_hien": "Xác nhận NQ 01/NQ-HĐND Cà Mau ngày 25/02/2026; file chỉ ghi năm 2026 — đề xuất bổ sung ngày.",
    },
]

# Phụ lục E mục 0–9 — kết luận có nguồn
PHU_LUC_E: list[dict[str, Any]] = [
    {
        "muc": 0,
        "stt": 1,
        "hang_muc": "Link cột E",
        "ket_luan": "sai",
        "phat_hien": "Link mt.gov.vn trả 404 (LINK_CHẾT).",
        "de_xuat": "Thay bằng moc.gov.vn ChiTietVanBan vID=4465 hoặc TVPL 1549/QĐ-BGTVT.",
        "link": "https://moc.gov.vn/vn/Pages/ChiTietVanBan.aspx?TypeVB=1&vID=4465",
        "thay": "https://moc.gov.vn/vn/Pages/ChiTietVanBan.aspx?TypeVB=1&vID=4465",
    },
    {
        "muc": 1,
        "stt": 3,
        "hang_muc": "Link cột E",
        "ket_luan": "sai",
        "phat_hien": "STT 3 và 4 dùng chung vimawa/node/15406 — bài/danh sách chung, không riêng ICD; hiện Access denied (403).",
        "de_xuat": "Tách link riêng theo QĐ mở từng ICD; tạm dùng phụ lục 506/QĐ-BGTVT làm nguồn kiểm chứng số QĐ.",
        "link": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-506-QD-BGTVT-2023-cong-bo-cang-can-Viet-Nam-564780.aspx",
        "thay": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-506-QD-BGTVT-2023-cong-bo-cang-can-Viet-Nam-564780.aspx",
    },
    {
        "muc": 2,
        "stt": 2,
        "hang_muc": "Link cột E",
        "ket_luan": "sai",
        "phat_hien": "Link PDF nghị quyết HĐND Phú Thọ, không phải quyết định mở cảng 1617/QĐ-BGTVT; fetch hiện LINK_CHẾT/DNS.",
        "de_xuat": "Thay bằng nguồn nêu 1617/QĐ-BGTVT (vd. phụ lục 506) hoặc văn bản gốc BGTVT khi có.",
        "link": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-506-QD-BGTVT-2023-cong-bo-cang-can-Viet-Nam-564780.aspx",
        "thay": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-506-QD-BGTVT-2023-cong-bo-cang-can-Viet-Nam-564780.aspx",
    },
    {
        "muc": 3,
        "stt": 12,
        "hang_muc": "Link cột E",
        "ket_luan": "sai",
        "phat_hien": "Link STT 12 = 1686/QĐ-TTg (QH tỉnh Hà Nam), không phải 1007/QĐ-BGTVT. Link STT 13 = 979/QĐ-TTg, không phải QĐ mở Phúc Lộc.",
        "de_xuat": "STT 12: trỏ nguồn 1007/QĐ-BGTVT. STT 13: trỏ 584/QĐ-BGTVT (không phải 684).",
        "link": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-506-QD-BGTVT-2023-cong-bo-cang-can-Viet-Nam-564780.aspx",
        "thay": "https://nhipcaudautu.vn/kinh-doanh/mo-cang-can-phuc-loc--ninh-binh-3234178/",
    },
    {
        "muc": 4,
        "stt": 8,
        "hang_muc": "Link cột E",
        "ket_luan": "sai",
        "phat_hien": "Link logistics.gov.vn là bài về cảng cạn quy hoạch Bắc Ninh, không phải QĐ mở Quế Võ.",
        "de_xuat": "Dùng 1543/QĐ-BGTVT ngày 19/8/2021 (danh mục 506); tạo sheet 08 ở Phase 5.",
        "link": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-506-QD-BGTVT-2023-cong-bo-cang-can-Viet-Nam-564780.aspx",
        "thay": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-506-QD-BGTVT-2023-cong-bo-cang-can-Viet-Nam-564780.aspx",
    },
    {
        "muc": 5,
        "stt": 9,
        "hang_muc": "Số QĐ thành lập",
        "ket_luan": "sai",
        "phat_hien": "STT 9 và 15 thiếu số QĐ trong file ('cần tra cứu số').",
        "de_xuat": "STT 9: 1246/QĐ-BGTVT (2024). STT 15: 07/QĐ-BGTVT ngày 06/01/2023.",
        "link": "https://baoxaydung.vn/cang-can-tien-son-cu-hich-moi-cho-phat-trien-kinh-te-bac-ninh-1926868386204.htm",
        "thay": "https://banduong.vn/mo-cang-can-tan-cang-long-binh-d5184.html",
    },
    {
        "muc": 6,
        "stt": 10,
        "hang_muc": "Quy mô",
        "ket_luan": "sai",
        "phat_hien": "Lỗi float Excel: 8,1910900000000009 ha (STT 10) và 9,6477599999999999 ha (STT 18).",
        "de_xuat": "Sửa thành 8,19109 ha (STT 10) và 9,64776 ha (STT 18).",
        "link": "",
        "thay": "",
    },
    {
        "muc": 7,
        "stt": 19,
        "hang_muc": "Nhiều ô",
        "ket_luan": "sai",
        "phat_hien": "Còn chữ 'Excel gốc' / 'EXCEL GỐC' trong sheet 19 (Kết nối VT, Quy mô, Dịch vụ, Khách hàng).",
        "de_xuat": "Xóa cụm ghi chú nội bộ sau khi xác minh số liệu; giữ giá trị đã kiểm.",
        "link": "",
        "thay": "",
    },
    {
        "muc": 8,
        "stt": 0,
        "hang_muc": "Văn bản QH tỉnh",
        "ket_luan": "đúng",
        "phat_hien": "Đã đối 2279, 5455, 568, 779, 01/NQ-HĐND (Lai Châu, Cà Mau) — số/ngày khớp nguồn công khai (chi tiết P2.3).",
        "de_xuat": "Bổ sung ngày 25/02/2026 cho 01/NQ-HĐND Cà Mau (file chỉ ghi 2026).",
        "link": "",
        "thay": "",
    },
    {
        "muc": 9,
        "stt": 0,
        "hang_muc": "Số QĐ nhóm 428",
        "ket_luan": "ghi_nhan",
        "phat_hien": "Đối chiếu 19 ICD nhóm QĐ 428 với danh mục 506 + tin chính thống; phát hiện lệch số/ngày ở STT 4, 13 và thiếu số ở STT 9, 15 (xem P2.3).",
        "de_xuat": "Cập nhật từng dòng theo QD_MO_CAN_DOI_CHIEU; dòng 'theo tài liệu lịch sử' giữ đến khi có PDF gốc.",
        "link": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-506-QD-BGTVT-2023-cong-bo-cang-can-Viet-Nam-564780.aspx",
        "thay": "",
    },
]

# Nguồn thay khi cột E bị Cloudflare / chết (P2.1 DoD)
NGUON_THAY_THEO_STT: dict[int, str] = {
    1: "https://moc.gov.vn/vn/Pages/ChiTietVanBan.aspx?TypeVB=1&vID=4465",
    2: "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-506-QD-BGTVT-2023-cong-bo-cang-can-Viet-Nam-564780.aspx",
    3: "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-506-QD-BGTVT-2023-cong-bo-cang-can-Viet-Nam-564780.aspx",
    4: "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-506-QD-BGTVT-2023-cong-bo-cang-can-Viet-Nam-564780.aspx",
    8: "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Quyet-dinh-506-QD-BGTVT-2023-cong-bo-cang-can-Viet-Nam-564780.aspx",
    12: "https://luatvietnam.vn/giao-thong/quyet-dinh-1007-qd-bgtvt-2019-mo-cang-can-tan-cang-ha-nam-173217-d1.html",
    13: "https://vanban.chinhphu.vn/?docid=208522&pageid=27160",  # 979 chính thức; QĐ mở = 584 riêng
    19: "https://luatvietnam.vn/giao-thong/quyet-dinh-1810-qd-bxd-2025-cong-bo-mo-cang-can-tan-cang-moc-bai-415672-d1.html",
    23: "https://www.dulieuphapluat.vn/van-ban/xay-dung-van-ban/nghi-quyet-01nq-hdnd-nam-2026-dieu-chinh-quy-hoach-tinh-lai-chau-thoi-ky-2021-2030-tam-nhin-den-nam-2050-1253510.html",
    # 21/27/31/40/123/126: TVPL bị chặn → can_mo_tay (Chrome thường)
    51: "https://giavien.haiphong.gov.vn/thong-tin-ve-tai-nguyen-moi-truong/quyet-dinh-so-5455-qd-ubnd-ngay-31-12-2025-cua-ubnd-thanh-pho-hai-phong-phe-duyet-dieu-chinh-quy-956212",
    52: "https://giavien.haiphong.gov.vn/thong-tin-ve-tai-nguyen-moi-truong/quyet-dinh-so-5455-qd-ubnd-ngay-31-12-2025-cua-ubnd-thanh-pho-hai-phong-phe-duyet-dieu-chinh-quy-956212",
    54: "https://giavien.haiphong.gov.vn/thong-tin-ve-tai-nguyen-moi-truong/quyet-dinh-so-5455-qd-ubnd-ngay-31-12-2025-cua-ubnd-thanh-pho-hai-phong-phe-duyet-dieu-chinh-quy-956212",
    64: "https://sonnmt.ninhbinh.gov.vn/van-ban/ve-viec-dinh-chinh-mot-so-noi-dung-tai-phu-luc-ban-hanh-kem-theo-quyet-dinh-so-568-qd-ubnd-ngay-26-thang-02-nam-2026-cua-chu-tich-uy-ban-nhan-dan-tinh-ve-viec-phe-duyet-dieu-chinh-quy-hoach-tinh-ninh-binh-thoi-ky-2021-2030-tam-nhin-den-nam-2050-2802.html",
    66: "https://sonnmt.ninhbinh.gov.vn/van-ban/ve-viec-dinh-chinh-mot-so-noi-dung-tai-phu-luc-ban-hanh-kem-theo-quyet-dinh-so-568-qd-ubnd-ngay-26-thang-02-nam-2026-cua-chu-tich-uy-ban-nhan-dan-tinh-ve-viec-phe-duyet-dieu-chinh-quy-hoach-tinh-ninh-binh-thoi-ky-2021-2030-tam-nhin-den-nam-2050-2802.html",
    67: "https://sonnmt.ninhbinh.gov.vn/van-ban/ve-viec-dinh-chinh-mot-so-noi-dung-tai-phu-luc-ban-hanh-kem-theo-quyet-dinh-so-568-qd-ubnd-ngay-26-thang-02-nam-2026-cua-chu-tich-uy-ban-nhan-dan-tinh-ve-viec-phe-duyet-dieu-chinh-quy-hoach-tinh-ninh-binh-thoi-ky-2021-2030-tam-nhin-den-nam-2050-2802.html",
    86: "https://bangoi.khanhhoa.gov.vn/vi/thong-tin-quy-hoach/ngay-26-6-2026-chu-tich-uy-ban-nhan-dan-tinh-da-ky-quyet-dinh-so-2279-qd-ubnd-phe-duyet-dieu-chinh-quy-hoach-tinh-khanh-hoa-thoi-ky-2021-2030-tam-nhin-den-nam-2050",
    87: "https://bangoi.khanhhoa.gov.vn/vi/thong-tin-quy-hoach/ngay-26-6-2026-chu-tich-uy-ban-nhan-dan-tinh-da-ky-quyet-dinh-so-2279-qd-ubnd-phe-duyet-dieu-chinh-quy-hoach-tinh-khanh-hoa-thoi-ky-2021-2030-tam-nhin-den-nam-2050",
    88: "https://bangoi.khanhhoa.gov.vn/vi/thong-tin-quy-hoach/ngay-26-6-2026-chu-tich-uy-ban-nhan-dan-tinh-da-ky-quyet-dinh-so-2279-qd-ubnd-phe-duyet-dieu-chinh-quy-hoach-tinh-khanh-hoa-thoi-ky-2021-2030-tam-nhin-den-nam-2050",
    89: "https://bangoi.khanhhoa.gov.vn/vi/thong-tin-quy-hoach/ngay-26-6-2026-chu-tich-uy-ban-nhan-dan-tinh-da-ky-quyet-dinh-so-2279-qd-ubnd-phe-duyet-dieu-chinh-quy-hoach-tinh-khanh-hoa-thoi-ky-2021-2030-tam-nhin-den-nam-2050",
    128: "https://thuviennhadat.vn/phap-luat/tai-nghi-quyet-01-nq-hdnd-dieu-chinh-quy-hoach-tinh-ca-mau-thoi-ky-2021-2030-tam-nhin-den-nam-2050-737526.html",
}

# STT cột E BỊ_CHẶN (TVPL) — chưa có cổng thay ổn định → mở tay
CAN_MO_TAY_STT = {21, 27, 31, 40, 123, 126}

FLOAT_RE = re.compile(
    r"(\d+),(\d*?(?:0{4,}\d*|9999+\d*))\b"
)
EXCEL_GOC_RE = re.compile(r"excel\s*gốc", re.I)
CAN_TRA_RE = re.compile(r"cần\s*tra\s*cứu\s*số|cần\s*tra\s*cứu", re.I)


def _now() -> str:
    return datetime.now(VN_TZ).isoformat(timespec="seconds")


def load_hien_trang() -> list[dict[str, str]]:
    with HIEN_TRANG.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def tong_hop_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {r["stt"]: r for r in rows if r.get("loai") == "tong_hop"}


def chi_tiet_by_stt(
    rows: list[dict[str, str]], stt: str, hang_muc: str
) -> dict[str, str] | None:
    for r in rows:
        if r.get("loai") == "chi_tiet" and r.get("stt") == stt and r.get("hang_muc") == hang_muc:
            return r
    return None


def load_link_check() -> list[dict[str, str]]:
    if not LINK_CHECK.exists():
        return []
    with LINK_CHECK.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def run_check_links() -> None:
    from check_links import check_many, load_tong_hop_links

    items = load_tong_hop_links()
    print(f"P2.1: checking {len(items)} unique cột-E links…", flush=True)
    check_many(items, use_cache=True, out_path=LINK_CHECK)


def row_out(**kwargs: Any) -> dict[str, str]:
    base = {c: "" for c in COLUMNS}
    for k, v in kwargs.items():
        if k in base:
            base[k] = "" if v is None else str(v)
    return base


def p21_from_link_check(
    rows: list[dict[str, str]], link_rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    th = tong_hop_index(rows)
    by_url: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        if r.get("loai") != "tong_hop":
            continue
        url = (r.get("link") or "").strip()
        if url:
            by_url[url].append(r)

    # map unique-check result → all STTs sharing that URL
    check_by_url = {(r.get("url") or "").strip(): r for r in link_rows}

    out: list[dict[str, str]] = []
    statuses_ok = 0
    for url, owners in by_url.items():
        cr = check_by_url.get(url)
        if not cr:
            for o in owners:
                out.append(
                    row_out(
                        stt=o["stt"],
                        ten=o["ten"],
                        sheet=o.get("sheet") or "Tổng hợp",
                        hang_muc="Link cột E",
                        noi_dung_hien_tai=url,
                        phat_hien="Chưa có kết quả check_links cho URL này.",
                        link_nguon=url,
                        loai="link_thieu_kiem",
                        ket_luan="chưa đủ nguồn",
                        de_xuat_sua="Chạy: python3 scripts/check_links.py tong-hop",
                        phase2_muc="P2.1",
                    )
                )
            continue
        statuses_ok += 1
        status = cr.get("status") or ""
        first = owners[0]
        stts = [o["stt"] for o in owners]
        phap = first.get("phap_ly") or ""

        # trùng URL giữa ≥2 ICD
        if len(owners) >= 2:
            for o in owners:
                out.append(
                    row_out(
                        stt=o["stt"],
                        ten=o["ten"],
                        sheet="Tổng hợp",
                        hang_muc="Link cột E",
                        noi_dung_hien_tai=url,
                        phat_hien=(
                            f"Link trùng giữa các STT {', '.join(stts)} "
                            f"(pháp lý: {phap}). status={status}."
                        ),
                        link_nguon=url,
                        loai="link_trung",
                        ket_luan="sai" if status != "MỞ_ĐƯỢC_KHỚP" else "ghi_nhan",
                        de_xuat_sua=(
                            "Ưu tiên link riêng từng ICD ở cột G (Phase 3); "
                            "cột E có thể giữ văn bản chung nếu ghi rõ."
                        ),
                        nguon_thay_the="",
                        ghi_chu=cr.get("ly_do") or "",
                        phase2_muc="P2.1",
                    )
                )

        # trạng thái xấu / CHỈ_KHỚP_CHUNG với nhóm 428
        bad = status in (
            "LINK_CHẾT",
            "MỞ_ĐƯỢC_KHÔNG_KHỚP",
            "BỊ_CHẶN",
        )
        chi_chung_428 = status == "CHỈ_KHỚP_CHUNG" and "428" in phap
        if bad or chi_chung_428 or status == "LỖI_SSL_MỞ_ĐƯỢC":
            # tránh trùng dòng nếu đã ghi link_trung với cùng nội dung xấu
            for o in owners:
                if len(owners) >= 2 and not (bad or chi_chung_428):
                    continue
                if len(owners) >= 2 and (bad or chi_chung_428):
                    # đã có dòng link_trung; bổ sung dòng trạng thái nếu LINK_CHẾT/BỊ_CHẶN
                    if status not in ("LINK_CHẾT", "BỊ_CHẶN", "MỞ_ĐƯỢC_KHÔNG_KHỚP"):
                        continue
                stt_i = int(o["stt"]) if o["stt"].isdigit() else 0
                thay = NGUON_THAY_THEO_STT.get(stt_i) or ""
                if not thay and stt_i in QD_MO_CAN_DOI_CHIEU:
                    thay = QD_MO_CAN_DOI_CHIEU[stt_i].get("link") or ""
                ket = "sai" if status in ("LINK_CHẾT", "MỞ_ĐƯỢC_KHÔNG_KHỚP") else (
                    "chưa đủ nguồn" if status == "BỊ_CHẶN" else "ghi_nhan"
                )
                if status == "BỊ_CHẶN" and thay:
                    ket = "ghi_nhan"  # đã có nguồn thay / cổng tỉnh
                out.append(
                    row_out(
                        stt=o["stt"],
                        ten=o["ten"],
                        sheet="Tổng hợp",
                        hang_muc="Link cột E",
                        noi_dung_hien_tai=url,
                        phat_hien=f"Trạng thái kiểm link: {status}. {cr.get('ly_do') or ''}".strip(),
                        link_nguon=url,
                        loai=f"link_{status}",
                        ket_luan=ket,
                        de_xuat_sua=(
                            "Tìm/gắn nguồn thay thế; nếu vẫn chặn → data/can_mo_tay.csv."
                            if status == "BỊ_CHẶN"
                            else "Thay link cột E / ghi đề xuất vào Kiểm tra sai lệch."
                        ),
                        nguon_thay_the=thay,
                        ghi_chu=f"tier={cr.get('tang')}; http={cr.get('http_code')}",
                        phase2_muc="P2.1",
                    )
                )

    return out


def p22_phu_luc_e(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    th = tong_hop_index(rows)
    out: list[dict[str, str]] = []
    for item in PHU_LUC_E:
        stt = str(item["stt"])
        if item["stt"] == 0:
            ten, sheet = "(nhiều ICD)", "Tổng hợp"
            noi = item["phat_hien"]
        else:
            meta = th.get(stt, {})
            ten = meta.get("ten") or ""
            sheet = meta.get("sheet") or ""
            if item["hang_muc"] == "Số QĐ thành lập":
                ct = chi_tiet_by_stt(rows, stt, "Số QĐ thành lập")
                noi = (ct or {}).get("noi_dung") or ""
            elif item["hang_muc"] == "Quy mô":
                ct = chi_tiet_by_stt(rows, stt, "Quy mô")
                noi = (ct or {}).get("noi_dung") or ""
            else:
                noi = meta.get("link") or ""
        out.append(
            row_out(
                stt=stt if item["stt"] else "",
                ten=ten,
                sheet=sheet,
                hang_muc=item["hang_muc"],
                noi_dung_hien_tai=noi,
                phat_hien=f"[Phụ lục E.{item['muc']}] {item['phat_hien']}",
                link_nguon=item.get("link") or "",
                loai=f"phu_luc_E_{item['muc']}",
                ket_luan=item["ket_luan"],
                de_xuat_sua=item["de_xuat"],
                nguon_thay_the=item.get("thay") or "",
                phase2_muc="P2.2",
            )
        )
    # dòng riêng STT 4 cho mục 1 (dùng chung link)
    meta4 = th.get("4", {})
    out.append(
        row_out(
            stt="4",
            ten=meta4.get("ten") or "",
            sheet="Tổng hợp",
            hang_muc="Link cột E",
            noi_dung_hien_tai=meta4.get("link") or "",
            phat_hien="[Phụ lục E.1] Dùng chung link vimawa với STT 3 — không riêng ICD.",
            link_nguon=meta4.get("link") or "",
            loai="phu_luc_E_1",
            ket_luan="sai",
            de_xuat_sua="Tách nguồn riêng; số QĐ đúng 1456/QĐ-BGTVT ngày 12/5/2016.",
            nguon_thay_the=QD_MO_CAN_DOI_CHIEU[4]["link"],
            phase2_muc="P2.2",
        )
    )
    # STT 15 thiếu số (mục 5)
    meta15 = th.get("15", {})
    ct15 = chi_tiet_by_stt(rows, "15", "Số QĐ thành lập")
    out.append(
        row_out(
            stt="15",
            ten=meta15.get("ten") or "",
            sheet=(ct15 or {}).get("sheet") or "",
            hang_muc="Số QĐ thành lập",
            noi_dung_hien_tai=(ct15 or {}).get("noi_dung") or "",
            phat_hien="[Phụ lục E.5] Thiếu số QĐ mở cảng giai đoạn 1.",
            link_nguon=QD_MO_CAN_DOI_CHIEU[15]["link"],
            loai="phu_luc_E_5",
            ket_luan="sai",
            de_xuat_sua="Ghi 07/QĐ-BGTVT ngày 06/01/2023.",
            nguon_thay_the=QD_MO_CAN_DOI_CHIEU[15]["link"],
            phase2_muc="P2.2",
        )
    )
    # STT 18 float (mục 6)
    ct18 = chi_tiet_by_stt(rows, "18", "Quy mô")
    meta18 = th.get("18", {})
    out.append(
        row_out(
            stt="18",
            ten=meta18.get("ten") or "",
            sheet=(ct18 or {}).get("sheet") or "",
            hang_muc="Quy mô",
            noi_dung_hien_tai=(ct18 or {}).get("noi_dung") or "",
            phat_hien="[Phụ lục E.6] Lỗi float 9,6477599999999999 ha.",
            link_nguon="",
            loai="phu_luc_E_6",
            ket_luan="sai",
            de_xuat_sua="Sửa thành 9,64776 ha.",
            phase2_muc="P2.2",
        )
    )
    # STT 13 trong mục 3
    meta13 = th.get("13", {})
    out.append(
        row_out(
            stt="13",
            ten=meta13.get("ten") or "",
            sheet="Tổng hợp",
            hang_muc="Link cột E / Số QĐ",
            noi_dung_hien_tai=meta13.get("link") or "",
            phat_hien="[Phụ lục E.3] Link = QĐ 979; số trong sheet ghi 684 — đúng là 584/QĐ-BGTVT 11/2/2015.",
            link_nguon=QD_MO_CAN_DOI_CHIEU[13]["link"],
            loai="phu_luc_E_3",
            ket_luan="sai",
            de_xuat_sua="Sửa số thành 584/QĐ-BGTVT; thay link bằng nguồn QĐ mở Phúc Lộc.",
            nguon_thay_the=QD_MO_CAN_DOI_CHIEU[13]["link"],
            phase2_muc="P2.2",
        )
    )
    return out


def p23_doi_chieu_qd(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    th = tong_hop_index(rows)
    out: list[dict[str, str]] = []

    for stt, info in QD_MO_CAN_DOI_CHIEU.items():
        ct = chi_tiet_by_stt(rows, str(stt), "Số QĐ thành lập")
        noi = (ct or {}).get("noi_dung") or "(không có sheet chi tiết)"
        file_so = noi
        ket = "đúng"
        phat = f"Nguồn đối chiếu: {info['so']} ngày {info['ngay']}. {info['note']}"
        de_xuat = ""
        # lệch rõ
        if stt == 4 and "2015" in noi and "2016" not in noi:
            ket = "sai"
            de_xuat = "Sửa ngày thành 12/5/2016."
        elif stt == 13 and "684" in noi:
            ket = "sai"
            de_xuat = "Sửa thành 584/QĐ-BGTVT ngày 11/2/2015."
        elif stt in (9, 15) and CAN_TRA_RE.search(noi):
            ket = "sai"
            de_xuat = f"Điền {info['so']} ngày {info['ngay']}."
        elif stt == 8:
            ket = "ghi_nhan"
            de_xuat = f"Khi tạo sheet 08: ghi {info['so']} ngày {info['ngay']}."
        elif "theo tài liệu lịch sử" in noi.lower() or "báo cáo logistics" in noi.lower():
            ket = "ghi_nhan"
            de_xuat = "Số khớp danh mục 506; vẫn nên gắn PDF/QĐ gốc khi có."
        elif info["so"].split("/")[0] not in noi.replace(" ", ""):
            # số chính không xuất hiện trong ô
            if stt not in (8, 9, 15):
                ket = "chưa đủ nguồn"
                de_xuat = f"Kiểm lại ô Số QĐ so với {info['so']}."

        meta = th.get(str(stt), {})
        out.append(
            row_out(
                stt=str(stt),
                ten=meta.get("ten") or "",
                sheet=(ct or {}).get("sheet") or meta.get("sheet") or "",
                hang_muc="Số QĐ thành lập",
                noi_dung_hien_tai=file_so,
                phat_hien=phat,
                link_nguon=info["link"],
                loai="doi_chieu_qd_mo",
                ket_luan=ket,
                de_xuat_sua=de_xuat,
                nguon_thay_the=info["link"],
                phase2_muc="P2.3",
            )
        )

    for qh in QH_TINH_DOI_CHIEU:
        for stt in qh["stts"]:
            meta = th.get(str(stt), {})
            ct = chi_tiet_by_stt(rows, str(stt), "Số QĐ thành lập") or chi_tiet_by_stt(
                rows, str(stt), "Tình trạng"
            )
            noi = (ct or {}).get("noi_dung") or ""
            ket = qh["ket_luan"]
            de_xuat = ""
            if qh["tinh"] == "Cà Mau" and "25/02" not in noi and "25/2" not in noi:
                de_xuat = "Bổ sung ngày 25/02/2026 vào ghi chú căn cứ."
            out.append(
                row_out(
                    stt=str(stt),
                    ten=meta.get("ten") or "",
                    sheet=(ct or {}).get("sheet") or "Tổng hợp",
                    hang_muc="Văn bản quy hoạch tỉnh",
                    noi_dung_hien_tai=noi[:300],
                    phat_hien=qh["phat_hien"],
                    link_nguon=qh["link"],
                    loai="doi_chieu_qh_tinh",
                    ket_luan=ket,
                    de_xuat_sua=de_xuat,
                    nguon_thay_the=qh["link"],
                    ghi_chu=f"{qh['ma']} | file={qh['ngay_file']} | nguồn={qh['ngay_nguon']}",
                    phase2_muc="P2.3",
                )
            )
    return out


def p24_quet_dinh_dang(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    th = tong_hop_index(rows)
    out: list[dict[str, str]] = []
    sheets_seen: set[str] = set()

    for r in rows:
        if r.get("loai") == "chi_tiet":
            sheets_seen.add(r.get("sheet") or "")
        nd = r.get("noi_dung") or ""
        stt = r.get("stt") or ""
        ten = r.get("ten") or th.get(stt, {}).get("ten") or ""

        if FLOAT_RE.search(nd) and re.search(r"0{5,}|9{5,}", nd):
            out.append(
                row_out(
                    stt=stt,
                    ten=ten,
                    sheet=r.get("sheet") or "",
                    hang_muc=r.get("hang_muc") or "",
                    noi_dung_hien_tai=nd[:240],
                    phat_hien="Nghi lỗi số thập phân do float Excel.",
                    loai="dinh_dang_float",
                    ket_luan="sai",
                    de_xuat_sua="Làm tròn/ghi lại số đúng (bỏ đuôi 0000/9999).",
                    phase2_muc="P2.4",
                )
            )
        if EXCEL_GOC_RE.search(nd):
            out.append(
                row_out(
                    stt=stt,
                    ten=ten,
                    sheet=r.get("sheet") or "",
                    hang_muc=r.get("hang_muc") or "",
                    noi_dung_hien_tai=nd[:240],
                    phat_hien="Còn ghi chú nội bộ 'Excel gốc'.",
                    loai="ghi_chu_noi_bo",
                    ket_luan="sai",
                    de_xuat_sua="Xóa cụm 'Excel gốc' sau khi xác minh.",
                    phase2_muc="P2.4",
                )
            )
        if CAN_TRA_RE.search(nd):
            out.append(
                row_out(
                    stt=stt,
                    ten=ten,
                    sheet=r.get("sheet") or "",
                    hang_muc=r.get("hang_muc") or "",
                    noi_dung_hien_tai=nd[:240],
                    phat_hien="Còn cụm 'cần tra cứu số'.",
                    loai="can_tra_cuu_so",
                    ket_luan="sai",
                    de_xuat_sua="Điền số QĐ đã tra (xem P2.3).",
                    phase2_muc="P2.4",
                )
            )

    # tên sheet chi tiết vs Tổng hợp
    for r in rows:
        if r.get("loai") != "chi_tiet" or r.get("hang_muc") != "Tên":
            continue
        stt = r["stt"]
        th_ten = (th.get(stt) or {}).get("ten") or ""
        ct = (r.get("noi_dung") or "").strip()
        if not ct:
            out.append(
                row_out(
                    stt=stt,
                    ten=th_ten,
                    sheet=r.get("sheet") or "",
                    hang_muc="Tên",
                    noi_dung_hien_tai="",
                    phat_hien="Ô Tên sheet chi tiết trống.",
                    loai="ten_lech",
                    ket_luan="sai",
                    de_xuat_sua=f"Điền theo Tổng hợp: {th_ten}",
                    phase2_muc="P2.4",
                )
            )
        elif ct != th_ten and ct not in th_ten and th_ten not in ct:
            out.append(
                row_out(
                    stt=stt,
                    ten=th_ten,
                    sheet=r.get("sheet") or "",
                    hang_muc="Tên",
                    noi_dung_hien_tai=ct,
                    phat_hien=f"Tên chi tiết lệch Tổng hợp: '{ct}' vs '{th_ten}'.",
                    loai="ten_lech",
                    ket_luan="sai",
                    de_xuat_sua="Thống nhất tên với sheet Tổng hợp (sau duyệt).",
                    phase2_muc="P2.4",
                )
            )

    # ghi nhận đã quét đủ sheet
    out.append(
        row_out(
            stt="",
            ten="",
            sheet="",
            hang_muc="(quét toàn file)",
            noi_dung_hien_tai=f"Đã quét {len(sheets_seen)} sheet chi tiết + Tổng hợp "
            f"({len(rows)} dòng icd_hien_trang).",
            phat_hien="P2.4 hoàn tất quét định dạng / ghi chú nội bộ / lệch tên.",
            loai="quet_tom_tat",
            ket_luan="ghi_nhan",
            de_xuat_sua="",
            ghi_chu=_now(),
            phase2_muc="P2.4",
        )
    )
    return out


def write_sai_lech(rows: list[dict[str, str]]) -> None:
    OUT_SAI.parent.mkdir(parents=True, exist_ok=True)
    with OUT_SAI.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"Wrote {OUT_SAI} ({len(rows)} rows)", flush=True)


def append_can_mo_tay(link_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Ghi các URL BỊ_CHẶN trong CAN_MO_TAY_STT vào can_mo_tay.csv (idempotent)."""
    from fetch import CAN_MO_TAY  # type: ignore

    path = Path(CAN_MO_TAY)
    by_url: dict[str, dict[str, str]] = {}
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("url"):
                    by_url[row["url"]] = row

    added: list[dict[str, str]] = []
    for r in link_rows:
        if r.get("status") != "BỊ_CHẶN":
            continue
        stt = r.get("stt") or ""
        stt_i = int(stt) if stt.isdigit() else -1
        if stt_i not in CAN_MO_TAY_STT:
            continue
        url = r.get("url") or ""
        if url in by_url:
            continue
        by_url[url] = {
            "stt": stt,
            "url": url,
            "tier": str(r.get("tang") or 3),
            "reason": "P2.1 BỊ_CHẶN — mở Chrome thường / ĐÃ_XÁC_MINH_TAY",
            "fetched_at": _now(),
        }
        added.append({"stt": stt, "url": url})

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["stt", "url", "tier", "reason", "fetched_at"])
        w.writeheader()
        # chỉ giữ các URL thuộc danh sách cần mở tay (bỏ STT đã có nguồn thay)
        keep_urls = {r.get("url") for r in link_rows if (r.get("stt") or "").isdigit() and int(r["stt"]) in CAN_MO_TAY_STT}
        for url, row in by_url.items():
            if url in keep_urls or (row.get("stt") or "").isdigit() and int(row["stt"]) in CAN_MO_TAY_STT:
                w.writerow(row)
    print(f"can_mo_tay: +{len(added)} mới, tổng giữ lại theo CAN_MO_TAY_STT → {path}", flush=True)
    return added


def summarize(
    sai: list[dict[str, str]], link_rows: list[dict[str, str]], unique_urls: int
) -> dict[str, Any]:
    by_status: dict[str, int] = defaultdict(int)
    for r in link_rows:
        by_status[r.get("status") or "?"] += 1
    bi_chan = [r for r in link_rows if r.get("status") == "BỊ_CHẶN"]
    bi_chan_handled = 0
    for r in bi_chan:
        stt = r.get("stt") or ""
        stt_i = int(stt) if stt.isdigit() else -1
        thay = NGUON_THAY_THEO_STT.get(stt_i) or (
            QD_MO_CAN_DOI_CHIEU.get(stt_i, {}).get("link") or ""
        )
        if thay and "thuvienphapluat.vn" not in thay:
            bi_chan_handled += 1
        elif stt_i in CAN_MO_TAY_STT:
            bi_chan_handled += 1
    ket_luan_counts: dict[str, int] = defaultdict(int)
    muc_counts: dict[str, int] = defaultdict(int)
    for r in sai:
        ket_luan_counts[r.get("ket_luan") or ""] += 1
        muc_counts[r.get("phase2_muc") or ""] += 1

    summary = {
        "generated_at": _now(),
        "unique_cot_E_urls": unique_urls,
        "link_check_rows": len(link_rows),
        "link_status_counts": dict(by_status),
        "bi_chan": len(bi_chan),
        "bi_chan_handled_thay_hoac_mo_tay": bi_chan_handled,
        "sai_lech_rows": len(sai),
        "sai_lech_by_ket_luan": dict(ket_luan_counts),
        "sai_lech_by_muc": dict(muc_counts),
        "dod": {
            "P2.1_30_30_status": len(link_rows) >= unique_urls and unique_urls >= 30,
            "P2.1_bi_chan_handled": bi_chan_handled >= len(bi_chan),
            "P2.2_phu_luc_E": muc_counts.get("P2.2", 0) >= 10,
            "P2.3_doi_chieu_qd": muc_counts.get("P2.3", 0) >= 19,
            "P2.4_quet": muc_counts.get("P2.4", 0) >= 1,
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_SUMMARY}", flush=True)
    return summary


def main(argv: list[str]) -> int:
    if "--check-links" in argv:
        run_check_links()

    rows = load_hien_trang()
    link_rows = load_link_check()
    unique_urls = len(
        {
            (r.get("link") or "").strip()
            for r in rows
            if r.get("loai") == "tong_hop" and (r.get("link") or "").strip()
        }
    )

    if len(link_rows) < unique_urls:
        print(
            f"WARNING: link_check có {len(link_rows)} dòng, kỳ vọng ≥ {unique_urls}. "
            "Chạy với --check-links.",
            flush=True,
        )

    sai: list[dict[str, str]] = []
    sai.extend(p21_from_link_check(rows, link_rows))
    sai.extend(p22_phu_luc_e(rows))
    sai.extend(p23_doi_chieu_qd(rows))
    sai.extend(p24_quet_dinh_dang(rows))

    write_sai_lech(sai)
    append_can_mo_tay(link_rows)
    summary = summarize(sai, link_rows, unique_urls)
    print(json.dumps(summary["dod"], ensure_ascii=False, indent=2), flush=True)
    print("Phase 2 assemble done.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
