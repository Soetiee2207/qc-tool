# Template testcase — nguồn gốc và cách sinh lại

## File

| File | Là gì |
|---|---|
| `testcase-template.xlsx` | Template testcase, 14 cột, **sinh tự động** |
| `../../scripts/build_testcase_template.py` | Script sinh ra file trên |
| `../../scripts/validate_openapi.py` | Kiểm tra file OpenAPI trước khi dùng |

**Sinh lại:**

```bash
uv run scripts/build_testcase_template.py
```

## Nguồn gốc 14 cột

Ảnh `Screenshot From 2026-09-17 10-28-26.png` — bảng *"Standard Test Case Template Structure"*,
2 cột `Field Name` | `Description / Example Entry`, 14 dòng.

Ảnh **không phải** file Excel — nó là bảng mô tả field. File `.xlsx` này là bản dựng lại từ mô tả đó.

Thứ tự và tên cột giữ **đúng nguyên văn** trong ảnh.

## Quy ước

> **Một dòng = một testcase.** Không phải một bước.

Các bước nằm chung trong ô `Test Steps`, đánh số `1.` `2.` `3.` — đúng như ảnh spec mô tả ở dòng
`Test Steps`: *"Sequential actions required to execute the test: 1. Navigate to the login page. 2. Enter email and password. 3. Click the 'Sign In' button."*

Quy ước ID: `TC_{MODULE}_{NNN}` — ví dụ `TC_AUTH_001` (ảnh spec cũng dùng dạng này).

## Hai nhóm cột

Màu header phân biệt cột nào điền lúc nào. Đây là **ranh giới generator ↔ runner**:

| Nhóm | Màu | Số cột | Điền khi nào |
|---|---|---|---|
| Tool sinh | Xanh đậm `#1F4E79` | 10 | Lúc sinh testcase |
| Điền khi chạy | Nâu cam `#9C5700` | 4 | Lúc thực thi |

Bốn cột runtime: `Actual Result`, `Status`, `Environment`, `Executed By / Date`.

## Tính năng có trong file

| Tính năng | Ở đâu |
|---|---|
| Dropdown `Pass / Fail / Blocked / Not Executed` | Cột `Status`, chặn nhập sai |
| Dropdown `High / Medium / Low` | Cột `Priority / Severity` |
| Tô màu theo Status | Xanh = Pass · Đỏ = Fail · Vàng = Blocked · Xám = chưa chạy |
| Chú thích khi hover | Mọi ô header — nhắc ý nghĩa cột |
| Cố định 2 cột đầu | Cuộn ngang vẫn thấy ID + Module |
| Bộ lọc tự động | Hàng 1, lọc theo Status/Module |
| Sheet "Hướng dẫn" | Giải thích màu và cách dùng |

## Khi nào sửa file này

**Không sửa trực tiếp file `.xlsx`.** Sửa xong thì lần sinh sau sẽ ghi đè.

Muốn đổi cấu trúc → sửa `scripts/build_testcase_template.py` rồi chạy lại.
Muốn đổi **dữ liệu** trong một lần test cụ thể → sửa file output trong `artifacts/`, không đụng template.

## Còn thiếu

File hiện tại dựng từ **mô tả field**, chưa phải file template gốc của team.

Nếu team có file `.xlsx` thật (có sẵn logo, sheet phụ, cột gộp, công thức), đưa vào đây —
khi đó renderer sẽ xuất thẳng ra file đó thay vì dựng lại từ đầu.
