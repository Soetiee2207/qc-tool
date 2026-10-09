# qc-tool — hướng dẫn sử dụng

Công cụ tự động hoá QC: đưa **tài liệu** + **OAS** + **link web** + **tài khoản**, nhận lại
**danh sách testcase**, **kết quả chạy**, và **báo cáo**.

---

## Bốn đầu vào

```bash
./qc.sh --docs <thư-mục> --oas <file> --link <url> --acc <email> [mật-khẩu]
```

| Flag | Là gì | Bắt buộc? |
|---|---|---|
| `--docs` | Thư mục chứa `urd.md`, `srs.md` | Một trong hai |
| `--oas` | File OpenAPI spec (`.yaml`/`.json`) | Một trong hai |
| `--link` | Link webapp cần test | Nên có |
| `--acc` | Tài khoản đăng nhập | Nếu app cần đăng nhập |

Đưa được flag nào hay flag đó. Thiếu cái nào tool cũng nói rõ hệ quả.

---

## Chạy đầy đủ

```bash
cd /home/hendry/workspace/zcoding/qc-tool

./qc.sh \
  --docs /home/hendry/workspace/data-platform/data-management/vd-data-platform-portal/docs/authentication/login-sso \
  --oas ./openapi.json \
  --link https://dev-qc-portal.datafactory.fit \
  --acc v.binhhm1@vindynamics.net 'Abcd1234@'
```

Tên feature tự suy từ tên thư mục `--docs` (`login-sso`). Muốn đặt khác thì thêm `--feature <tên>`.

---

## Ba cách đưa mật khẩu

| Cách | Lệnh | Khi nào dùng |
|---|---|---|
| **Gõ thẳng** | `--acc user@x.com 'mật-khẩu'` | Tiện, nhưng mật khẩu nằm trong lịch sử shell |
| **Lấy từ `.env`** | `--acc user@x.com` | Chạy lặp lại nhiều lần |
| **Hỏi tại chỗ** | `--acc user@x.com -` | Máy dùng chung — không lưu vết |

Script đặt mật khẩu vào **biến môi trường** của tiến trình con, không truyền qua tham số
dòng lệnh — vì tham số dòng lệnh hiện trong `ps` cho mọi user trên máy đọc được.

---

## Thử ngay không cần hệ thống thật

```bash
./qc.sh --config qc-demo.yaml
```

Chạy trên API giả có 4 bug cài sẵn — thấy đủ cả Đạt lẫn Lỗi.

---

## Chạy lặp lại nhiều lần

Nếu ngày nào cũng chạy cùng một bộ đầu vào, ghi vào `qc.yaml` rồi gọi một lệnh:

```bash
./qc.sh --config qc.yaml
```

Flags và config dùng chung một đường đi — cái nào cũng được.

---

## Tuỳ chọn khác

| Flag | Việc |
|---|---|
| `--api <url>` | Địa chỉ API, nếu khác `--link` |
| `--feature <tên>` | Đặt tên feature (mặc định suy từ `--docs`) |
| `--module <tên>` | Module cho case sinh từ tài liệu |
| `--show-browser` | Hiện cửa sổ Chrome thay vì chạy ẩn |
| `--skip-run` | Chỉ sinh testcase, không chạy |
| `-h, --help` | Hướng dẫn đầy đủ |

---

## Test UI/UX bằng trình duyệt thật

Khi có `--link`, tool mở Chromium thật: dò element, chạy case UI, chụp bằng chứng.
Phần này không bật gì thêm cũng chạy, nhưng có mấy nút đáng biết — ghi trong `qc.yaml`:

```yaml
ui:
  retry: 1              # hỏng thì chạy lại 1 lần, để tách "chập chờn" khỏi "lỗi thật"
  evidence: on-fail     # ảnh chụp khi test hỏng (off | on-fail | always)
  trace: false          # ghi trace từng bước để xem lại
  axe: false            # quét accessibility
  soft_assert: false    # true = sai một bước vẫn chạy hết, thấy mọi lỗi trong 1 lượt
```

Hoặc dùng cờ dòng lệnh, ví dụ:

```bash
uv run qctool run artifacts/login-sso/testcases.yaml \
  --web-url https://dev-qc-portal.datafactory.fit \
  --retry 1 --evidence always --show-browser
```

**Nút "Chạy" bị khoá có đúng không, lỗi JS có hiện ra không, con trỏ có nằm đúng ô
không** — đó là những thứ test API không thấy được. Bộ verb UI/UX kiểm được:
`assert.disabled`, `assert.enabled`, `assert.console_clean`, `assert.no_broken_requests`,
`assert.focused`, `assert.text`, `assert.value`, `assert.attr`, `assert.count`,
`assert.checked`, `assert.axe`, `assert.screenshot`.

Xem lại một case hỏng:

```bash
uv run playwright show-trace artifacts/<feature>/evidence/TC_AUTH_001.trace.zip
```

---

## Đọc kết quả

Sau mỗi lần chạy, trong `artifacts/<feature>/`:

| File | Đọc để biết |
|---|---|
| `runs/<giờ>/report.md` | **Đọc cái này** — tóm tắt, chi tiết theo module, danh sách lỗi, chưa chạy được, bằng chứng |
| `testcases.xlsx` | File testcase 14 cột — **đã điền kết quả vào sẵn** |
| `runs/<giờ>/junit.xml` | Đưa vào CI |
| `runs/<giờ>/results.csv` | Mở Excel, tự làm pivot |
| `evidence/` | Ảnh chụp + trace của test UI, đặt tên theo mã test |
| `ui-map.yaml` | Webapp có những nút/element gì |

Script in sẵn đường dẫn báo cáo ở cuối mỗi lần chạy.

---

## Bốn trạng thái, đừng lẫn

| | Nghĩa | Việc cần làm |
|---|---|---|
| **Đạt** | Chạy xong, đúng | — |
| **Lỗi** | Chạy xong, **sai** → **sản phẩm có bug** | Báo dev |
| **Bị chặn** | **Chưa chạy được** — thiếu dữ liệu/tài khoản/case chưa map | Bổ sung môi trường. **Không phải bug** |
| **Chưa chạy** | Case thủ công, người phải làm theo các bước trong file | Đọc cột Test Steps rồi làm |

Thêm một thứ nữa không phải trạng thái mà là **cảnh báo**: test **chập chờn** (lần
đầu hỏng, chạy lại mới đạt). Nó nằm ở Mục 6 của báo cáo. Đừng bỏ qua — một test lúc
được lúc không là bug, chỉ khác là chưa biết bug của sản phẩm hay của test.

Nếu bạn thấy `Lỗi` mà nguyên nhân là "thiếu tài khoản" — đó là **bug của tool**, báo ngay.

---

## Vì sao OAS là đầu vào quan trọng nhất

Không có nó, case sinh từ tài liệu phải **map** sang hành động cụ thể mới chạy được.
Mà tài liệu viết *"sidebar chỉ hiện module tôi được phép"* — câu đó nói cần kiểm gì,
không nói element nào. Tool giữ nguyên và đánh dấu *chưa map*, rồi báo `Bị chặn`.

Có OAS thì tool sinh thẳng case chạy được: giá trị biên, mã lỗi, ma trận xác thực.

> Lấy spec từ FastAPI:
> ```bash
> python -c "import json,app.main; print(json.dumps(app.main.app.openapi()))" > openapi.json
> ```

---

## LLM tùy chọn cho generation

Mặc định không gọi model. Adapter dùng endpoint Chat Completions tương thích
OpenAI (`<base URL>/chat/completions`), cùng một model cho resolution và exploration
planning. Chỉ hỗ trợ provider/model nhận `response_format: json_object`.

Điền `.env` (gitignored) hoặc export biến môi trường:

```bash
export QCTOOL_LLM_BASE_URL=https://api.openai.com/v1
export QCTOOL_LLM_MODEL='your-model-id'
# QCTOOL_LLM_API_KEY đặt qua .env hoặc secret manager, không commit vào repo.
export QCTOOL_LLM_TIMEOUT_SECONDS=30
uv run qctool all --config qctool.yaml --llm
```

`--llm` bật tường minh; `--no-llm` tắt kể cả khi config/env đã bật. Cũng có thể đặt
`llm.enabled: true` trong YAML, hoặc `QCTOOL_LLM_ENABLED=true` trong env khi YAML
không ghi `llm.enabled`. Chỉ có API key/model không đủ để tự bật LLM.
Python caller có thể dùng `PipelineConfig(llm_enabled=True, ...)`, hoặc truyền
adapter qua `run_pipeline(..., resolution_llm=..., exploration_llm=...)`.

Provider không retry request. Timeout, lỗi HTTP và JSON sai/rỗng được báo có kiểm
soát, không ghi API key/provider body vào lỗi. Proposal/plan vẫn phải qua parser,
validator và applier hiện có; model không được sửa testcase trực tiếp. Chỉ phần
context đã chọn được gửi đi. Xem `generation.json` để biết case unresolved/lỗi
stage; pipeline hoàn tất không có nghĩa coverage đã hoàn tất. Replay offline
không đọc/tạo provider này, kể cả khi env bật LLM.

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
| Nhiều `Lỗi` với `401` | Phiên hết hạn — xoá `artifacts/<feature>/.auth-state.json` rồi chạy lại |
| Nhiều `Lỗi` với `404` | Sai `--api` — thử thêm/bớt `/api/v1` |
| Crawl ra 0 element | Mạng chậm — thử lại; nếu vẫn vậy kiểm tra đăng nhập |
| Nhiều `Bị chặn` | Thiếu OAS — đây là lý do phổ biến nhất |
| Sai mật khẩu | Sửa `.env`, hoặc truyền lại qua `--acc` |
| Case UI báo `Lỗi` vì không tìm thấy element | Nhãn trên trang đã đổi. Chạy lại `uv run qctool crawl <url>` rồi sinh lại testcase |
| Case a11y báo `Bị chặn` với "axe-core" | Máy không ra được Internet — chép `axe.min.js` vào `qctool/execute/` hoặc đặt `QCTOOL_AXE_PATH` |
| Báo cáo có mục "Test chập chờn" | Đọc Mục 6 và 7: trace + ảnh nằm trong `evidence/`, mở bằng `playwright show-trace` |
| Tool tự đăng nhập dù không muốn | Đặt `auth.mode: manual` trong `qc.yaml` — chế độ này không bao giờ tự đăng nhập |
| Đăng nhập hỏng nhưng vẫn muốn chạy case UI khác | Cứ chạy: case cần xác thực báo `Bị chặn`, case còn lại vẫn chạy |

## Authoring agent (nhánh agent-redesign)

```bash
# .env: QCTOOL_LLM_BASE_URL / QCTOOL_LLM_MODEL / QCTOOL_LLM_API_KEY
# Provider phải hỗ trợ OpenAI-compatible tools. Không ghi key trong YAML.
uv run qctool validate --config qctool.agent.example.yaml --llm
uv run qctool run --config qctool.agent.example.yaml --llm
```

Copy cấu hình mẫu và điền docs/OpenAPI/website. Với DeepSeek, có thể đặt
`QCTOOL_LLM_THINKING=disabled` để dùng tool calling không reasoning; không bắt buộc.
`auth.mode: browser` mới cho phép bootstrap login bằng env. `manual` không tự login.
Provisioning mặc định OFF; thao tác ghi cần policy được review.

Agent quan sát ARIA → viết case có source quote → thử action/locator trên context
riêng → nhận lỗi để sửa trong cùng hội thoại. Dry-run **chưa** là Pass: runner mới
kiểm expected. Khi không chạy được, case vẫn manual/blocked và giữ source.

- `ready`: gate + dry-run đủ, expected literal có nguồn.
- `needs_review`: oracle yếu/nonliteral/critic nghi ngờ; vẫn chạy, có nhãn trong report
  và Description. QC ghi quyết định tại sheet Review; 14 cột Test Cases không đổi.
- `manual` / `blocked_env`: chưa chấp nhận chạy tự động; xem `generation.json`.

Dùng `generation.max_intents: 1` hoặc `2` lúc kiểm chứng để giới hạn chi phí; có thể
chọn `generation.intent_ids` từ obligation IDs trong coverage audit. Coverage vẫn
hiển thị toàn bộ nguồn; chạy subset không có nghĩa toàn bộ tài liệu đã covered.
Budget `max_turns`, `max_tokens`, `max_seconds`, `completion_tokens` áp dụng mỗi
intent; có thêm một call thiết kế intent trước authoring. Timeout/call lỗi vẫn tốn
chi phí nếu provider đã xử lý; xem metadata, không giả định usage thiếu là zero.

Artifact: requirements.yaml, app-model.yaml, generation.json, testcases.yaml/xlsx,
results.json/csv, junit.xml, report.md. Knowledge không chứa phiên đăng nhập;
`.auth-state.json` / `.token` là runtime private, không chia sẻ hay commit.

```bash
# Benchmark offline: đọc artifact, không gọi model/browser
uv run python scripts/run_agent_benchmark.py artifacts/<feature>
```

Bộ patch/resolution-loop cũ đã retire; không còn flag chạy nhánh legacy.

### Xem lại agent và Playwright đã làm gì

| Muốn xem | Mở file |
|---|---|
| Agent gọi tool nào, lỗi gì, tốn bao nhiêu token | `generation.json` → `agent_history[i].history`, `provider_attempts` |
| Các bước của testcase | `testcases.yaml` hoặc `testcases.xlsx` |
| Playwright chạy từng bước ra sao | `runs/<thời gian>/results.json`, `report.md` |
| Xem lại trực quan (DOM, mạng, console) | `uv run playwright show-trace evidence/<MÃ>.trace.zip` |

Bật trace trong config: `ui: {evidence: always, trace: true}`. Case có điền mật khẩu
hoặc bắt request đăng nhập **không** có trace/ảnh — tool tắt có chủ ý để file không chứa
mật khẩu/token. Kết quả từng bước của các case đó vẫn có trong `results.json`.
Trace chứa dữ liệu phiên: không chia sẻ, không commit.

Ví dụ đầy đủ: `samples/customer_e2e_test_1/` + `qctool.customer_e2e_test_1.e2e.yaml`
(11 AC: đăng nhập, mua hàng, đặt lịch — dừng trước bước tạo dữ liệu).
