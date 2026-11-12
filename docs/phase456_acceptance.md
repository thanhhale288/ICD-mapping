# Nghiệm thu Phase 4–6

Nhánh `phase3-fill`. Số liệu đối chiếu 05/11/2026 (Asia/Saigon, UTC+7).

## Phase 4 — Duyệt tay

| Mục | Kết quả | Bằng chứng |
|-----|---------|------------|
| Duyệt dòng có URL + dòng bot đề xuất | **ĐẠT** | Người dùng chốt: đã duyệt tay + xác minh hết; không cần kiểm lại |
| `data/final_status.csv` 128 dòng | **ĐẠT** | Đồng bộ `trang_thai_de_xuat` / override sau đợt duyệt |
| Không còn blocker trước Phase 5 | **ĐẠT** | Ủy quyền ghi Excel |

## Phase 5 — Ghi Excel

| Mục | Yêu cầu (plan-final) | Kết quả | Bằng chứng |
|-----|----------------------|---------|------------|
| P5.1 Sheet 08 | Nhân bản format QĐ 428; chỉ nội dung có nguồn | **ĐẠT** | Sheet `08 Tân Cảng Quế Võ` giữa 07 và 09; QĐ 1543/QĐ-BGTVT 19/8/2021 |
| P5.2 Tổng hợp F–I | Thêm 4 cột, merge A1:I1 | **ĐẠT** | 128/128 cột F |
| P5.3 Chi tiết 13–16 | 128 sheet | **ĐẠT** | verify `detail_rows_13_16` |
| P5.4 Sai lệch + Thống kê | Sheet mới | **ĐẠT** | 196 dòng sai lệch; sheet Thống kê |
| R1/R2 | Không ghi đè ô gốc | **ĐẠT** | `original_cells_changed = 0` |
| R4 | G không phải URL chung QĐ 979 | **ĐẠT** | verify `G_not_qd979`; 100 URL G |

Lệnh: `python scripts/build_excel.py`

## Phase 6 — Verify & bàn giao

| Mục | Yêu cầu | Kết quả | Bằng chứng |
|-----|---------|---------|------------|
| P6.1 verify.py | Sheet 01–128; F đủ; ô gốc; nguồn | **ĐẠT** | `verify_report.json` PASS |
| Online re-fetch mọi link | Tùy môi trường | **Bỏ qua có báo cáo** | `online_refetch_skipped_by_design`; dựa evidence + duyệt tay |
| Pytest | Offline | **ĐẠT** | 60 passed |
| Tài liệu bàn giao | handover | **ĐẠT** | `docs/handover.md` |

Lệnh:

```bash
python scripts/verify.py --json-out /workspace/icd_phase3_out/final_delivery/verify_report.json
python -m pytest -q
```

## Hạn chế chấp nhận được

- STT 49, 86: G trống (duyệt tay, không URL công khai).
- 27 «Chưa triển khai» không có G riêng (R4).
- Chưa push/PR.
