# Nghiệm thu Phase 3 (P3.1–P3.7)

Nhánh `phase3-fill`, số liệu đọc từ `data/` tại commit `d3d64fa` (ICD Data, 05/11/2026 01:28 UTC+7).
`data/phase3_summary.json` và `data/phase3_report.html` được tạo lại 05/11/2026 18:28 (UTC+7) bằng
`python scripts/phase3_summary.py` (chỉ đọc CSV, không gọi mạng). Đã đối chiếu `trang_thai_de_xuat.csv` với
`final_status.csv` của ICD Data: 128/128 dòng khớp trạng thái, URL và câu trích (0 khác biệt).

## Chạy test tự động (offline)

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q        # 56 passed, không cần mạng
```

`tests/conftest.py` chặn mọi socket; `fetch.py` (thuvienphapluat/vimawa/mt.gov.vn/baochinhphu) được giả lập
bằng `httpx.MockTransport` + Playwright giả, cache/evidence ghi vào thư mục tạm. CI: `.github/workflows/ci.yml`.

## Bảng đối chiếu

| Mục | Yêu cầu (plan-final.md) | Bằng chứng | Lệnh kiểm |
|---|---|---|---|
| P3.1 | Danh mục mạng lưới nhà khai thác | `data/operator_networks.json` (7/7 nhà khai thác), dòng `loai_nguon=operator_network` trong `data/ung_vien.csv` | `python scripts/phase3_operators.py` |
| P3.2 | Link ứng viên 3 lô, 128 STT × ≥2 query | `data/ung_vien.csv`: 3204 dòng, phủ 128/128 STT (5 dòng `stt` rỗng, xem Tồn đọng) | `python scripts/phase3_search.py --lo all` |
| P3.3 | Kiểm mọi link ứng viên, 0 unchecked | `data/ung_vien_check.csv`: 2547 dòng — MỞ_ĐƯỢC_KHÔNG_KHỚP 1027, MỞ_ĐƯỢC_KHỚP 666, CHỈ_KHỚP_CHUNG 481, LINK_CHẾT 252, LỖI_SSL_MỞ_ĐƯỢC 96, BỊ_CHẶN 25. `unchecked_urls` = **0** (2541 cặp (stt,url) unique trong ung_vien, tất cả đã kiểm) | `python scripts/check_links.py ung-vien --unchecked-only --per-stt 0`; test `tests/test_fetch.py`, `test_check_links_stability` |
| P3.4 | `verify_website.py` (Phụ lục F) | `data/website_verify.csv`: 2546 dòng — chính thức 34, có khả năng 1564, loại 948 | `pytest tests/test_script_suites.py::test_verify_website_unit` |
| P3.5 | `pick_links.py`, 128 dòng, QĐ 428 19/19 | `data/link_chon.csv`: 128 dòng, 99 có `url_chon`, 29 trống có lý do | `pytest -k PickLinksTests`; `python scripts/pick_links.py` |
| P3.6 | `tra_cuu.csv` chỉ ghi khi có URL + câu trích | `data/tra_cuu.csv`: 120 dòng, 0 dòng thiếu `url`/`cau_trich` | `pytest -k ExtractTraCuuTests` |
| P3.7 | Đề xuất trạng thái 128/128 | `data/trang_thai_de_xuat.csv`: 128 dòng — Chưa triển khai 95, Đang hoạt động 15, Đã công bố mở 10, Đang xây dựng 4, Chưa đủ thông tin 4 (STT 23, 27, 31 hạ xuống ở e577674). Nguồn (theo `final_status.csv`): tu_dong 69, duyet_tay 53, bot 6. Độ tin cậy: trung_binh 64, cao 45, duyet_tay 17, thap 2 (gồm override `data/trang_thai_override.csv`) | `pytest -k "ProposeStatusTests or MatchedGateTests or V4Tests or FinalTableTests"` |
| DoD | `phase3_summary.json` / `phase3_report.html` khớp số liệu | Đã tạo lại tại d3d64fa; `tests/test_phase3_summary.py` kiểm summary đã commit khớp CSV | `python scripts/phase3_summary.py` |

## Tồn đọng (chưa đạt)

- Còn thiếu câu trích: STT 21, 27, 49, 67, 86 (27 nay là Chưa đủ thông tin; 23 và 31 đã bổ sung ở d3d64fa).
- STT 49, 86 (Đang hoạt động): không có URL và bằng chứng hiện có mâu thuẫn với trạng thái Đang hoạt động — cần duyệt lại.
- `ung_vien.csv` có 5 dòng `stt` rỗng (Nam Hải ICD, Phước Long ICD ×2, ICD SOTRANS, ICD Transimex): không khớp ICD nào trong 128, giữ nguyên (vì vậy `checked_stts` = 129).
- Duyệt tay đợt 2 còn các dòng ghi trong `docs/duyet_tay/audit_dot2_final.md`; đối chiếu QĐ 428 cho 9 dòng vòng 3.
- Đồng bộ Google Sheet `final_status_phase3` với repo.
