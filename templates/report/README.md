# Template báo cáo — hướng dẫn

File: `report-template.md`

## Nguyên tắc

Báo cáo viết cho **người đọc**, không phải cho máy. Cụ thể:

- Ngôn ngữ đơn giản. "Có 42 test, 38 đạt, 4 lỗi" — không phải "Test execution summary: 90.48% pass rate".
- **Số liệu lên đầu.** Người đọc chỉ cần 10 giây để biết đợt test này ổn hay không.
- Danh sách lỗi xếp ngay dưới, mỗi lỗi 1 dòng.
- Không đưa chi tiết kỹ thuật vào báo cáo chính. Ai cần thì mở file testcase hoặc JUnit XML.

## Cấu trúc

| Mục | Nội dung | Ai đọc |
|---|---|---|
| 1. Tóm tắt | 1 câu kết luận + bảng 5 con số | Tất cả |
| 2. Chi tiết theo module | Mỗi module bao nhiêu test, đạt bao nhiêu | PO, QA lead |
| 3. Danh sách lỗi | Mỗi lỗi 1 dòng, kèm mức độ | Dev, QA |
| 4. Chưa chạy được | Case bị block + lý do | QA lead |
| 5. Độ phủ yêu cầu | Bao nhiêu % requirement có test | PO |

Hai mục 4 và 5 hay bị bỏ sót, nhưng lại là chỗ trả lời câu hỏi khó nhất:
*"Vậy còn chỗ nào chưa test?"*

## Năm con số ở Mục 1

| Số | Nghĩa | Vì sao cần |
|---|---|---|
| Tổng số test | Sinh ra bao nhiêu case | Quy mô |
| Đạt | Chạy xong, đúng như mong đợi | |
| **Lỗi** | Chạy xong, **sai** như mong đợi | Con số quan trọng nhất |
| Bị chặn | Không chạy được (thiếu dữ liệu, môi trường lỗi) | Không phải lỗi sản phẩm |
| Chưa chạy | Chưa tới lượt | Nhắc rằng đợt test chưa xong |

> **Đừng gộp "bị chặn" vào "lỗi".** Một case bị chặn vì môi trường chết **không phải** là bug
> của sản phẩm. Gộp vào sẽ làm dev đi tìm bug không tồn tại.

## Ví dụ một báo cáo đã điền

Xem `report-example.md`.

## File máy đọc

Báo cáo Markdown này là để **người** đọc. Ngoài ra tool còn xuất:

| File | Định dạng | Cho ai |
|---|---|---|
| `junit.xml` | JUnit XML | CI (Jenkins, GitLab CI, GitHub Actions) |
| `results.csv` | CSV | Mở bằng Excel, tự làm pivot |
| `results.json` | JSON | Tool khác đọc, hoặc tra cứu chi tiết từng bước |
| `evidence/` | Ảnh chụp `.png`, trace Playwright `.zip` | Khi cần tra tại sao fail |

Ba thứ đầu sinh tự động, không viết tay. Bằng chứng có khi nào là do cấu hình `ui.evidence`
(`off` / `on-fail` / `always`) — mặc định chỉ lưu khi test hỏng. Trace mở bằng:

```bash
uv run playwright show-trace evidence/TC_AUTH_001.trace.zip
```

Trong `junit.xml`: thẻ `failure` → `Fail` (sản phẩm sai), `error` → `Blocked`
(thiếu điều kiện môi trường), `skipped` → `Not Executed` (case thủ công).