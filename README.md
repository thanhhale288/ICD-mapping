# ICD-mapping

Kiểm tra, bổ sung và gắn link cho 128 ICD (file Excel 34 tỉnh năm 2026).

Plan chính: [`plan-final.md`](plan-final.md).

## Trạng thái

| Phase | Trạng thái |
|-------|------------|
| 0 – Chuẩn bị | Xong |
| 1 – fetch / match / check_links | Xong (30/10/2026) |
| 2 – Kiểm link & sai lệch hiện có | Xong (30/10/2026) |
| 3 – Tra cứu & chọn link mới | Chưa |
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
