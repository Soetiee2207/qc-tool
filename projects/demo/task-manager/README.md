# Demo — Task Manager API (hư cấu)

> ⚠️ **Hư cấu.** Không phải contract của hệ thống thật nào. Dùng để thử tool và làm bộ
> test hồi quy cho generator: spec thật đổi theo thời gian, spec này thì cố định.

```bash
qctool demo    # tự bật tests/mock_server.py (cổng 8099) rồi chạy feature này
```

Mock server cài **4 bug API + 4 bug giao diện**, nên một lượt chạy thấy đủ cả Đạt lẫn Lỗi.
Kết quả mong đợi: `54 test · 29 đạt · 15 lỗi · 10 bị chặn` → `artifacts/`.

`openapi.yaml` cố ý bao đủ nhiều hình dạng để generator bị thử thách:

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

Không trộn với `templates/api/` (template thật để người dùng điền): một endpoint hư cấu
bị tưởng là thật thì tool sẽ sinh testcase gọi endpoint không tồn tại.
