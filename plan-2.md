---
name: Đánh giá workflow Gemini
overview: "Workflow Gemini chẩn đoán đúng file Excel, nhưng chưa ổn để chạy: taxonomy gộp “đã công bố mở” với “đang hoạt động”, pipeline tự động sẽ gán nhầm ICD trùng tên, và cách điền sheet 08 phá giọng văn thận trọng mà file đang dùng."
todos:
  - id: fix-taxonomy
    content: Tách nhãn pháp lý và hiện trạng vận hành; bỏ tiêu chí Active = đã công bố mở
    status: pending
  - id: lock-fields
    content: Khóa Tình trạng, Số QĐ, Vị trí, Quy mô đã có chữ; chỉ thêm dòng/cột mới khi có URL
    status: pending
  - id: manual-collisions
    content: Rà tay nhóm trùng tên và ICD đang chạy nhưng nằm ngoài QĐ 428 trước khi ghi Excel
    status: pending
  - id: sheet-08
    content: Nhân bản sheet 08 theo giọng thận trọng của sheet lân cận, không chốt chủ đầu tư từ bài báo triển khai
    status: pending
isProject: false
---

# Đánh giá workflow trong plan.md

**Kết luận: khung hai lớp là đúng, chưa nên chạy nguyên workflow.** Phần mô tả file khớp số liệu. Phần phân loại và pipeline thu thập sẽ ghi đè lên chuẩn mực mà file đang giữ: công bố mở không đồng nghĩa đang khai thác, và ô trống không được điền bằng suy đoán.

## Những gì plan nói đúng

Đối chiếu [plan.md](plan.md) với [Thông tin ICD 34 tỉnh năm 2026.xlsx](Thông tin ICD 34 tỉnh năm 2026.xlsx):

- 128 ICD trên sheet `Tổng hợp` (cột A–E: STT, Tên, Miền, Pháp lý, Link). Đúng 127 sheet chi tiết, thiếu đúng STT 8 (Tân Cảng Quế Võ). Không thiếu số nào khác.
- Pháp lý: 19 `QĐ 428/QĐ-BXD`, 91 `QH ngành 979`, 18 `QH tỉnh`.
- Link: 91 `vanban.chinhphu.vn` (cùng một URL QĐ 979, `docid=208522`), 22 `thuvienphapluat.vn` (18 QH tỉnh + 4 QĐ 428), 15 link còn lại đều thuộc nhóm QĐ 428.
- Mọi sheet chi tiết cùng một khung 13 hạng mục, cột A–C, font Times New Roman. Chèn dòng và nhân bản sheet 08 bằng openpyxl là khả thi.
- Ô `Tình trạng` đã được viết theo giọng đã duyệt. Không sửa ô này là đúng.
- Địa danh đã theo bản đồ 34 tỉnh: “Hà Nam cũ, nay Ninh Bình”, “Hải Dương, Hải Phòng”, “Tân Uyên (Bình Dương cũ), nay TP.HCM”, Khánh Hòa `2279/QĐ-UBND`, Hải Phòng `5455`, Ninh Bình `568`. Nguyên tắc không quy đổi ngược 63 tỉnh là đúng với dữ liệu hiện có.

## Chỗ workflow chưa ổn

### 1. Taxonomy 4 nhóm đánh đồng pháp lý với vận hành

Nhóm “Đang hoạt động” lấy tiêu chí “đã công bố mở / có mã hải quan / có bãi” nối bằng HOẶC. Cả 18 sheet nhóm QĐ 428 đều ghi cùng một câu: “Không đồng nhất công bố mở với sản lượng thực tế.” Nếu chạy đúng tiêu chí này, 19 ICD QĐ 428 bị gán Active dù file cố ý không khẳng định sản lượng.

Ngược lại, ICD đang khai thác ngoài đời nhưng không nằm trong QĐ 428 sẽ bị dán “Mới quy hoạch”. Sheet của chúng đang dùng mẫu câu pháp lý, không phải câu hiện trạng:

- STT 106 Bình Hòa (Tân Cảng Sóng Thần)
- STT 107 TBS Tân Vạn Dĩ An
- STT 98 Long Bình (TP.HCM cũ)

Ba tên này là cảng cạn đã vận hành nhiều năm. `Tình trạng` chỉ nói “chưa có căn cứ công bố mở”, tức là chưa thấy quyết định mở theo thủ tục đang xét, không phải “ngoài đời chưa có cảng”.

Nhóm 4 lấy ví dụ cụm Trường Thọ. Tên này không có trong 128 dòng. Các ca đặc thù thật sự của file là trùng tên và nhầm phạm vi diện tích: Long Bình có 3 dòng (15, 98, 126), Tân Lập có 2 (58, 121), Thạnh Phước (18) khác Thanh Phước (116). Sheet 15 và 18 đã cảnh báo không được lấy diện tích cả tổ hợp gán cho phần đã công bố mở.

### 2. Pipeline “script 3 tầng” chưa có, và query sẽ gán nhầm

Repo chỉ có `plan.md` và file Excel. Bước B2 ghi “Sẵn sàng” trong khi chưa có script, JSON hay CSV.

Tầng 1 (VNACCS / danh bạ mã hải quan) không phải API tra theo tên. Tầng 3 với query `"ICD [Tên]"` sẽ trộn các cặp trùng tên ở trên, và trộn Quế Võ với Mộc Bài: sheet 19 có câu cấm “KHÔNG áp dụng dữ liệu sông Đuống / QL18 / sà lan Quế Võ”.

Bước B3 chỉ yêu cầu duyệt tay nhóm Tân Cảng, Gemadept, VIMC. Phần còn lại sẽ bị ghi thẳng vào Excel. Với file này, đó là chỗ dễ hỏng nhất.

### 3. “STT 1–19 đã đầy đủ” là đầy ô, chưa đầy sự thật

Trong 18 sheet đã có:

- Cả 18 ô hãng tàu đều là một câu: “Chưa xác minh hãng tàu và code khai thác còn hiệu lực.”
- Đơn vị khai thác chỉ có 6 ô có chữ; nhiều ô trong số đó vẫn ghi “cần xác minh”.
- Dịch vụ và quy mô đều kèm câu không được lấy công suất quy hoạch làm sản lượng 2026.

Giai đoạn 3 bảo “bổ sung đầy đủ hãng tàu, dịch vụ” cho nhóm Active sẽ thay câu “chưa xác minh” bằng dữ liệu marketing.

### 4. Sheet 08 đang được điền bằng khẳng định, không theo giọng các sheet kia

Plan yêu cầu ghi Quế Võ: chủ đầu tư Tân Cảng Sài Gòn, KCN Quế Võ, Bắc Ninh, đã công bố mở. Trong khi đó link ở dòng tổng hợp STT 8 là bài “4 cảng cạn quy hoạch tại Bắc Ninh đang được triển khai thế nào”, còn sheet lân cận luôn ghi nguồn và mức chắc chắn. Bắc Ninh trong bản đồ 34 tỉnh cũng cần ghi theo cách file đang ghi địa danh mới, không chốt “tỉnh Bắc Ninh” nếu đề tài đã sáp nhập.

### 5. Khóa dữ liệu đang hẹp hơn dữ liệu đã duyệt

Plan chỉ khóa `Tình trạng` và link pháp lý. Các ô sau cũng đã có câu đã căn chỉnh, không được ghi đè:

- `Số QĐ thành lập` (nhóm 20–128 thực chất là “chưa xác minh quyết định mở” + số quy hoạch, không phải quyết định thành lập)
- `Vị trí` (đã chuyển sang địa danh mới)
- `Quy mô` ở những dòng đã phân biệt ha công bố với ha cả khu

91 dòng QH 979 dùng chung một mẫu `Tình trạng`. Dán thêm một câu “chưa triển khai” cho cả 109 dòng sẽ biến Sóng Thần và Tân Vạn thành quy hoạch trống.

## Cách chỉnh trước khi làm

Giữ giai đoạn 1 (thêm cột và sheet 08) nhưng đổi phần điền nội dung:

- Tách hai nhãn, không gộp: `Tình trạng pháp lý` giữ nguyên (QĐ 428 / QH 979 / QH tỉnh) và `Hiện trạng vận hành` chỉ nhận một trong: `Đang khai thác — đã có nguồn`, `Đã công bố mở — chưa chứng minh sản lượng`, `Đang đầu tư`, `Mới quy hoạch`, `Chưa đủ nguồn để kết luận`.
- Ô mới để trống cho đến khi có URL. Không có nguồn thì ghi `Chưa đủ nguồn`, không điền chủ đầu tư hay hãng tàu.
- Khóa thêm `Số QĐ thành lập`, `Vị trí`, `Quy mô` đã có chữ. Chỉ điền vào ô đang trống, hoặc thêm dòng mới `Tình trạng thực tế (2026)` và `Nguồn kiểm chứng` (không đánh số, giống dòng `Tình trạng` hiện nằm giữa hạng mục 1 và 2).
- Tra cứu theo lô có người đọc, ưu tiên trước các tên trùng và các ICD đã nổi tiếng nằm ngoài QĐ 428 (Sóng Thần, Tân Vạn, Long Bình). Mỗi dòng giữ tên ICD + tỉnh mới + URL. Bỏ trạng thái “Sẵn sàng” của B2 cho đến khi có file trung gian.
- Sheet 08 nhân bản đúng format sheet 09, viết theo cùng giọng “theo quyết định / cần tra số gốc”, không chốt chủ đầu tư nếu nguồn chỉ là bài “đang triển khai”.
- Khi thêm cột F–G trên `Tổng hợp`, nới merge tiêu đề `A1:E1` ra `A1:G1`. Cột F hiện chỉ có width mặc định, chưa có header.
