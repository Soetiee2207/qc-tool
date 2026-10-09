# qc-tool

Công cụ tự động hoá QC: đưa **tài liệu yêu cầu** + **OpenAPI spec** + **link webapp**,
nhận lại **testcase**, **kết quả chạy**, và **báo cáo**.

Tool dùng chung, không gắn với một webapp cụ thể. Đầu vào thiếu cái nào thì chặng dùng
cái đó bị bỏ qua và tool nói rõ hệ quả.

```bash
uv sync && uv run playwright install chromium
uv run qctool serve            # giao diện web — bấm là chạy
```

## Bốn chặng

```
tài liệu ─┐
OpenAPI  ─┼─► requirements.yaml ─► testcases.yaml ─► runner ─► results.json
          │         (ingest)          (generate)      (execute)   results.csv
          │                              │                        junit.xml
          ▼                              ▼                        report.md
       webapp ◄──── ui-map.yaml      testcases.xlsx ◄─────────────────┘
      (crawl)                        (14 cột)         ghi kết quả ngược
```

| Chặng | Làm gì | Module |
|---|---|---|
| **Ingest** | Tài liệu markdown → requirement có ID ổn định + trích dẫn nguồn | `qctool/ingest/` |
| **Generate** | Requirement và/hoặc OpenAPI → testcase IR, qua validator | `qctool/generate/` |
| **Execute** | Chạy testcase: HTTP thật, hoặc Chromium thật cho case UI/UX | `qctool/execute/` |
| **Report** | `report.md` + `junit.xml` + `results.csv`, ghi kết quả ngược vào `.xlsx` | `qctool/report/`, `qctool/render/` |

Điểm quan trọng nhất của luồng dữ liệu: file `.xlsx` 14 cột là **bản ghi hai pha** — sinh
ra một lần, rồi chạy điền kết quả vào chính file đó (4 cột runtime). QC không phải đối
chiếu hai file.

**Agent authoring:** LLM dùng tools để quan sát ARIA, viết testcase có source quote,
nhận lỗi và sửa trong cùng session. Gate giữ schema/safety/citation; dry-run chỉ kiểm
action/locator, không cho model đọc actual assertion để sửa expected theo sản phẩm.
Runner mới quyết định Pass/Fail. Weak oracle là `needs_review`, không generation success.

```bash
uv run qctool validate --config qc_config/qctool.agent.example.yaml --llm
uv run qctool run --config qc_config/qctool.agent.example.yaml --llm
```

Điền docs/OpenAPI/URL và provider env trước; bắt đầu với `generation.max_intents: 1`
hoặc `2`. Xem [hướng dẫn](HUONG-DAN.md) và [kết quả kiểm chứng giới hạn](docs/findings/agent-redesign.md).
Không còn patch engine/legacy execution flag. API-only generation vẫn deterministic.

### V2 — kết quả kiểm chứng (2026-10-09)

Trên SalonHub thật (role Customer, DeepSeek, Chromium):

| Bộ tài liệu | Executable | Pass | Fail |
|---|---|---|---|
| `samples/customer` (7 AC) | 5/7 | 5 | 0 |
| `samples/customer_e2e_test_1` (11 AC: đăng nhập, mua hàng, đặt lịch — read-only) | 9/11 | 9 | 0 |

Trước V2: 3–4/7 với ~330k token. Case không chạy được giữ `Not Executed` kèm lý do,
không bao giờ tính là Pass. Chi tiết, giới hạn và lỗi đã sửa:
[docs/findings/agent-redesign.md](docs/findings/agent-redesign.md).

```bash
QCTOOL_LLM_TIMEOUT_SECONDS=90 QCTOOL_LLM_THINKING=disabled \
  uv run qctool run --config qc_config/qctool.customer_e2e_test_1.e2e.yaml --llm
```

**Xem bằng chứng:** `artifacts/<feature>/generation.json` (agent gọi tool nào),
`runs/<t>/results.json` + `report.md` (từng bước Playwright), `evidence/*.trace.zip`
(`uv run playwright show-trace <file>`). Case đăng nhập không có trace — cố ý, vì trace
sẽ chứa mật khẩu thật.

**Giới hạn hiện tại:** chưa test bước ghi dữ liệu (đặt hàng, xác nhận lịch) — cần mutation
policy; DeepSeek đôi khi timeout; kết quả từng case dao động giữa các lượt.


## Cài đặt

Cần **Python ≥ 3.12** và [uv](https://docs.astral.sh/uv/). Playwright + Chromium chỉ cần
khi chạy test UI/UX.

```bash
uv sync
uv run playwright install chromium    # chỉ cần cho test UI/UX
cp .env.example .env                  # rồi điền tài khoản, token (không commit .env)
```

## Dùng

### Quick-start: một lệnh cho toàn bộ QC

```bash
uv run qctool validate --docs ./docs --openapi ./openapi.yaml
uv run qctool run --docs ./docs --openapi ./openapi.yaml \
  --url https://app.example.com --out artifacts/run
```

Thay URL/paths mẫu bằng inputs của bạn. `docs` chứa `urd.md`, `srs.md`;
luồng bổ sung nằm trong `srs/*flow*.md` theo định dạng tool hỗ trợ. OpenAPI là tùy chọn nếu workflow không có
API contract. Không cần tạo testcase YAML trước.

Hoặc copy [qc_config/qctool.run.example.yaml](qc_config/qctool.run.example.yaml) thành `qctool.yaml`,
điền inputs và chạy:

```bash
uv run qctool run --config qctool.yaml
```

CLI dùng chung `run_pipeline()` cho ingest, crawl (đăng nhập + `app-model.yaml`),
generation bằng agent, Chromium/API execution và report. Terminal hiển thị tiến trình
`[ingest]`, `[crawl]`, `[generate]`, `[agent]`, `[run]`, `[report]`; tiến trình được redact
và ghi vào `pipeline.log`. `summary.json` chứa số liệu, `generation.json` giữ lịch sử
agent (tool đã gọi, lỗi gate/dry-run, token). Case manual/unresolved vẫn nằm trong
testcase YAML/XLSX và report, không bao giờ thành Pass.

**Profile duy nhất: `agent`.** Mỗi acceptance criterion là một intent; agent viết một
testcase cho nó trong một hội thoại có feedback. `generation.profile: business`/`legacy`
trong config cũ chỉ là alias của `agent` — không còn nhánh legacy, không còn
`legacy-testcases.yaml`. Giới hạn chi phí: `generation.max_intents`, `intent_ids`,
`budget` (turns/tokens/giây mỗi intent).

Preparation AVAILABLE được dùng lại trong cùng run chỉ khi toàn bộ data/trust
identity khớp: fixture, aliases, facts, assurance, credentials/config, reviewed rules,
policy, contract, backend và environment. Cache runtime tối đa 128 entries, độ tươi
300 giây, không đọc proof từ JSON hoặc chia sẻ mặc định giữa runs. Audit ghi
`preparation_mode: EXECUTED/REUSED`, `preparation_identity`, `reused_from_testcase`
và `executed_calls`; receipt cũ chỉ là lịch sử proof, không phải call mới.

**LLM mặc định OFF.** Có API key không tự bật model. Bật qua `llm.enabled: true`
hoặc `--llm`, sau khi cấu hình `QCTOOL_LLM_BASE_URL`, `QCTOOL_LLM_MODEL`,
`QCTOOL_LLM_API_KEY` và tùy chọn `QCTOOL_LLM_TIMEOUT_SECONDS`. Không ghi key vào
YAML; dùng env/secrets. `--no-llm` ghi đè cấu hình bật.

**Provisioning mặc định OFF.** `provisioning.enabled: true` hoặc
`--allow-provisioning --test-environment test` chỉ bật gate; engine vẫn đòi exact
operation, reviewed rule, allowed test environment/origin và verification phù hợp.
Không có rule hợp lệ thì không tạo dữ liệu. Fixtures đi qua `test_fixtures`, giá trị
qua env; credentials/facts khai báo không tự chứng minh trạng thái backend.

`auth.mode: manual` là mặc định của primary CLI; có credentials trong env không
tự đăng nhập. Muốn bootstrap login phải chọn mode trong config rõ ràng.

`validate` chỉ kiểm tra config, docs có thể ingest, OpenAPI đọc được bằng loader
hiện có và provider configuration nếu bật LLM. Không gọi model/browser/API,
không ghi artifacts, không chứng minh coverage/account/website hoạt động và không
phải validator đầy đủ mọi tính năng chuẩn OpenAPI.

Artifacts: `requirements.yaml`, `app-model.yaml`, `testcases.yaml`,
`testcases.xlsx`, `generation.json`, `summary.json`, `pipeline.log`; execution
reports `results.json`, `results.csv`, `junit.xml`, `report.md` dưới `runs/<timestamp>/`.
Evidence/trace giữ policy và secret protection hiện có. Xem `summary.json.artifacts`
để lấy đường dẫn chính xác. `--out` chọn thư mục mới cho mỗi run nếu cần giữ lịch sử.

#### Exit codes của primary `run`

| Code | Ý nghĩa |
| --- | --- |
| 0 | Generation thành công và toàn bộ testcase đã chạy Pass |
| 1 | Có execution Fail; generation status vẫn hiển thị riêng |
| 2 | Config/preflight/pipeline/artifact error |
| 3 | Generation/coverage incomplete hoặc unassessable, không có execution Fail |
| 4 | Generation hoàn tất nhưng execution bị Blocked/chưa chạy/skip |

`generation_success` và `pipeline_ok` là hai trường riêng. Coverage không thay
cho runtime Pass; testcase chưa chạy không có Pass. Flaky Pass vẫn có cờ/count
riêng trong summary và reports. Blocker resolution không thay đổi status runner:
manual testcase có thể là `Not Executed` với reason `MISSING_FIXTURE`.

Tương thích: `qctool run testcases.yaml --base-url URL --web-url URL` vẫn chạy YAML
đã có; `qctool all` vẫn dùng hành vi/exit codes cũ. Không trộn testcase positional
với `--docs/--config/--openapi/--url` của primary mode.

### 1. Cả pipeline bằng một lệnh

```bash
uv run qctool all --config qctool.yaml
```

`qc_config/qctool.example.yaml` là mẫu đầy đủ, chú thích từng khoá. Không cần file cấu hình thì
truyền thẳng tham số:

```bash
uv run qctool all --openapi ./openapi.yaml --feature login-sso --module AUTH \
                  --base-url https://dev.example.com --token "$TOKEN"
```

Bốn thứ cần đưa, đưa được cái nào hay cái đó:

| Đầu vào | Flag | Có thì được gì |
|---|---|---|
| Tài liệu (`urd.md`, `srs.md`) | `--docs-dir` | Case từ acceptance criteria + NFR |
| OpenAPI spec | `--openapi` | Case kỹ thuật: biên, mã lỗi, ma trận xác thực |
| Link webapp | `--web-url` | Mở Chromium thật: dò element, chạy case UI, chụp bằng chứng |
| Tài khoản / token | `--username` `--password` `--token` | Case cần xác thực chạy được |

### 2. Giao diện web

```bash
uv run qctool serve            # http://127.0.0.1:8080
```

Bí mật nhập trên giao diện **không được lưu lại**. CLI, web UI và CI dùng chung một hàm
`qctool/pipeline.py::run_pipeline()` — không có logic nào chỉ tồn tại trong giao diện.

### 3. Từng chặng, khi cần kiểm soát chi tiết

```bash
uv run qctool ingest   <thư-mục-tài-liệu> --feature login-sso
uv run qctool generate --requirements artifacts/login-sso/requirements.yaml \
                       --openapi ./openapi.yaml \
                       --xlsx artifacts/login-sso/testcases.xlsx
uv run qctool run      artifacts/login-sso/testcases.yaml \
                       --base-url https://dev.example.com --token "$TOKEN" \
                       --xlsx artifacts/login-sso/testcases.xlsx
uv run qctool crawl    https://dev.example.com --out artifacts/login-sso/ui-map.yaml
```

### 4. Thử toàn bộ, không cần hệ thống thật

API giả trong `tests/mock_server.py` có **4 bug API + 4 bug giao diện cài sẵn**, nên một
lượt chạy thấy đủ cả Đạt lẫn Lỗi:

```bash
uv run python -m tests.mock_server --port 8099 &
uv run qctool all --openapi samples/openapi/task-manager-sample.yaml \
                  --feature sample --module SAMPLE \
                  --base-url http://127.0.0.1:8099/api/v1 --token fake
```

Kết quả mong đợi: `54 test · 29 đạt · 15 lỗi · 10 bị chặn`. Hoặc gọn hơn bằng script:

```bash
./qc.sh --config qc_config/qc-demo.yaml
```

`./qc.sh` là lớp bọc quanh CLI cho người dùng cuối (`--docs --oas --link --acc`), có sẵn
ba cách đưa mật khẩu (gõ thẳng / lấy từ `.env` / hỏi tại chỗ). Chi tiết: `HUONG-DAN.md`.

## Kết quả

Mỗi lượt chạy tạo `artifacts/<feature>/`:

| File | Đọc để biết |
|---|---|
| `runs/<giờ>/report.md` | **Đọc cái này** — tóm tắt, theo module, danh sách lỗi, chưa chạy được, bằng chứng |
| `testcases.xlsx` | Testcase 14 cột, **đã điền kết quả vào sẵn** |
| `runs/<giờ>/junit.xml` | Đưa vào CI |
| `runs/<giờ>/results.csv` | Mở Excel, tự làm pivot |
| `evidence/` | Ảnh chụp + trace của test UI, đặt tên theo mã test |
| `app-model.yaml` | Trang agent đã thấy + macro đăng nhập (không chứa mật khẩu) |
| `generation.json` | Agent đã gọi tool nào, sửa lỗi gì, tốn bao nhiêu token |

`artifacts/` là output sinh lại được — không sửa tay, không commit.

## Bốn trạng thái, đừng lẫn

| Trạng thái | Nghĩa | Tuyệt đối không dùng khi |
|---|---|---|
| `Pass` | Đã chạy, đúng như mong đợi | Case chưa chạy, còn bước chưa map, hoặc chỉ đạt nhờ chạy lại |
| `Fail` | Đã chạy, **sai** → **sản phẩm có lỗi** | Thiếu môi trường, case chưa map, hoặc lỗi do tool |
| `Blocked` | **Chưa chạy được**: cần tài khoản/dữ liệu/cách map/axe-core | Sản phẩm thật sự trả sai |
| `Not Executed` | Chưa tới lượt (gồm case thủ công) | — |

Trạng thái thứ năm không phải kết quả mà là **dấu vết**: case đạt ở lần chạy lại mang cờ
`flaky`. Nó vẫn tính `Pass` về số liệu nhưng báo cáo nêu riêng ở Mục 6 — một test lúc được
lúc không là vấn đề, không phải bằng chứng chất lượng.

Báo cáo QC chỉ có giá trị khi mỗi con số đều đúng, nên:

- Case cần "tài khoản không có quyền" để kiểm 403 mà chỉ có một tài khoản → `Blocked` kèm
  lý do, **không** `Fail`. Ghi `Fail` là gửi dev đi tìm bug không tồn tại.
- Không nạp được axe-core vì mạng chập → ném `NeedsEnvironment` → `Blocked`. Lỗi của tool
  không phải câu trả lời của sản phẩm.
- Tỉ lệ đạt luôn ghi kèm mẫu số + số test chưa chạy: `Tỉ lệ đạt 66% (29/44) · 10 chưa chạy`.

## Testcase — template 14 cột

`templates/testcase/testcase-template.xlsx` sinh tự động từ
`scripts/build_testcase_template.py`. **Không sửa tay file `.xlsx`** — lần sinh sau sẽ ghi
đè; sửa script rồi chạy lại:

```bash
uv run scripts/build_testcase_template.py
```

- Một dòng = một testcase, không phải một bước. Các bước nằm chung ô `Test Steps`, đánh số.
- ID: `TC_{MODULE}_{NNN}`.
- 10 cột tool sinh (xanh) · 4 cột điền khi chạy (cam): `Actual Result`, `Status`,
  `Environment`, `Executed By / Date`.
- Có dropdown `Pass / Fail / Blocked / Not Executed`, tô màu theo Status, lọc tự động.
- Đổi cấu trúc template là phá vỡ file người dùng đang dùng — phải ghi changelog và báo trước.

## UI/UX test bằng trình duyệt thật

Case UI chạy trên Chromium thật: mỗi testcase một browser context riêng, assert dùng
`expect()` tự chờ thay vì đọc DOM một lần, ưu tiên selector `data-testid`.

Bộ verb UI/UX: `assert.disabled` `assert.enabled` `assert.console_clean`
`assert.no_broken_requests` `assert.focused` `assert.text` `assert.value` `assert.attr`
`assert.count` `assert.checked` `assert.axe` `assert.screenshot`.

```yaml
ui:
  retry: 1              # hỏng thì chạy lại 1 lần, để tách "chập chờn" khỏi "lỗi thật"
  evidence: on-fail     # ảnh chụp khi test hỏng (off | on-fail | always)
  trace: false          # ghi trace từng bước để xem lại
  axe: false            # quét accessibility
  soft_assert: false    # true = sai một bước vẫn chạy hết, thấy mọi lỗi trong 1 lượt
```

Xem lại một case hỏng:

```bash
uv run playwright show-trace artifacts/<feature>/evidence/TC_AUTH_001.trace.zip
```

`auth.mode: manual` nghĩa là **không tự đăng nhập**, kể cả khi `.env` có tài khoản. Chỉ
`browser` mới đăng nhập qua form của IdP.

## Cấu trúc repo

| Đường dẫn | Là gì |
|---|---|
| `qctool/` | Mã nguồn — `ingest/` `generate/` `execute/` `ui/` `report/` `render/` `web/` `pipeline.py` |
| `templates/testcase/` | Template 14 cột — tool ghi ra, sinh từ script |
| `templates/api/` | Template OpenAPI — người điền, tool đọc vào để ground |
| `templates/report/` | Template báo cáo |
| `samples/` | Dữ liệu **hư cấu** để dev/test — không phải hệ thống thật |
| `tests/mock_server.py` | API + trang HTML giả, có bug cài sẵn |
| `docs/` | Brainstorm, findings, tracking |
| `scripts/` | Sinh template, validate OpenAPI |
| `artifacts/` | Output mỗi lần chạy — gitignored |
| `docs/tracking/milestones.md` | Trạng thái M01–M07 |
| `HUONG-DAN.md` | Hướng dẫn cho người dùng cuối |

Nguyên tắc: **OpenAPI là nguồn ground cho API.** Endpoint/field không có trong OpenAPI hoặc
tài liệu thì tool không được bịa — thà bỏ sót còn hơn sinh case gọi endpoint không tồn tại.
Case prose mà agent không viết được qua gate + dry-run thì giữ dạng `perform.unmapped`,
đánh dấu *chưa map* / thủ công — không được đoán ra selector hay URL.

## Phát triển

```bash
uv run python -m pytest tests/ -q -m "not playwright"   # nhanh, không cần trình duyệt
uv run python -m pytest tests/ -q                       # đầy đủ, mở Chromium thật
uv run scripts/validate_openapi.py <file.yaml>          # kiểm spec trước khi dùng
```

Góp ý cho coding agent: đọc `AGENTS.md` trước khi sửa — có danh sách lỗi đã gặp thật và
luật sinh ra để chặn chúng tái diễn.

## Giới hạn hiện tại

| Chưa có | Ảnh hưởng |
|---|---|
| Bảng traceability đầy đủ | Mới có cảnh báo requirement thiếu test |
| `.docx` / `.pdf` | Tài liệu phải là markdown |
| Tài khoản thiếu quyền | Case 403/forbidden sẽ `Blocked` |
| UI map nhiều trang | Dò được nhiều trang, chưa bấm sâu vào menu |
| Chạy song song | Chạy lần lượt, bộ test lớn sẽ chậm |
| Upload file / iframe / dialog hệ thống | Chưa có verb cho nhóm này |
| Bước ghi dữ liệu (đặt hàng, xác nhận lịch…) | Agent không dry-run được thao tác ghi → case giữ thủ công; cần mutation policy đã review |
| LLM ổn định | DeepSeek có lúc timeout/hết budget → vài case `Not Executed`; kết quả từng case dao động giữa các lượt |

Xem `docs/tracking/todo.md` và `docs/tracking/milestones.md` để biết đang làm gì tiếp.
