# Bàn giao dự án ICD-mapping (Phase 0–6)

**Ngày bàn giao:** 05/11/2026 (Asia/Saigon, UTC+7)  
**Nhánh làm việc:** `phase3-fill` (không push / không mở PR — người dùng giữ quyền duyệt)  
**File gốc (chỉ đọc):** `Thông tin ICD 34 tỉnh năm 2026.xlsx`  
**File bàn giao Excel:** `Thông tin ICD 34 tỉnh năm 2026 - đã kiểm tra.xlsx`

## Tiến độ

| Phase | Nội dung | Trạng thái |
|-------|----------|------------|
| 0 | Chuẩn bị, quy tắc, extract | Hoàn thành |
| 1 | fetch / match / check_links | Hoàn thành (30/10/2026) |
| 2 | Kiểm link & sai lệch hiện có | Hoàn thành (30/10/2026) |
| 3 | Tra cứu, chọn link, đề xuất trạng thái | Hoàn thành (30/10/2026 + fill) |
| 4 | Duyệt tay | **Hoàn thành** — người dùng đã duyệt tay + xác minh hết dòng có URL và dòng bot đề xuất; không cần kiểm lại |
| 5 | Ghi Excel (`scripts/build_excel.py`) | **Hoàn thành** |
| 6 | Verify + tài liệu (`scripts/verify.py`) | **Hoàn thành** |

## Sản phẩm chính

1. **Excel bàn giao** — `Thông tin ICD 34 tỉnh năm 2026 - đã kiểm tra.xlsx`
   - Sheet `Tổng hợp`: cột F–I (trạng thái 10/2026, link ICD, kết quả kiểm tra, ghi chú)
   - 128 sheet chi tiết **01–128 đúng thứ tự**, gồm **08 Tân Cảng Quế Võ** (tạo mới)
   - Mỗi sheet chi tiết: dòng 13–16 (tình trạng thực tế, link, nguồn, kết quả kiểm tra)
   - Sheet `Kiểm tra sai lệch` (196 dòng từ `data/sai_lech.csv`)
   - Sheet `Thống kê`
   - **0 ô gốc bị đổi** (chỉ điền ô trống / cột·dòng mới)
2. **Báo cáo** — `docs/bao_cao_du_an.docx` (+ PDF trong `final_delivery/` nếu LibreOffice xuất được)
3. **Hai tệp Excel riêng** (giữ nguyên theo yêu cầu trước):  
   `/workspace/icd_phase3_out/nop_co/cang_can_cap_nhat.xlsx`,  
   `/workspace/icd_phase3_out/nop_co/cang_can_goc_kem_update.xlsx`
4. **Trạng thái chốt** — `data/final_status.csv` (128 dòng)
5. **Nghiệm thu** — `docs/phase456_acceptance.md`
6. **Verify report** — JSON từ `scripts/verify.py`

## Số liệu kiểm chứng (Phase 5–6)

- Trạng thái F: Chưa triển khai 95 · Đang hoạt động 15 · Đã công bố mở 10 · Đang xây dựng 4 · Chưa đủ thông tin 4 (=128)
- Cột G có URL riêng ICD: **100/128** (không dùng URL chung QĐ 979)
- G trống có chủ đích: 27 dòng «Chưa triển khai» (chỉ có QĐ 979 chung → R4); STT **49, 86** Đang hoạt động theo duyệt tay nhưng không có URL công khai (R3)
- Ô trống chi tiết được điền từ `tra_cuu.csv`: 120 (kèm thẻ nguồn)
- Sai lệch: 196 dòng
- `verify.py`: **PASS** (offline)
- `pytest`: **60 passed** (offline)

## Cách tái tạo

```bash
cd /workspace/ICD-mapping
.venv/bin/python scripts/build_excel.py
.venv/bin/python scripts/verify.py --json-out /tmp/verify_report.json
.venv/bin/python -m pytest -q
```

## Hạn chế thật còn lại

1. STT 49 (Giang Biên), 86 (Cam Ranh): Đang hoạt động theo duyệt tay, **chưa có nguồn/URL công khai** → G trống.
2. STT 106: còn mâu thuẫn với hiện trạng 2023 trong QĐ 979 theo QA trước; giữ theo quyết định duyệt.
3. STT 100, 101, 122, 127: chưa đối chiếu bản PDF gốc QĐ 979.
4. Không re-fetch toàn bộ link online lúc bàn giao; dựa evidence đã lưu (~30/10/2026) + xác minh tay Phase 4.
5. Một số nguồn thuvienphapluat từng bị Cloudflare; đã dùng nguồn thay / xác minh tay khi có.
6. Chưa merge/push lên remote — chờ người dùng duyệt.

## Quy tắc đã tuân thủ

R1–R2 không ghi đè ô gốc · R3 không điền khi không có link · R4 cột G riêng ICD · R8 chỉ làm trên bản sao.
