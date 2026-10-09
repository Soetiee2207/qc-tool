# Chạy customer SalonHub — 7 intent từ source

Kết quả V2 (2026-10-09): 5/7 executable, 5 Pass, 0 Fail — xem `docs/findings/agent-redesign.md`.

Fixture này dùng source SalonHub thật, không phải app mock. Feature `customer`,
module `CUSTOMER`. Không có testcase YAML viết tay; tool ingest AC và tự sinh.

## Chạy full E2E

Từ root qc-tool:

```bash
uv run qctool validate --config qc_config/qctool.customer.e2e.yaml --llm
uv run qctool run --config qc_config/qctool.customer.e2e.yaml --llm
```

`validate` chỉ preflight offline, không browser/model/API. `run` chạy toàn bộ
pipeline: ingest → crawl (đăng nhập) → preparation dữ liệu tin cậy → agent DeepSeek
viết từng case (quan sát → nháp → gate → dry-run) → runner Chromium → XLSX/report.
Không bảo đảm cả 7 ca map được: thiếu bằng chứng hoặc dữ liệu phải unresolved,
không được coi là Pass. Web UI đang mở để xem trực tiếp (`headless: false`).
Không đóng terminal hoặc Chromium khi đang chạy.

Entrypoint `all` dùng cùng pipeline agent:

```bash
uv run qctool all --config qc_config/qctool.customer.e2e.yaml --llm
```

Ưu tiên `run` cho summary và exit codes. Không chạy hai lệnh `run`/`all`
cùng lúc; chúng dùng cùng thư mục output. Config bật sẵn `llm.enabled: true`; `--no-llm`
để tắt (khi đó 7 case ở dạng thủ công, Not Executed). Nên có `QCTOOL_LLM_THINKING=disabled`
trong `.env` — chế độ thinking làm câu trả lời bị cắt (`finish_reason: length`).

## Env/config cần chú ý

Trong `.env` gitignored, không paste giá trị vào terminal/log/issue:

- `QCTOOL_USERNAME`: email của **customer có sẵn**.
- `QCTOOL_PASSWORD`: mật khẩu đúng của account đó.
- `QCTOOL_LLM_API_KEY`, `QCTOOL_LLM_MODEL`, `QCTOOL_LLM_BASE_URL`:
  adapter OpenAI-compatible cho DeepSeek đã cấu hình.
- `QCTOOL_LLM_TIMEOUT_SECONDS`: timeout mỗi model call; có thể đặt `90` nếu cần.

Config đã bind cả `email`, `password`, `correct_password` vào alias active_user
cho AC-001-1/3/4/5/6. Không có fixture cho AC-001-2/7 vì không cần dữ liệu account.
Account trong env đã được người dùng xác nhận hợp lệ. Config ghi facts dưới
assurance **DECLARED**, đặt `require_verified: false`, không cấu hình verification
probe. Vì vậy preparation không gọi login chỉ để kiểm lại account trước mỗi case.
Đây là tin cậy input của operator, không phải gắn nhãn live VERIFIED hoặc Pass.
Thiếu env vẫn là blocker; testcase login thực sự vẫn phải kiểm 200/success/URL.
Nếu account bị từ chối lúc thực thi, giữ nguyên expected và báo kết quả thật.
Provisioning luôn tắt trên website này.

- `feature: customer`: namespace requirement IDs.
- `generation.profile: agent` (V2; `business` cũ là alias): mỗi AC một intent cho agent.
- `web_url`: frontend Vercel; `run.base_url`: backend Render, không đảo hai URL.
  Host backend là default source; nếu deployment dùng host khác cần sửa cả config
  và `servers` OpenAPI theo host đã xác nhận.
- `auth.mode: browser`: đăng nhập form trực tiếp bằng account trong `.env` trước khi sinh
  case, để agent có macro `authenticate:active_user` dùng lại. Mỗi testcase vẫn tự đăng
  nhập trong When và bắt đầu phiên riêng. Đổi về `manual` nếu không muốn tool tự đăng nhập.
- `generation.budget`: 14 lượt / 90k token / 480 giây mỗi AC.
- `provisioning.enabled: false`: không tạo account/seed/OTP.
- `out.skip_run: false`: có thực thi; true chỉ generate/review, chưa thể có Pass.
- `ui.retry: 0`: không che lần fail đầu bằng retry.
- `ui.evidence: always`, `ui.trace: true`, `ui.trace_sensitive: true`: mọi case có trace,
  **kể cả bước gõ mật khẩu và token** — chỉ xem cục bộ, xoá `evidence/` sau khi xem.
  Đặt `trace_sensitive: false` để quay lại chế độ an toàn (case đăng nhập không có trace).
- `out.dir`: `artifacts/customer-e2e`. Dùng thư mục mới khi cần giữ từng lượt chạy.

Render có thể cold start. Warm-up tùy chọn trước full run, chỉ GET health:

```bash
curl --silent --show-error --max-time 90 --output /dev/null \
  --write-out 'HTTP %{http_code}\n' \
  https://salonhub-3cg8.onrender.com/api/health
```

Warm-up không verify credentials. `run.timeout_seconds` không tự tăng mọi timeout
capture/verification. Timeout là blocker môi trường, không tự kết luận bug sản phẩm.

## Đọc kết quả

Trong `artifacts/customer-e2e/`:

- `requirements.yaml`: expected source và traceability (1 US + 7 AC = 8 records).
- `ui-map.yaml`: controls/pages thực sự crawl được.
- `generation.json`: coverage, gaps, preparation và resolution audit.
- `testcases.yaml`, `testcases.xlsx`: IR và tài liệu testcase; không sửa tay.
- `runs/<run>/`: `results.json`, `results.csv`, `junit.xml`, `report.md`, evidence
  khi runner tạo được. Kiểm tra summary/log chỉ đường dẫn chính xác của lượt chạy.
- `summary.json`, `pipeline.log`: summary và tiến trình nếu pipeline tạo thành công.

Đúng **7 obligations** không có nghĩa 7 executable hoặc 7 Pass. Nếu xuất hiện
unresolved/manual thì vẫn giữ để chẩn đoán và không tính là automation thành công.
Source Given/When/Then phải còn đầy đủ sau mapping. So AC-001-2 phải chứng minh cả
trường trống, validation, POST count=0 và URL; riêng một assertion URL chưa đủ.

Exit codes của `qctool run`: 0 thành công; 1 execution Fail; 2 lỗi config/pipeline;
3 generation incomplete; 4 execution Blocked/Not Executed. `generation_success`
và pipeline/runtime kết quả là các khái niệm khác nhau; xem audit nếu có nhiều lỗi.

## Intent dự kiến

| AC | Logical ID khi planner chạy với bộ input trống | Intent |
| --- | --- | --- |
| 1 | TC_CUSTOMER_001 | Login customer hợp lệ |
| 2 | TC_CUSTOMER_002 | Form trống không gửi API |
| 3 | TC_CUSTOMER_003 | Xem hồ sơ/badge customer |
| 4 | TC_CUSTOMER_004 | Xem danh sách đơn của mình |
| 5 | TC_CUSTOMER_005 | Xem danh sách lịch hẹn của mình |
| 6 | TC_CUSTOMER_006 | Customer bị redirect khỏi /admin |
| 7 | TC_CUSTOMER_007 | Anonymous bị redirect khỏi /profile |

ID final có thể khác vì pipeline giữ/reserve ID các seed compatibility. AC canonical
`AC-customer-001-N` và provenance là cách đối chiếu ổn định, không chỉ số thứ tự TC.
Hai warning SRS không có FR/NFR độc lập là có chủ ý: các FR-CUSTOMER trong bảng
chỉ đối chiếu AC; không thêm nghĩa vụ trùng hoặc yêu cầu không có trong source.
