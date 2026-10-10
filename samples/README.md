# Sample cho phát triển & test

> ⚠️ **Toàn bộ file trong `samples/` là HƯ CẤU.** Không phải contract của hệ thống thật nào.
> Mục đích duy nhất: cho tool có dữ liệu để phát triển và test trước khi có spec thật.

## Vì sao tách khỏi `templates/`

| Thư mục | Là gì | Đưa cho ai |
|---|---|---|
| `templates/api/` | **Template thật** — anh điền, có 3 operation thật của portal | Người dùng tool |
| `samples/` | **Dữ liệu hư cấu** — để dev/test tool | Lập trình viên |

Trộn hai thứ này lại rất nguy hiểm: một endpoint hư cấu bị tưởng là thật thì tool sẽ sinh ra
testcase gọi endpoint không tồn tại — đúng cái sai mà cả dự án này sinh ra để tránh.

Nên sample ở đây dùng một hệ thống **hoàn toàn bịa**: "Task Manager API". Không dính dáng gì
tới portal, nên không thể nhầm.

## `openapi/task-manager-sample.yaml`

Cố ý bao đủ nhiều hình dạng để generator bị thử thách:

| Hình dạng | Ở đâu |
|---|---|
| Path parameter | `/projects/{project_id}` |
| Query parameter + phân trang | `?page=&page_size=&status=` |
| Body có field bắt buộc | `POST /projects` |
| Enum | `status`, `priority` |
| Ràng buộc số — để test biên | `minLength`, `maxLength`, `minimum`, `maximum` |
| Mảng | `tags`, `items` |
| Object lồng nhau | `owner{id,name,email}` |
| Nhiều mã lỗi | 400, 401, 403, 404, 409, 422, 500 |
| Endpoint public & cần token | `/health` vs phần còn lại |
| Không có body | `DELETE`, `GET` |
| `x-qc-*` | ngưỡng latency, mức ưu tiên, dữ liệu mẫu |

Có đủ hình dạng thì generator viết xong sẽ chạy được trên spec thật mà không phải sửa nhiều.

## Bộ tài liệu SalonHub (lấy từ source thật)

`customer/`, `customer_e2e_test_1/`, `order_product/` là URD/SRS/OpenAPI viết từ source
SalonHub thật. Đây là ngoại lệ của quy tắc "hư cấu" ở trên. Project chạy chúng nằm ở
`projects/<cùng tên>/qctool.yaml`.

## Khi nào xoá

Khi spec thật của portal có, `samples/openapi/task-manager-sample.yaml` vẫn **giữ lại** —
dùng làm bộ test hồi quy cho generator. Spec thật đổi theo thời gian; sample thì cố định,
nên nó là cái neo để biết generator có bị hỏng không.
