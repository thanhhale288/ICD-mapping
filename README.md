# ICD-mapping

Kiểm tra, bổ sung và gắn link cho 128 ICD (file Excel 34 tỉnh năm 2026).

Plan chính: [`plan-final.md`](plan-final.md).

## Trạng thái

| Phase | Trạng thái |
|-------|------------|
| 0 – Chuẩn bị | Xong |
| 1 – fetch / match / check_links | Xong (30/10/2026) |
| 2 – Kiểm link & sai lệch hiện có | Xong (30/10/2026) |
| 3 – Tra cứu & chọn link mới | **Đóng** 30/10/2026 (0 unchecked, QĐ428 19/19 G) — chờ Phase 4 duyệt tay |
| 4 – Duyệt tay | Chưa |
| 5 – Ghi Excel | Chưa |
| 6 – Verify & bàn giao | Chưa |

## Chạy nhanh

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env   # điền BRAVE_API_KEY nếu có

# Phase 1
python3 scripts/fetch.py test
python3 scripts/match.py test
python3 scripts/check_links.py test

# Phase 2
python3 scripts/check_links.py tong-hop          # ~30 URL cột E → data/link_check.csv
python3 scripts/phase2_sai_lech.py               # → data/sai_lech.csv
```

Đầu ra Phase 2: `data/sai_lech.csv`, `data/phase2_summary.json`, `data/can_mo_tay.csv` (link cần mở Chrome thường).

```bash
# Phase 3
python3 scripts/phase3_operators.py          # P3.1 mạng lưới nhà khai thác
python3 scripts/phase3_search.py --lo all    # P3.2 tìm ứng viên (Brave)
python3 scripts/check_links.py ung-vien --unchecked-only --per-stt 0   # P3.3 hết URL
python3 scripts/verify_website.py from-csv data/ung_vien.csv --limit 80
python3 scripts/pick_links.py
python3 scripts/propose_status.py
python3 scripts/extract_tra_cuu.py
```

Đầu ra Phase 3: `data/ung_vien.csv`, `ung_vien_check.csv`, `link_chon.csv`, `trang_thai_de_xuat.csv`, `tra_cuu.csv`, `phase3_summary.json`.
**Xem trực quan:** mở `data/phase3_report.html` trong trình duyệt.
