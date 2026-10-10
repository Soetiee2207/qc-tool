# qc-tool

Công cụ tự động hoá QC: đưa **tài liệu yêu cầu** + **OpenAPI spec** + **link webapp**,
nhận lại **testcase**, **kết quả chạy**, và **báo cáo**.

Tool dùng chung, không gắn với một webapp cụ thể. Đầu vào thiếu cái nào thì chặng dùng
cái đó bị bỏ qua và tool nói rõ hệ quả.

```bash
uv sync && uv run playwright install chromium
uv run qctool demo             # thử ngay trên API giả
uv run qctool run salonhub     # chạy mọi feature của projects/salonhub/
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
qctool init shop/login && qctool check shop
qctool run shop --login --only 001-1   # một feature, một AC — giới hạn chi phí
```

Đặt tài liệu vào `projects/shop/login/`, điền web/api trong `projects/shop/project.yaml` và `QCTOOL_LLM_*` trong `.env` trước. Xem [hướng dẫn](HUONG-DAN.md) và [kết quả kiểm chứng giới hạn](docs/findings/agent-redesign.md).
Không còn patch engine/legacy execution flag. API-only generation vẫn deterministic.

### V2 — kết quả kiểm chứng (2026-10-09)

Trên SalonHub thật (role Customer, DeepSeek, Chromium):

| Bộ tài liệu | Executable | Pass | Fail |
|---|---|---|---|
| customer (7 AC) | 5/7 | 5 | 0 |
| customer_e2e_test_1 (11 AC: đăng nhập, mua hàng, đặt lịch — read-only) | 9/11 | 9 | 0 |

_Số liệu lịch sử, đo trên bộ tài liệu cũ; từ 2026-10-10 thay bằng 11 feature trong `projects/salonhub/`, chưa đo lại._

Trước V2: 3–4/7 với ~330k token. Case không chạy được giữ `Not Executed` kèm lý do,
không bao giờ tính là Pass. Chi tiết, giới hạn và lỗi đã sửa:
[docs/findings/agent-redesign.md](docs/findings/agent-redesign.md).

```bash
qctool run salonhub --auth     # timeout/thinking của LLM đặt trong .env
```

**Xem bằng chứng:** `<feature>/artifacts/3-generate/generation.json` (agent gọi tool nào),
`5-execute/results.json` + `6-report/report.md` (từng bước Playwright), `5-execute/evidence/*.trace.zip`
(`uv run playwright show-trace <file>`). Case đăng nhập không có trace — cố ý, vì trace
sẽ chứa mật khẩu thật.

**Giới hạn hiện tại:** chưa test bước ghi dữ liệu (đặt hàng, xác nhận lịch) — cần mutation
policy; DeepSeek đôi khi timeout; kết quả từng case dao động giữa các lượt.


## Cài đặt

Cần **Python ≥ 3.12** và [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run playwright install chromium    # cho test UI/UX
cp .env.example .env                  # rồi điền tài khoản + LLM key (không commit .env)
source .venv/bin/activate             # để gõ `qctool …` thay vì `uv run qctool …`
```

## Dùng

```bash
qctool demo                            # thử ngay trên API giả — không cần hệ thống thật
qctool init salonhub/loyalty           # tạo feature mới
qctool check salonhub                  # kiểm tra mọi feature, không gọi model/browser/API
qctool run salonhub                    # chạy MỌI feature của project
qctool run salonhub --auth             # chỉ chạy feature auth
qctool trace salonhub TC_AUTH_001      # xem lại từng bước của một case
qctool ui                              # giao diện web (http://127.0.0.1:8080)
qctool step …                          # từng chặng: ingest | generate | exec | crawl
```

**Project = một sản phẩm, feature = một phần của nó.** Tài liệu, cấu hình và kết quả của
feature nằm chung một thư mục:

```
projects/salonhub/
  project.yaml              # chung: web, api, llm, account.role, timeout, ui
  auth/
    urd.md srs.md openapi.yaml
    qctool.yaml             # riêng feature: account.login_for, ghi đè
    artifacts/              # 1-ingest 2-crawl 3-generate 4-render 5-execute 6-report + run.json
```

Mọi khoá khác có mặc định (tài liệu/OpenAPI cạnh `qctool.yaml`, feature/module = tên thư
mục, budget agent 14 lượt/90k token/480s mỗi AC). Bảng mặc định, cờ `run` (`--only`,
`--no-llm`, `--skip-run`, `--show-browser`, `--trace-sensitive`) và xử lý sự cố:
[HUONG-DAN.md](HUONG-DAN.md).

Lệnh `run` dùng chung `run_pipeline()` với web UI: ingest, crawl (đăng nhập +
`app-model.yaml`), generation bằng agent, Chromium/API execution và report. Terminal hiển
thị tiến trình `[ingest]`, `[crawl]`, `[generate]`, `[agent]`, `[run]`, `[report]`; tiến
trình được redact và ghi vào `pipeline.log`. `summary.json` chứa số liệu, `generation.json`
giữ lịch sử agent. Case manual/unresolved vẫn nằm trong testcase YAML/XLSX và report,
không bao giờ thành Pass.

**Profile duy nhất: `agent`.** Mỗi acceptance criterion là một intent; agent viết một
testcase cho nó trong một hội thoại có feedback. Giới hạn chi phí: `--only`,
`generation.max_intents`, `generation.budget`.

**LLM chỉ bật tường minh** (`llm: true` hoặc `--llm`). Có API key không tự bật model.
Key/model/base URL chỉ ở `.env` (`QCTOOL_LLM_*`).

**`auth.mode: manual`** là mặc định khi không có `account`; credential trong env không
tự đăng nhập.

**Provisioning mặc định OFF.** `provisioning.enabled: true` chỉ bật gate; engine vẫn đòi
exact operation, reviewed rule, allowed test environment/origin và verification phù hợp.
Credentials/facts khai báo không tự chứng minh trạng thái backend.

Preparation AVAILABLE được dùng lại trong cùng run chỉ khi toàn bộ data/trust identity
khớp (fixture, aliases, facts, assurance, credentials/config, rules, policy, contract,
backend, environment). Cache runtime tối đa 128 entries, độ tươi 300 giây, không chia sẻ
giữa runs.

`check` chỉ kiểm tra config, docs ingest được, OpenAPI đọc được và provider configuration
nếu bật LLM. Không gọi model/browser/API, không ghi artifacts.

#### Exit codes của `run`

| Code | Ý nghĩa |
| --- | --- |
| 0 | Generation thành công và toàn bộ testcase đã chạy Pass |
| 1 | Có execution Fail; generation status vẫn hiển thị riêng |
| 2 | Config/preflight/pipeline/artifact error |
| 3 | Generation/coverage incomplete hoặc unassessable, không có execution Fail |
| 4 | Generation hoàn tất nhưng execution bị Blocked/chưa chạy/skip |

`generation_success` và `pipeline_ok` là hai trường riêng. Coverage không thay cho runtime
Pass; testcase chưa chạy không có Pass. Flaky Pass vẫn có cờ/count riêng.

`qctool demo` chạy trên `tests/mock_server.py` (4 bug API + 4 bug giao diện cài sẵn).
Kết quả mong đợi: `54 test · 29 đạt · 15 lỗi · 10 bị chặn`.

## Kết quả

Mỗi lượt chạy ghi vào `<feature>/artifacts/`, mỗi bước một thư mục:

| Đường dẫn | Đọc để biết |
|---|---|
| `run.json` | Bước nào xong / đang chạy / bỏ qua / **lỗi**; file sinh ra; lỗi trỏ tới `error.log` |
| `events.jsonl` | Dòng thời gian `{t, stage, level, message}` — UI đọc trực tiếp |
| `1-ingest/requirements.yaml` | Requirement đọc được từ tài liệu |
| `2-crawl/app-model.yaml` | Trang agent đã thấy + macro đăng nhập (không chứa mật khẩu) |
| `3-generate/generation.json`, `testcases.yaml` | Agent gọi tool nào, lỗi gate/dry-run, token · bước của từng case |
| `4-render/testcases.xlsx` | Testcase 14 cột, **đã điền kết quả vào sẵn** |
| `5-execute/` | `results.json/csv`, `junit.xml`, `evidence/` (ảnh + trace theo mã test) |
| `6-report/report.md` | **Báo cáo cho người đọc** |
| `<bước>/stage.log`, `<bước>/error.log` | Log riêng của bước · traceback khi bước đó hỏng |

`artifacts/` là output sinh lại được — không sửa tay, không commit (gitignored).

Mỗi lượt `qctool run <project>` còn ghi `projects/<project>/summary/<YYYY-MM-DD_HH-MM-SS>/summary.md`:
số liệu tổng, theo feature, danh sách Fail/Bị chặn và **toàn bộ testcase**, kèm bản sao report/evidence của
lượt đó (artifacts thì bị ghi đè). `summary/README.md` liệt kê mọi lượt chạy.

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
qctool trace salonhub TC_AUTH_001
```

`auth.mode: manual` nghĩa là **không tự đăng nhập**, kể cả khi `.env` có tài khoản. Chỉ
`browser` mới đăng nhập qua form của IdP.

## Cấu trúc repo

| Đường dẫn | Là gì |
|---|---|
| `qctool/cli.py`, `cli_run.py` | Lệnh `qctool …` |
| `qctool/config.py` | `.env` + mở rộng `qctool.yaml` dạng gọn (mặc định, `account`) |
| `qctool/pipeline.py` | `run_pipeline()` — đường đi chung của CLI, web UI, CI |
| `qctool/core/` | Testcase IR (`testcase.py`, ACTION_SPECS), model, validate, coverage, executability |
| `qctool/ingest/` `generate/` `execute/` `render/` `report/` | Bốn chặng |
| `qctool/agent/` | Authoring agent: loop, tools, gate, safety, LLM provider |
| `qctool/data/` | Test data: fixtures, acquisition, verification, provisioning, capture |
| `qctool/ui/` `web/` | Crawl webapp · giao diện web |
| `projects/<project>/<feature>/` | Tài liệu đầu vào + `qctool.yaml` + `artifacts/` của từng feature |
| `templates/` | Template testcase 14 cột (sinh từ script) · OpenAPI · báo cáo |
| `tests/` | Test; `mock_server.py` = API + trang HTML giả có bug cài sẵn |
| `docs/` | Brainstorm, findings, tracking |
| `scripts/` | Sinh template testcase, validate OpenAPI |
| `qctool/artifacts.py` | Bố cục artifacts theo bước + `run.json`/`events.jsonl` |
| `qctool/summary.py` | Báo cáo tổng hợp mỗi lượt chạy project → `projects/<p>/summary/<ngày_giờ>/` |

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
