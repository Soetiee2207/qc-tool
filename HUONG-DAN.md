# qc-tool — hướng dẫn sử dụng

Công cụ tự động hoá QC: đưa **tài liệu** + **OAS** + **link web** + **tài khoản**, nhận lại
**danh sách testcase**, **kết quả chạy**, và **báo cáo**.

---

## Năm lệnh cần nhớ

```bash
qctool init  <tên>            # tạo projects/<tên>/qctool.yaml
qctool check <tên>            # kiểm tra cấu hình + tài liệu, không gọi model/browser/API
qctool run   <tên>            # sinh testcase → chạy → báo cáo
qctool trace <tên> <MÃ_TEST>  # xem lại từng bước của một case
qctool ui                     # giao diện web — bấm là chạy
```

Chạy trong venv của repo (`uv sync` một lần), hoặc thêm `uv run` phía trước mỗi lệnh.
`<tên>` là thư mục trong `projects/`; cũng nhận đường dẫn thư mục hoặc file YAML.

---

## Một project = một thư mục

```bash
qctool init shop     # → projects/shop/qctool.yaml
```

File cấu hình chỉ cần vài dòng. Đường dẫn tính từ thư mục project:

```yaml
docs: ../../samples/shop            # thư mục urd.md + srs.md
openapi: ../../samples/shop/openapi.yaml
web: https://shop.example.com       # link webapp
api: https://api.shop.example.com   # địa chỉ API (bỏ thì dùng `web`)
llm: true                           # agent viết case UI từ tài liệu

account:                            # bỏ nếu webapp không cần đăng nhập
  role: customer
  login_for: [001-1, 001-3]         # AC cần đăng nhập ĐÚNG tài khoản
```

| Khoá | Mặc định khi bỏ trống |
|---|---|
| `feature` / `module` | Tên thư mục project (`shop` / `SHOP`) |
| Thư mục kết quả | `artifacts/<feature>/` |
| `auth.mode` | `browser` nếu có `account`, ngược lại `manual` |
| `generation.budget` | 14 lượt · 90k token · 480 giây mỗi AC |
| `run.timeout_seconds` | 30 |
| `ui.evidence` / `ui.trace` | `on-fail` / tắt |

**Tài khoản** luôn lấy từ `.env` (`QCTOOL_USERNAME`, `QCTOOL_PASSWORD`), không bao giờ ghi
vào YAML. Chỉ AC nằm trong `login_for` mới được dùng tài khoản. AC kiểu *"sai mật khẩu
thì báo lỗi"* thì **không** liệt kê, để tool không điền mật khẩu đúng vào case đó.

Các khoá nâng cao vẫn dùng được và luôn thắng giá trị mặc định: `auth`, `run`, `ui`,
`generation`, `provisioning`, `exploration`, `test_fixtures`. Xem ví dụ thật trong
`projects/order_product/qctool.yaml` (cho phép tạo đơn hàng thật theo rule).

---

## Thử ngay không cần hệ thống thật

```bash
qctool demo
```

Tự bật API giả (cổng 8099, có 4 bug cài sẵn) rồi chạy `projects/demo`, nên sẽ thấy cả Đạt lẫn Lỗi.

---

## Cờ hay dùng với `run`

| Cờ | Việc |
|---|---|
| `--no-llm` / `--llm` | Tắt/bật agent, đè cấu hình |
| `--only 001-1 001-3` | Chỉ sinh case cho các AC này (tiết kiệm chi phí khi thử) |
| `--skip-run` | Chỉ sinh testcase, không chạy |
| `--show-browser` | Hiện cửa sổ Chrome thay vì chạy ẩn |
| `--trace-sensitive` | Trace cả case có mật khẩu (⚠ file chứa bí mật) |
| `--docs` `--openapi` `--url` `--out` | Đè đường dẫn trong cấu hình |

---

## Từng chặng (nâng cao)

```bash
qctool step ingest   <thư-mục-docs> --feature <tên>
qctool step generate --requirements artifacts/<f>/requirements.yaml \
                     --openapi <spec.yaml> --xlsx artifacts/<f>/testcases.xlsx
qctool step exec     artifacts/<f>/testcases.yaml --base-url <url> --xlsx artifacts/<f>/testcases.xlsx
qctool step crawl    <url>     # dò element → ui-map.yaml
```

`step generate` không gọi LLM: OpenAPI → case API; tài liệu → case thủ công. Case UI tự
động từ tài liệu chỉ có qua `qctool run` khi bật LLM.

---

## Test UI/UX bằng trình duyệt thật

Khi có `web`, tool mở Chromium thật: dò element, chạy case UI, chụp bằng chứng. Các nút
chỉnh trong `qctool.yaml`:

```yaml
ui:
  retry: 1              # hỏng thì chạy lại 1 lần, để tách "chập chờn" khỏi "lỗi thật"
  evidence: on-fail     # ảnh chụp: off | on-fail | always
  trace: true           # ghi trace từng bước để xem lại
  axe: false            # quét accessibility
  soft_assert: false    # true = sai một bước vẫn chạy hết, thấy mọi lỗi trong 1 lượt
```

**Nút "Chạy" bị khoá có đúng không, lỗi JS có hiện ra không, con trỏ có nằm đúng ô
không**: test API không thấy được những thứ này. Bộ verb UI/UX kiểm được:
`assert.disabled`, `assert.enabled`, `assert.console_clean`, `assert.no_broken_requests`,
`assert.focused`, `assert.text`, `assert.value`, `assert.attr`, `assert.count`,
`assert.checked`, `assert.axe`, `assert.screenshot`.

Xem lại một case: `qctool trace shop TC_SHOP_001`.

---

## Đọc kết quả

Sau mỗi lần chạy, trong `artifacts/<feature>/`:

| File | Đọc để biết |
|---|---|
| `runs/<giờ>/report.md` | **Đọc cái này**: tóm tắt, chi tiết theo module, danh sách lỗi, chưa chạy được, bằng chứng |
| `testcases.xlsx` | File testcase 14 cột, **đã điền kết quả vào sẵn** |
| `runs/<giờ>/junit.xml` | Đưa vào CI |
| `runs/<giờ>/results.csv` | Mở Excel, tự làm pivot |
| `evidence/` | Ảnh chụp + trace của test UI, đặt tên theo mã test |
| `generation.json` | Agent đã gọi tool nào, sửa lỗi gì, tốn bao nhiêu token |
| `app-model.yaml` | Trang agent đã thấy + macro đăng nhập (không chứa mật khẩu) |
| `summary.json`, `pipeline.log` | Tóm tắt máy đọc được + log đầy đủ của lượt chạy |

---

## Bốn trạng thái, đừng lẫn

| | Nghĩa | Việc cần làm |
|---|---|---|
| **Đạt** | Chạy xong, đúng | — |
| **Lỗi** | Chạy xong, **sai** → **sản phẩm có bug** | Báo dev |
| **Bị chặn** | **Chưa chạy được**: thiếu dữ liệu/tài khoản/case chưa map | Bổ sung môi trường. **Không phải bug** |
| **Chưa chạy** | Case thủ công, người phải làm theo các bước trong file | Đọc cột Test Steps rồi làm |

Thêm một thứ không phải trạng thái mà là **cảnh báo**: test **chập chờn** (lần đầu hỏng,
chạy lại mới đạt). Nó nằm ở Mục 6 của báo cáo. Đừng bỏ qua: một test lúc được lúc không
là bug, chỉ là chưa biết bug của sản phẩm hay của test.

Nếu bạn thấy `Lỗi` mà nguyên nhân là "thiếu tài khoản" thì đó là **bug của tool**, báo ngay.

---

## Tài liệu và OAS — mỗi thứ dùng để làm gì

**Tài liệu (URD/SRS markdown)** là nguồn chính cho test giao diện. Agent đọc từng
acceptance criterion (Given/When/Then), tự mở website, tìm nút/ô bằng `data-testid`
hoặc role + tên, viết testcase rồi chạy thử. Kết quả mong đợi **phải trích nguyên văn**
tài liệu; agent không được lấy theo những gì website đang hiển thị. Câu mơ hồ
(*"sidebar chỉ hiện module tôi được phép"*) không có giá trị cụ thể để trích, nên case
thành `needs_review` hoặc thủ công, không bao giờ tự thành Đạt.

**OAS** cho phép: (1) sinh thẳng case API (giá trị biên, mã lỗi, ma trận xác thực) không
cần LLM; (2) agent kiểm response API sau một thao tác UI (ví dụ POST login trả 200).

> Lấy spec từ FastAPI:
> ```bash
> python -c "import json,app.main; print(json.dumps(app.main.app.openapi()))" > openapi.json
> ```

---

## LLM (agent) cho generation

Agent dùng Chat Completions tương thích OpenAI có **tool calling**
(`<base URL>/chat/completions`), đã kiểm với DeepSeek. Cấu hình một lần trong `.env`:

```bash
QCTOOL_LLM_BASE_URL=https://api.deepseek.com/v1
QCTOOL_LLM_MODEL=deepseek-chat
QCTOOL_LLM_API_KEY=…
QCTOOL_LLM_TIMEOUT_SECONDS=90
QCTOOL_LLM_THINKING=disabled      # DeepSeek: tool calling không reasoning
```

Bật bằng `llm: true` trong project hoặc `--llm`; `--no-llm` tắt kể cả khi config đã bật.
Chỉ có API key thì **không** tự bật LLM.

Mỗi call thử lại **đúng một lần** khi timeout/429/5xx. Lỗi được báo có kiểm soát, không
ghi API key/nội dung phản hồi. Model không sửa testcase trực tiếp: mọi bản nháp phải qua
gate (schema, an toàn, trích dẫn, thứ tự bước) và dry-run trên trình duyệt. Không có LLM
thì case từ tài liệu ở dạng thủ công; case OpenAPI vẫn sinh bình thường.

Agent quan sát ARIA → viết case có source quote → thử action/locator trên context riêng →
nhận lỗi để sửa trong cùng hội thoại. Dry-run **chưa** là Pass: runner mới kiểm expected.

- `ready`: gate + dry-run đủ, expected literal có nguồn.
- `needs_review`: oracle yếu/nonliteral/critic nghi ngờ; vẫn chạy, có nhãn trong report
  và Description. QC ghi quyết định tại sheet Review; 14 cột Test Cases không đổi.
- `manual` / `blocked_env`: chưa chấp nhận chạy tự động; xem `generation.json`.

Budget áp dụng **mỗi AC**, cộng thêm một call thiết kế intent. Timeout/call lỗi vẫn tốn
chi phí nếu provider đã xử lý. Dùng `--only` hoặc `generation.max_intents: 1` khi thử.
Coverage vẫn hiển thị toàn bộ nguồn: chạy một phần không có nghĩa toàn bộ tài liệu đã covered.

### Xem lại agent và Playwright đã làm gì

| Muốn xem | Mở |
|---|---|
| Agent gọi tool nào, lỗi gì, tốn bao nhiêu token | `generation.json` → `agent_history[i].history`, `provider_attempts` |
| Các bước của testcase | `testcases.yaml` hoặc `testcases.xlsx` |
| Playwright chạy từng bước ra sao | `runs/<thời gian>/results.json`, `report.md` |
| Xem lại trực quan (DOM, mạng, console) | `qctool trace <tên> <MÃ>` |

Case có điền mật khẩu hoặc bắt request đăng nhập **không** có trace/ảnh. Tool tắt có chủ ý
để file không chứa mật khẩu/token; kết quả từng bước vẫn có trong `results.json`. Muốn
xem cả bước đăng nhập: `qctool run <tên> --trace-sensitive` (hoặc `ui.trace_sensitive: true`).
⚠ Khi đó `.trace.zip` chứa mật khẩu/token thật: chỉ dùng tài khoản test, xem trên máy
mình, xoá `evidence/` sau khi xem, không chia sẻ/commit.

---

## Giới hạn hiện tại

| Chưa có | Ảnh hưởng |
|---|---|
| **Bảng traceability** | Có cảnh báo requirement thiếu test, chưa có bảng đầy đủ |
| **Hỗ trợ `.docx`/`.pdf`** | Tài liệu phải là markdown |
| **Tài khoản thiếu quyền** | Case kiểm 403/forbidden sẽ `Bị chặn` |
| **UI map nhiều trang** | Dò được nhiều trang, nhưng chưa bấm sâu vào menu để dò hết |
| **Chạy song song** | Chạy lần lượt, bộ test lớn sẽ chậm |
| **Upload file / iframe / dialog hệ thống** | Chưa có verb cho nhóm này |

---

## Khi có trục trặc

| Hiện tượng | Xử lý |
|---|---|
| Nhiều `Lỗi` với `401` | Phiên hết hạn: xoá `artifacts/<feature>/.auth-state.json` rồi chạy lại |
| Nhiều `Lỗi` với `404` | Sai `api`: thử thêm/bớt `/api/v1` |
| Crawl ra 0 element | Mạng chậm: thử lại; nếu vẫn vậy kiểm tra đăng nhập |
| Nhiều `Bị chặn` | Thiếu OAS: đây là lý do phổ biến nhất |
| Sai mật khẩu | Sửa `.env` |
| Case UI báo `Lỗi` vì không tìm thấy element | Nhãn trên trang đã đổi. Chạy `qctool step crawl <url>` rồi sinh lại testcase |
| Case a11y báo `Bị chặn` với "axe-core" | Máy không ra được Internet: chép `axe.min.js` vào `qctool/execute/` hoặc đặt `QCTOOL_AXE_PATH` |
| Báo cáo có mục "Test chập chờn" | Đọc Mục 6 và 7: trace + ảnh nằm trong `evidence/`, mở bằng `qctool trace` |
| Tool tự đăng nhập dù không muốn | Đặt `auth: {mode: manual}` trong `qctool.yaml`. Chế độ này không bao giờ tự đăng nhập |
| Đăng nhập hỏng nhưng vẫn muốn chạy case UI khác | Cứ chạy: case cần xác thực báo `Bị chặn`, case còn lại vẫn chạy |
| `Cổng 8099 đang bận` khi `qctool demo` | Tắt mock server cũ đang chạy |

Ví dụ đầy đủ: `projects/customer_e2e_test_1/` + `samples/customer_e2e_test_1/` (đăng nhập,
mua hàng, đặt lịch; dừng trước bước tạo dữ liệu).
