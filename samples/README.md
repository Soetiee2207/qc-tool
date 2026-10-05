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

## Đánh giá resolution loop offline

`evaluation/resolution-replay.yaml` chứa testcase, phản hồi model và quan sát trang
đã ghi sẵn. Bộ mẫu kiểm tra sửa Login sau hai cycle và chặn assertion trái yêu cầu.
Mọi URL trong bộ mẫu đều hư cấu; lệnh dưới chỉ đọc file, không mở webapp.

```bash
uv run python -m qctool.resolution_evaluation \
  samples/evaluation/resolution-replay.yaml --out /tmp/resolution-evaluation.json
```

Báo cáo JSON chứa executability trước/sau, số case cải thiện/hồi quy, phân bố
stop reason/cycle/gap, các repair sai hoặc không an toàn theo nhãn, và toàn bộ
lịch sử cycle. Nhãn `allowed` liệt kê đầy đủ cặp action/args chấp nhận được cho
một step; `unsafe` liệt kê cặp bị cấm. Không có nhãn thì kết quả ngữ nghĩa là
`unknown`, không được tính là đúng. Ghi nhận thiếu replay có mã `REPLAY_MISS`;
tool không gọi model hoặc trình duyệt thật để bù dữ liệu.

Mã thoát: `0` không phát hiện hồi quy/lỗi replay, `1` có hồi quy hoặc thiếu replay,
`2` bộ dữ liệu/tham số/đường dẫn output không đọc hoặc ghi được. Mã `0` không có
nghĩa là toàn bộ testcase đã executable hoặc hệ thống thật đã Pass.

### Benchmark 24 case

`evaluation/resolution-benchmark.yaml` mở rộng bộ replay thành 24 case, dựa trên
các failure mode trong test hiện có. Mỗi case ghi category, test nguồn tham chiếu,
nhãn ground truth khi review được, và outcome mong đợi. UI/OpenAPI trong
`benchmark-ui-map.yaml` và `benchmark-openapi.yaml` đều hư cấu.

```bash
uv run python -m qctool.resolution_evaluation \
  samples/evaluation/resolution-benchmark.yaml --out /tmp/resolution-benchmark.json
uv run python -m pytest tests/test_resolution_benchmark.py -q
```

| Category | Case | Executable sau resolution |
|---|---:|---:|
| Deterministic UI | 3 | 3 |
| Deterministic HTTP | 3 | 3 |
| LLM repair | 4 | 4 |
| Exploration | 3 | 2 |
| Unresolved | 4 | 0 |
| Fabricated proposal | 3 | 0 |
| Assertion safety | 4 | 1 |

Baseline: executable **0 → 13**, execution gap **45 → 18**, **14 repair đã áp dụng
khớp nhãn**, **0 repair sai/unsafe**, **6 proposal bị chặn**. 11 case còn unresolved
là outcome mong đợi, gồm thiếu môi trường, evidence mơ hồ và đề xuất trái nguồn.
Nhãn giữ nguyên `perform.unmapped`/`assert.unmapped` kiểm tra việc bảo toàn ý nghĩa
chưa giải được, không tính là repair thành công hay executable. Hai case thiếu
oracle ngữ nghĩa cố ý không gắn nhãn; không được suy ra chúng đúng về nghiệp vụ.

Các phản hồi/quan sát trong benchmark là fixture được biên soạn từ test hiện có.
Đây là benchmark an toàn/hồi quy của compiler, không phải số đo chất lượng một
model thật hoặc kết quả chạy QC trên sản phẩm thật.

## Khi nào xoá

Khi spec thật của portal có, `samples/openapi/task-manager-sample.yaml` vẫn **giữ lại** —
dùng làm bộ test hồi quy cho generator. Spec thật đổi theo thời gian; sample thì cố định,
nên nó là cái neo để biết generator có bị hỏng không.
