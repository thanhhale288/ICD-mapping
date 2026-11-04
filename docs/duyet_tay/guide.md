# Hướng dẫn duyệt tay trạng thái cảng cạn (ICD)

Tài liệu này dành cho người chưa biết gì về dự án. Đọc khoảng 10 phút là làm được.

## 1. Bạn đang làm gì?

Dự án đang lập danh sách 128 **cảng cạn (ICD, Inland Container Depot)** ở Việt Nam. Cảng cạn là bãi hoặc kho nằm sâu trong đất liền, nơi container được làm thủ tục hải quan và xếp dỡ giống như ở cảng biển.

Với mỗi cảng cạn, ta cần biết nó **đang ở trạng thái nào**. Máy và bot đã tự tra trước, nhưng còn một số dòng chưa chắc. Việc của bạn là **kiểm tra lại bằng mắt** xem đề xuất của bot có đúng không.

File cần dùng là **`duyet_tay_bot_de_xuat.xlsx`**.

## 2. 6 trạng thái và cách nhận biết

| Trạng thái | Nghĩa | Câu thường gặp trong nguồn |
|---|---|---|
| **Đang hoạt động** | Cảng đang nhận hàng, đang khai thác | "đã đưa vào khai thác", "chính thức vận hành", "đón container đầu tiên", "sản lượng năm 2025 đạt…" |
| **Đã công bố mở** | Bộ GTVT hoặc Bộ Xây dựng đã ra Quyết định công bố mở cảng, nhưng chưa thấy tin cảng đã chạy | "Quyết định …/QĐ-BGTVT công bố mở cảng cạn X", "Nay công bố cảng cạn X" |
| **Đang xây dựng** | Đã khởi công nhưng chưa xong | "khởi công", "đang thi công", "hoàn thành giai đoạn 1 vào…" (công trình có thật, đang làm) |
| **Chưa triển khai** | Mới chỉ có trong quy hoạch, chưa có gì trên thực địa | "kêu gọi đầu tư", "giai đoạn sau 2030", "chưa có nhà đầu tư" |
| **Đã ngừng/di dời** | Từng hoạt động nhưng nay đã đóng hoặc chuyển đi | "chấm dứt hoạt động", "di dời", "thu hồi quyết định" |
| **Chưa đủ thông tin** | Tìm không ra câu nào nói rõ | Dùng khi **không chắc**. Đây là lựa chọn an toàn |

> **Nguyên tắc vàng: không đoán.** Không có câu nào nói rõ về đúng cảng đó thì chọn **Chưa đủ thông tin**. Ghi sai còn tệ hơn để trống.

## 3. 5 bẫy hay gặp (đọc kỹ)

1. **Câu nói về tương lai không tính.** Ví dụ "sẽ đưa vào hoạt động", "dự kiến năm 2027", "khi cao tốc hoàn thành…". Những câu này chỉ là kế hoạch.
2. **Văn bản quy hoạch không phải bằng chứng hoạt động.** QĐ 979/QĐ-TTg năm 2023 là *quy hoạch* hệ thống cảng cạn, chỉ liệt kê cảng sẽ có. Gặp nguồn này thì tối đa chọn "Chưa triển khai" hoặc "Chưa đủ thông tin".
3. **Nhầm đối tượng.** "Cảng Thị Nại" là cảng biển, "cảng thủy nội địa Yên Lệnh" là cảng sông, "ICD-10" là mã bệnh y tế. Những thứ này **không phải** cảng cạn. Câu trích phải nói đúng *cảng cạn hoặc ICD + tên đó*.
4. **Câu phủ định.** Ví dụ "chưa được công bố", "không đủ điều kiện". Những câu này không chứng minh cảng đã mở.
5. **Đóng địa điểm hải quan không có nghĩa là đóng cảng.** Một QĐ của Bộ Tài chính "chấm dứt địa điểm làm thủ tục hải quan" chưa chắc là cảng đã ngừng. Cần thêm nguồn khác mới kết luận.

## 4. Các cột trong file

| Cột | Ý nghĩa | Bạn có sửa không? |
|---|---|---|
| `stt`, `ten` | Số thứ tự và tên cảng cạn | Không |
| `trang_thai_hien_tai` | Trạng thái script đang gán | Không |
| `bot_de_xuat` | Trạng thái bot đề xuất sau khi tra web | Không |
| `do_chac` | Bot tự đánh giá mức chắc: **cao** (nguồn chính thức nói đúng tên), **trung_binh** (nguồn phụ, đoạn trích Google, tin cũ), **thấp** (gần như không có bằng chứng) | Không |
| `can_ban_xem` | **CÓ** (ô màu cam) nghĩa là cần bạn xem | Không |
| `url_bang_chung_bot` | Link bot dùng làm bằng chứng chính | Không |
| `cau_trich_bot` | Câu nguyên văn bot trích từ link đó | Không |
| `ghi_chu_bot` | Lưu ý của bot | Không |
| `tat_ca_link_da_tim` | Mọi link đã tìm được cho cảng này | Không |
| **`trang_thai_dung`** (vàng) | **Trạng thái bạn kết luận**, chọn từ dropdown | **Có** |
| **`ghi_chu_duyet`** (vàng) | Link và câu bằng chứng của bạn, hoặc lý do bạn chọn | **Có** |

## 5. Quy trình cho từng dòng (3 đến 5 phút một dòng)

Lọc cột `can_ban_xem` = **CÓ** (bấm mũi tên ở tiêu đề cột). Sau đó làm lần lượt từng dòng:

**Bước 1: Đọc `cau_trich_bot`.** Tự hỏi:
- Câu này có nói đúng *cảng cạn hoặc ICD + tên* ở cột `ten` không?
- Đây là chuyện đã xảy ra, hay là kế hoạch hoặc tương lai?

**Bước 2: Mở `url_bang_chung_bot`** (bấm giữ Ctrl/Cmd rồi click, hoặc copy dán vào Chrome). Bấm Ctrl+F, dán một đoạn của câu trích để tìm, rồi xem câu đó có thật trên trang không và ngày đăng là khi nào.

**Bước 3: Quyết định.**
- Bot đúng: để trống `trang_thai_dung`, nghĩa là đồng ý với bot.
- Bot sai, hoặc bạn tìm được nguồn tốt hơn: chọn trạng thái đúng ở `trang_thai_dung`, rồi dán link và câu bằng chứng vào `ghi_chu_duyet`.

**Bước 4 (chỉ khi câu trích trống hoặc sai):** thử các link ở `tat_ca_link_da_tim`, hoặc Google:
```
"cảng cạn <tên>" <tỉnh>
"ICD <tên>" công bố mở
"cảng cạn <tên>" khai thác
```
Nên ưu tiên các nguồn sau:
- mt.gov.vn hoặc moc.gov.vn (Bộ GTVT / Bộ Xây dựng)
- vinamarine.gov.vn (Cục Hàng hải)
- cổng thông tin tỉnh
- web của chủ đầu tư
- báo lớn: VnExpress, Báo Đầu tư, Nhân Dân

Tìm 5 phút mà không ra thì chọn **Chưa đủ thông tin** rồi qua dòng khác.

> Mẹo: thuvienphapluat.vn đôi khi hiện "Verify you are human". Bạn bấm vào ô đó là trang mở ra.

## 6. Ví dụ mẫu

**Đúng, để trống:**
- `ten`: Km3+4 Móng Cái, `bot_de_xuat`: Đã công bố mở
- `cau_trich_bot`: "Nay công bố cảng cạn Km3+4 Móng Cái, tỉnh Quảng Ninh…" (QĐ 3882/QĐ-BGTVT ngày 30/10/2015)
- Câu nói đúng tên, có số và ngày của QĐ, nên bot đúng.

**Sai, cần sửa:**
- `bot_de_xuat`: Đang hoạt động
- `cau_trich_bot`: "khi cao tốc hoàn thiện, tỉnh sẽ đưa vào khai thác cảng cạn…"
- Đây là câu tương lai. Bạn chọn `trang_thai_dung` = **Chưa triển khai** hoặc **Chưa đủ thông tin**, rồi ghi vào `ghi_chu_duyet`: "câu tương lai, chưa hoạt động".

**Nhầm đối tượng:**
- `ten`: Thị Nại, `cau_trich_bot` nói về "cảng Thị Nại đón tàu 10.000 tấn".
- Đó là cảng biển, không phải cảng cạn, nên chọn **Chưa đủ thông tin** và ghi "nguồn nói cảng biển".

## 7. Làm xong thì sao?

1. Lưu file, giữ nguyên tên và định dạng `.xlsx`.
2. Gửi lại cho Hà Lê.
3. Hệ thống sẽ áp các dòng bạn sửa vào phần sửa tay và tính lại toàn bộ.

**Mẹo làm nhanh:** chia mỗi buổi 10 đến 15 dòng. Dòng nào phân vân thì ghi "?" vào `ghi_chu_duyet` kèm lý do, đừng cố kết luận.
