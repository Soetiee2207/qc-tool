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

## Đánh giá generation (V2)

Resolution loop, coverage loop và hai benchmark replay cũ (`evaluation/resolution-*.yaml`,
`evaluation/generation-benchmark.yaml`) thuộc engine đã retire ở V2 — các file trong
`samples/evaluation/` chỉ còn là lịch sử, không còn code nào đọc chúng.

Đánh giá một lượt chạy agent (chỉ đọc artifact, không gọi model/browser):

```bash
uv run python scripts/run_agent_benchmark.py artifacts/<feature>
uv run python -m pytest tests/test_generation_benchmark.py -q
```

Số đo ngữ nghĩa không có nhãn QC thì là `unknown`, không bao giờ tính là đúng.

## Acceptance thật — generation qua pipeline

`acceptance/generation/` chứa URD/SRS, luồng nghiệp vụ và OpenAPI hư cấu cho
mock server trong repo. Chạy từ thư mục gốc:

```bash
uv run python scripts/run_generation_acceptance.py --out artifacts/generation-acceptance
uv run python -m pytest tests/test_pipeline_acceptance.py -q
```

Lệnh tự mở mock HTTP trên loopback/cổng trống, chạy Chromium thật và đóng server
sau khi kiểm tra. Không cần provider/model hoặc tài khoản. Cần Chromium đã cài
(`uv run playwright install chromium` nếu thiếu). Không trỏ vào hệ thống thật.

Luồng có hai obligation: mở `/ui/du-an` đúng URL, rồi cấp tài khoản bằng quản trị
viên. Thay model thật bằng bản ghi `RouteReplay` (không phải live LLM): case route
đi qua gate + dry-run của agent rồi chạy Chromium thật; cấp tài khoản giữ manual.
`PipelineResult.ok=true` nghĩa là pipeline hoàn tất; `generation_success=false`
vì executable coverage chưa hoàn tất và nguồn FR chưa assess được.

Output gồm `requirements.yaml`, `app-model.yaml`, `generation.json`, `testcases.yaml`,
`testcases.xlsx`, `evidence/*.trace.zip`, `runs/*/results.json`, `results.csv`,
`junit.xml`, `report.md` và `acceptance-checks.json`. Script đối chiếu ID/status
giữa IR, XLSX, JSON, CSV và JUnit; kiểm tra mọi Pass có đủ step thật đã chạy.
YAML/`generation.json` là dữ liệu trước execution, không tự mang status Pass;
XLSX/results là dữ liệu runtime. Mã thoát `0` chỉ khi các acceptance check đạt,
không có nghĩa là mọi obligation đã tự động hoá.

## Khi nào xoá

Khi spec thật của portal có, `samples/openapi/task-manager-sample.yaml` vẫn **giữ lại** —
dùng làm bộ test hồi quy cho generator. Spec thật đổi theo thời gian; sample thì cố định,
nên nó là cái neo để biết generator có bị hỏng không.
