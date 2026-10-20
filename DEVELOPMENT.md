# qc-tool — tài liệu phát triển

Tài liệu cho **người sẽ sửa/mở rộng tool**: hiểu dự án, cấu trúc, các hàm quan trọng và cách
chạy — mà không phải đọc lại toàn bộ ~25.000 dòng code.

| Bạn cần | Đọc |
|---|---|
| Dùng tool (QC, người chạy test) | [`HUONG-DAN.md`](HUONG-DAN.md) |
| Luật bắt buộc khi sửa code (cho người và coding agent) | [`AGENTS.md`](AGENTS.md) |
| Hiểu code để sửa/mở rộng | **file này** |
| Vì sao thiết kế như vậy, lỗi đã gặp | `docs/brainstorms/`, `docs/findings/` |
| Tiến độ, việc còn lại | `docs/tracking/` (`milestones.md`, `todo.md`) |

> Đọc nhanh 15 phút: §1 → §3 → §5 → §7. Phần còn lại là tra cứu khi cần.
> Tham chiếu code ghi theo `file::hàm` (không ghi số dòng vì số dòng trôi theo thời gian).

---

## Mục lục

1. [Tool làm gì, nguyên tắc cốt lõi](#1-tool-làm-gì-nguyên-tắc-cốt-lõi)
2. [Cài đặt và chạy lần đầu](#2-cài-đặt-và-chạy-lần-đầu)
3. [Bản đồ repo](#3-bản-đồ-repo)
4. [Khái niệm cần nắm](#4-khái-niệm-cần-nắm)
5. [Một lượt `qctool run` đi qua những đâu](#5-một-lượt-qctool-run-đi-qua-những-đâu)
6. [Từng package: file và hàm quan trọng](#6-từng-package-file-và-hàm-quan-trọng)
7. [Authoring agent — trái tim của tool](#7-authoring-agent--trái-tim-của-tool)
8. [Runner và bốn trạng thái kết quả](#8-runner-và-bốn-trạng-thái-kết-quả)
9. [Cấu hình: `project.yaml`, `qctool.yaml`, `.env`](#9-cấu-hình-projectyaml-qctoolyaml-env)
10. [Artifacts và cách truy vết một lượt chạy](#10-artifacts-và-cách-truy-vết-một-lượt-chạy)
11. [Web UI và chế độ chat](#11-web-ui-và-chế-độ-chat)
12. [Lệnh hay dùng và mã thoát](#12-lệnh-hay-dùng-và-mã-thoát)
13. [Test](#13-test)
14. [Công thức cho các thay đổi thường gặp](#14-công-thức-cho-các-thay-đổi-thường-gặp)
15. [Giới hạn đã biết và cạm bẫy](#15-giới-hạn-đã-biết-và-cạm-bẫy)

---

## 1. Tool làm gì, nguyên tắc cốt lõi

**Đầu vào:** tài liệu yêu cầu (`urd.md`, `srs.md` — AC dạng Given/When/Then) · link webapp ·
(tuỳ chọn) OpenAPI · tài khoản test trong `.env`.

**Đầu ra:** `testcases.xlsx` đúng template 14 cột của team → chạy trên trình duyệt/HTTP thật →
ghi kết quả **ngược vào chính file đó** + `report.md`, `junit.xml`, `results.csv/json`, ảnh,
Playwright trace.

Hai đường sinh testcase:

| Nguồn | Ai sinh | `generated_by` | Ghi chú |
|---|---|---|---|
| OpenAPI | Generator tất định (`generate/from_openapi.py`) | `engine` | Không cần LLM. EP, BVA, ma trận auth, lỗi validate |
| Văn xuôi (AC) | Authoring agent: LLM + trình duyệt thật (`agent/`) | `llm` | Cần LLM + `web`. Không được thì case thành **thủ công** |

**Năm nguyên tắc chi phối mọi quyết định thiết kế** (chi tiết và lịch sử lỗi ở `AGENTS.md`):

1. **Không nói dối.** `Pass` / `Fail` / `Blocked` / `Not Executed` có nghĩa chặt (§8). Thiếu môi
   trường là `Blocked`, không bao giờ `Fail`. Đạt ở lần chạy lại là `flaky`, không phải `Pass` sạch.
2. **Không đoán.** Agent không viết được case qua gate + dry-run → case giữ dạng thủ công
   (`perform.unmapped`). Không bịa selector, URL, endpoint, mật khẩu.
3. **Vocabulary đóng.** Mọi bước là một `action` trong `ACTION_SPECS` (`core/testcase.py`). Verb lạ bị
   validator chặn. LLM không viết code Playwright tự do.
4. **Tài liệu là chân lý.** Expected phải trích nguyên văn từ tài liệu (citation). Quan sát trên web
   **không** được sửa expected; dry-run không trả giá trị thực tế của assertion cho model.
5. **Mặc định chỉ đọc.** Request/thao tác ghi dữ liệu bị chặn trừ khi bật `mode: write` + xác nhận.
   Bí mật chỉ ở `.env`, không vào YAML, log, transcript chat hay prompt của model.

**Một đường đi duy nhất:** CLI, web UI và CI đều gọi `pipeline.py::run_pipeline()`. Không có logic
nào chỉ tồn tại trong giao diện.

---

## 2. Cài đặt và chạy lần đầu

```bash
uv sync                                  # Python ≥ 3.12; phụ thuộc: openpyxl, playwright, pyyaml
uv run playwright install chromium
cp .env.example .env                     # điền QCTOOL_LLM_* (và tài khoản test nếu cần)

uv run qctool demo                       # tự bật tests/mock_server.py (cổng 8099) + chạy projects/demo
uv run python -m pytest tests/ -q -m "not playwright"   # ~30 giây, không cần trình duyệt
uv run python -m pytest tests/ -q                        # đủ bộ, có mở Chromium thật
```

LLM: bất kỳ provider **OpenAI-compatible có tool calling** (đang dùng DeepSeek). Kiểm nhanh:
`qctool ui` → 📎 Dữ liệu đầu vào → mục 4 → **Kiểm tra**.

Không có `uv`: `python -m venv .venv && .venv/bin/pip install -e . pytest`, rồi bỏ `uv run`.

---

## 3. Bản đồ repo

```
qc-tool/
├── qctool/                    mã nguồn (chi tiết §6)
│   ├── cli.py, cli_run.py     lệnh qctool …; preflight + tóm tắt + mã thoát
│   ├── config.py              .env + dạng gọn của YAML → dạng đầy đủ (expand_project)
│   ├── pipeline.py            run_pipeline(): MỌI lượt chạy đi qua đây
│   ├── generation.py          điểm vào authoring agent (mỗi AC một phiên)
│   ├── artifacts.py           bố cục artifacts/ + run.json + events.jsonl
│   ├── summary.py             báo cáo tổng hợp cả project
│   ├── core/                  IR: Requirement, TestCase, Step, ACTION_SPECS, validate, coverage
│   ├── ingest/                markdown → requirements (ID ổn định, hash, trích dẫn)
│   ├── generate/              OpenAPI → case API (tất định)
│   ├── agent/                 authoring agent: loop, tools, gate, safety, knowledge, LLM provider
│   ├── data/                  test data: fixture alias, xác minh, provisioning (opt-in)
│   ├── execute/               runner + BrowserSession (Playwright) + HttpSession
│   ├── render/                IR → Excel 14 cột; ghi kết quả ngược
│   ├── report/                report.md, junit.xml, results.csv/json
│   ├── ui/                    crawl/explore (API cũ, phần lớn đã thay bằng agent tools)
│   └── web/                   qctool ui: app.py (HTTP), chat.py, chat_page.py, setup.py
├── projects/                  dữ liệu người dùng: <project>/project.yaml + <feature>/
│   ├── demo/task-manager/     HƯ CẤU — chạy với mock server
│   └── salonhub/<11 feature>/ hệ thống thật (pilot)
├── templates/                 hợp đồng I/O: testcase/ (xlsx sinh từ script), api/, report/
├── scripts/                   build_testcase_template.py, validate_openapi.py
├── tests/                     ~540 test; mock_server.py có bug cài sẵn; fixtures/ hư cấu
├── docs/                      brainstorms/, findings/, tracking/ (có frontmatter YAML)
├── AGENTS.md  HUONG-DAN.md  README.md  DEVELOPMENT.md
└── .env(.example)             bí mật — .env bị gitignore
```

⚠ **`projects/` bị gitignore** (trừ vài file được thêm bằng tay: `projects/demo/**`,
`projects/salonhub/project.yaml`). Tài liệu 11 feature SalonHub **chỉ có trên máy đã tạo ra
chúng** — clone mới sẽ thiếu (xem §15).

---

## 4. Khái niệm cần nắm

| Khái niệm | Nghĩa | Ở đâu |
|---|---|---|
| **Project / feature** | Project = một sản phẩm (`projects/<p>/project.yaml`, cấu hình chung). Feature = một phần (`<p>/<f>/qctool.yaml` + tài liệu + `artifacts/`). Feature ghi đè project | `config.py::expand_project` |
| **Requirement** | User story / AC / FR / NFR đọc từ tài liệu, có ID canonical (`AC-auth-001-1`), `content_hash`, `source` (file, dòng, trích dẫn) | `core/model.py` |
| **Intent / obligation** | Một mệnh đề *Then* của một AC cần được kiểm. Agent làm việc theo intent | `generation.py::run_generation` |
| **Testcase IR** | `TestCase` + danh sách `Step(action, args, source)`. Định dạng trung tâm; Excel chỉ là renderer | `core/testcase.py` |
| **Action / verb** | `ui.click`, `assert.text`, `http.request`… — danh sách đóng `ACTION_SPECS` (§6.2) | `core/testcase.py` |
| **Fixture alias** | Tên thay cho giá trị bí mật: `active_user.password`, `ac_001_3.password`. IR và model chỉ thấy alias; runner mới resolve | `data/fixtures.py` |
| **Generation status** | `ready` / `needs_review` / `manual` / `blocked_env` — chất lượng case khi sinh. **Không** phải kết quả chạy | `TestCase.generation_status` |
| **Runtime status** | `Pass` / `Fail` / `Blocked` / `Not Executed` (+ cờ `flaky`) — kết quả chạy | `execute/runner.py` |
| **Gate** | Kiểm tra tất định cho bản nháp của agent: schema, citation, thứ tự, route nguồn | `agent/gate.py` |
| **Dry-run** | Chạy thử action/locator trên context mới; không đánh giá assertion | `agent/tools.py::AgentTools.dry_run` |
| **Safe mode / write mode** | Mặc định chặn mọi thao tác ghi; `mode: write` + xác nhận mới cho ghi | `agent/safety.py` |
| **App knowledge** | `2-crawl/app-model.yaml`: trang đã quan sát + macro đăng nhập; giữ qua các lượt chạy | `agent/knowledge.py` |
| **Artifacts** | Output của một lượt chạy, chia theo bước `1-ingest … 6-report` | `artifacts.py` |

---

## 5. Một lượt `qctool run` đi qua những đâu

```
qctool run salonhub --auth --only 001-1
  │
  ├─ cli.py::main ─► cmd_run ─► _each_feature
  │     resolve_targets()          projects/salonhub/*/qctool.yaml (lọc theo --auth)
  │     confirm_write()            nếu có feature mode: write → hỏi "yes" / --yes
  │     for mỗi feature:
  │       cli_run.py::cmd_project
  │         preflight()            đọc config + tài liệu + OpenAPI, KHÔNG gọi model/browser/API
  │         pipeline.run_pipeline(cfg, on_progress, resolution_llm, exploration_llm)
  │         build_summary() ─► mã thoát 0–4 (§12)
  │     summary.write_project_summary()  projects/<p>/summary/<ngày_giờ>/
  │
  └─ pipeline.py::run_pipeline  (không bao giờ ném lỗi ra ngoài — trả PipelineResult.error)
        RunTracker(out_dir)                         dọn artifacts/ (trừ KEEP), tạo run.json
        [1-ingest]   ingest.ingest_feature()        → requirements.yaml
        [3-generate] generate.generate_all(None, openapi)   case API tất định (nếu có OpenAPI)
        [2-crawl]    BrowserSession: đăng nhập nếu auth.mode=browser, lưu .auth-state.json,
                     ghi macro đăng nhập vào app-model.yaml, lấy token cho API
        [3-generate] generation.run_generation()    agent viết case cho từng intent (§7)
                     validate.validate_batch()      ID trùng, gap, orphan, case chưa map
                     → generation.json, testcases.yaml
        [4-render]   render.render()                → testcases.xlsx (14 cột)
        [5-execute]  execute.run_cases()            HTTP + Chromium, mỗi case một context
                     → results.json/.csv, junit.xml, evidence/
        [6-report]   report.build_markdown()        → report.md
                     render.fill_results()          ghi kết quả ngược vào xlsx
        tracker.finish() / tracker.fail()           run.json không bao giờ kẹt "running"
```

Web UI và chat **không có đường riêng**: `web/app.py::_project_config` dựng config bằng đúng
`cli_run.preflight`, và mỗi mục kế hoạch chat là một lần `_run_feature` ≡ `qctool run <p> --<f> --only …`.

---

## 6. Từng package: file và hàm quan trọng

### 6.1 Lớp ngoài: CLI, config, pipeline

| File | Hàm/lớp chính | Việc |
|---|---|---|
| `cli.py` | `main`, `build_parser`, `_step_parsers` | Parse lệnh. `--<feature>` được nhận động theo thư mục có thật |
| | `resolve_targets`, `_each_feature` | Project → danh sách `qctool.yaml`; chạy lần lượt; in bảng tổng hợp; mã thoát = mã xấu nhất |
| | `cmd_init` (`PROJECT_TEMPLATE`, `FEATURE_TEMPLATE`), `cmd_trace`, `cmd_demo`, `cmd_serve` | Các lệnh phụ |
| | `cmd_ingest`, `cmd_generate`, `cmd_run_testcases`, `cmd_crawl` | `qctool step …` — chạy từng chặng |
| `cli_run.py` | `preflight` → `Preflight` | Đọc config/tài liệu/OpenAPI bằng loader thật; tạo LLM adapter. Lỗi → `PreflightError` (mã 2) |
| | `cmd_project`, `build_summary`, `print_summary`, `redact`, `confirm_write` | Chạy một feature, ghi `pipeline.log` + `summary.json`, tính mã thoát |
| `config.py` | `load_dotenv`, `load_config` → `Config` | Biến môi trường; `.env` không ghi đè biến đã có |
| | `expand_project` | **Dạng gọn → dạng đầy đủ**: gộp `project.yaml` (sâu), alias `docs/web/api/llm`, mặc định theo thư mục, `generation.budget = AGENT_BUDGET` |
| | `_expand_account` | `account: {role, login_for, test_values}` → `test_fixtures` (bindings + acquisition). Chỉ AC liệt kê mới được bind |
| `pipeline.py` | `PipelineConfig` (+ `from_file`) | Mọi tham số của một lượt chạy (§9) |
| | `run_pipeline` → `PipelineResult` | Toàn bộ luồng ở §5 |
| | `_warm_up`, `_resolve_base_url`, `_pick_base_url`, `_login` | Đánh thức backend ngủ; chọn host theo `servers` của OpenAPI; OIDC password flow |
| `artifacts.py` | `STAGES`, `KEEP`, `RunTracker` (`dir/output/event/skip/fail/finish`) | Bố cục artifacts; mỗi file output thuộc đúng một bước |
| `summary.py` | `write_project_summary` | Chép report/results/xlsx/evidence của mọi feature vào `summary/<ngày_giờ>/` |

### 6.2 `core/` — mô hình dữ liệu

| File | Nội dung |
|---|---|
| `model.py` | `Requirement` (kind: `user_story` / `acceptance_criterion` / `functional` / `non_functional`), `SourceRef`, `ApiSpec`. `content_hash` chỉ tính trên nội dung ngữ nghĩa → sửa chỗ khác không đổi hash |
| `testcase.py` | `TestCase`, `Step`, `ActionSpec`, **`ACTION_SPECS`**. `Step.describe()` / `Step.expects()` sinh chữ cho cột *Test Steps* / *Expected Result*. `TestCase.needs_mapping` = còn bước `*.unmapped` |
| `validate.py` | `validate_batch` → `Report`: lỗi từng case, ID trùng, case trùng, gap (requirement không có case), orphan, tỉ lệ case âm. `coverage_line` |
| `coverage.py` | `analyze_coverage`: độ phủ **ý định** (nghĩa vụ nguồn đã có case chưa) — không phải độ phủ Pass |
| `executability.py` | `analyze_executability`: case có chạy được với runner hiện tại không (thiếu adapter, thiếu tham số…) |

**Bộ verb** (`ACTION_SPECS`; ★ = cần trình duyệt, nằm trong `runner.UI_VERBS`):

| Nhóm | Verb |
|---|---|
| Hành động UI ★ | `ui.goto` `ui.session` `ui.click` `ui.fill` `ui.select` `ui.hover` `ui.press` `ui.check` `ui.scroll` `ui.wait_for` |
| Assert UI ★ | `assert.visible` `assert.not_visible` `assert.enabled` `assert.disabled` `assert.text` `assert.value` `assert.attr` `assert.count` `assert.focused` `assert.checked` `assert.url_matches` `assert.console_clean` `assert.no_broken_requests` `assert.screenshot` `assert.axe` |
| HTTP | `http.request` · `assert.http_status` `assert.json_field` `assert.json_schema` `assert.response_time` |
| Chung | `assert.contains` `assert.not_contains` `assert.equals` `assert.text_matches` `wait` |
| Chưa có adapter thật | `db.query` `assert.db_row` `cli.run` |
| Case thủ công | `perform.unmapped` `assert.unmapped` |

`ui.click` có thể kèm `capture_response` / `capture_requests` để bắt request do chính cú click gây ra
(kiểm "POST /api/login trả 200", "không gửi request"). Xem `data/capture.py`.

### 6.3 `ingest/` — tài liệu → requirements

| File | Hàm | Việc |
|---|---|---|
| `__init__.py` | `ingest_feature`, `ingest_one`, `ingest_tree`, `discover_features`, `write_yaml` | Một thư mục feature (hoặc cả cây) → dict `requirements` + cảnh báo |
| `markdown.py` | `parse_urd`, `parse_srs_functions`, `parse_srs_nfr`, `parse_srs_responses` | Parser markdown. **Không đoán**: thiếu thì để trống + cảnh báo |
| `ids.py` | `canonical` | `AC-001-1` → `AC-<feature>-001-1`; `F-01` → `FR-<feature>-001` |
| `flows.py` | `extract` | Sequence/state diagram mermaid, bảng quyết định → luồng (phục vụ coverage) |

**Định dạng URD tối thiểu** để đọc được AC:

```markdown
### US-001 — Tiêu đề user story
**As a** … / **I want** … / **So that** …

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-001-1 | Phiên anonymous ở /login | Nhập email; bấm Đăng nhập | URL chuyển tới /; hiển thị Xin chào |
```

Mỗi mệnh đề trong *Then* (tách bằng `;`) là một thứ phải được assert. SRS là bằng chứng phụ
(route, control, `data-testid`) — agent đọc nó qua `read_docs`.

### 6.4 `generate/` — OpenAPI → case API (tất định)

| File | Hàm | Việc |
|---|---|---|
| `loader.py` | `load_endpoints` → `Endpoint` | Đọc spec, giải `$ref`/`allOf` đơn giản. Bỏ operation `x-external: true`; tôn trọng `servers` cấp operation |
| `from_openapi.py` | `generate_for_endpoint`, `IdAllocator` | EP, BVA, ma trận auth, lỗi validate. `_can_trigger` chặn case "mong đợi 422" khi không dựng được input sai; `_wrong_type_value` gửi giá trị **sai kiểu** |
| `__init__.py` | `generate_all`, `write_cases` | Gom case từ mọi nguồn; văn xuôi không có LLM → case thủ công |

Operation mang `x-qc-observe-only: true` (API ghi trên production) không bao giờ được sinh case gọi.

### 6.5 `generation.py` + `agent/` — authoring agent

Xem §7 cho luồng. Bảng file:

| File | Hàm/lớp | Việc |
|---|---|---|
| `generation.py` | `run_generation` → `GenerationResult` | Liệt kê intent từ AC; `design_intents` (LLM đặt tiêu đề/thứ tự); chuẩn bị test data; mỗi intent một `AgentTools` + `author_intent`; lưu `AppKnowledge` |
| `agent/loop.py` | `author_intent`, `protocol`, `tool_definitions`, `compact_history`, `manual_case`, `AgentBudget` | Vòng hội thoại tool-calling cho một intent; system prompt; cắt lịch sử (chỉ giữ snapshot trang mới nhất) |
| `agent/tools.py` | `AgentTools` (`call`, `act`, `snapshot`, `dry_run`), `locator`, `public` | Thực thi tool của model trên Chromium thật; `public()` che bí mật trong mọi thứ trả về model |
| `agent/gate.py` | `draft_case`, `check_case`, `source_routes`, `GateResult` | Gate tất định (§7.3) |
| `agent/safety.py` | `SafetyPolicy` (`url`, `value`, `approve_action`, `check_case`, `attach`, `risky_path`, `control_reviewed`) | Chặn origin lạ, request ghi, control nguy hiểm, giá trị không phải alias. Gắn vào route của page |
| `agent/exploration_actions.py` | `high_risk`, `mutation_policy`, `MutationBudget` | Nhận diện control/route rủi ro; quy tắc cho phép ghi cụ thể (`exploration.mutation`) |
| `agent/knowledge.py` | `AppKnowledge` (`observe`, `remember`, `macro`, `hints`, `save`) | Trí nhớ công khai giữa các intent/lượt chạy (§7.5) |
| `agent/llm_provider.py` | `OpenAICompatibleLLM.chat`, `load_llm_provider`, `capture_provider_attempts`, `LLMProviderError` | Client Chat Completions (stdlib), retry transport tối đa 1 lần, audit metadata không chứa nội dung |

### 6.6 `data/` — test data

| File | Việc |
|---|---|
| `fixtures.py` | `FixtureStore`: giữ giá trị thật, chỉ lộ metadata. `bind` gắn alias vào case; `resolve` chỉ runner gọi. `PUBLIC_FACT_VALUES` = danh sách **đóng** của `role` (customer, staff, admin, warehouse_staff, service_staff, accountant) và `account_state` |
| `preparation.py` | `prepare_test_data`: acquisition → (xác minh) → (provisioning) — mỗi case tối đa một vòng |
| `acquisition.py` | Tìm dữ liệu khai báo sẵn cho Given của AC, offline |
| `verification.py`, `provisioning.py` | Xác minh fixture bằng request đã duyệt; tạo dữ liệu (opt-in `provisioning.enabled`). Tài liệu: `docs/test-data-*.md` |
| `cache.py` | `PreparationCache`: dùng lại bằng chứng trong **một** lượt chạy |
| `capture.py` | Hợp lệ hoá `capture_response`/`capture_requests` |

### 6.7 `execute/` — chạy thật

| File | Hàm/lớp | Việc |
|---|---|---|
| `runner.py` | `run_cases` → `RunResult` | Chạy cả lô; tách case cần trình duyệt |
| | `run_case` | Retry để tách **flaky** khỏi fail thật (§8) |
| | `_run_once`, `_run_step`, `_run_ui_step`, `_compare` | Quyết định trạng thái; dispatch bước HTTP/UI/assert |
| | `UI_VERBS`, `needs_browser`, `HttpSession` | Danh sách verb cần trình duyệt; client HTTP stdlib (luôn gửi `USER_AGENT`) |
| `browser.py` | `BrowserSession` | Bọc Playwright: `start_case`/`end_case` (**context riêng mỗi case**), `login` (form hoặc SSO), `save_state`/`session_alive`, `locate` (test id → role+name → text), `_check` (dùng `expect()` tự chờ), `screenshot` (che ô password/fixture), `capture_final`, `axe_scan` |
| | `NeedsEnvironment`, `NeedsLogin`, `BrowserError`, `LoginError` | Ngoại lệ → `Blocked` (lỗi môi trường), không phải `Fail` |
| | `_is_env_problem` | `ERR_NETWORK_CHANGED`, mất mạng… là lỗi máy test |

### 6.8 `render/`, `report/`

| File | Việc |
|---|---|
| `render/excel.py::render` | IR → `testcases.xlsx` 14 cột, dropdown, tô màu. Sheet Review: `read_review_labels` |
| `render/results.py::fill_results` | Điền 4 cột runtime (*Actual Result, Status, Environment, Executed By/Date*) vào file đã sinh |
| `report/__init__.py` | `build_markdown` (report.md tiếng Việt, số liệu lên đầu, Mục 6 = flaky), `write_junit`, `write_csv`, `write_json` |

Template 14 cột: `templates/testcase/` — **sinh từ** `scripts/build_testcase_template.py`, không sửa tay `.xlsx`.

### 6.9 `web/` — `qctool ui`

| File | Việc |
|---|---|
| `app.py` | HTTP server stdlib (`Handler`, `serve`). Bảng định tuyến `SETUP_GET/POST`, `CHAT_GET/POST`; `/api/run`, `/api/runs`, `/api/download`. `_project_config` (= CLI preflight), `_run_feature`, `_open_trace`, `_run_state` (live/running/interrupted). Trang `/console` (HTML trong `PAGE`) |
| `chat_page.py` | `CHAT_PAGE` — HTML/JS tĩnh của trang `/` (chat + drawer "Dữ liệu đầu vào"). Là `r"""…"""` |
| `chat.py` | Trợ lý điều phối: `catalog`, `send`/`_answer` (vòng LLM), `TOOLS` (`list_features`, `get_requirements`, `search_requirements`, `propose_test_plan`, `get_last_results`), `start_plan`/`cancel_plan`, `upload`, `note` |
| `setup.py` | Cấu hình qua giao diện (hàm thuần): `create_project`, `save_project_form`, `save_project_yaml`, `create_feature`, `get_feature`, `save_feature_account`, `save_feature_yaml`, `save_doc`, `get_env`/`save_env`, `test_llm`. Mọi lần ghi YAML qua `_write_checked`: ghi → nạp lại bằng loader thật → lỗi thì khôi phục |

### 6.10 `ui/` (cũ)

`crawl.py` (`crawl` → `ui-map.yaml`, dùng bởi `qctool step crawl`) và `explore.py` (API quan sát
tương thích). Luồng `qctool run` hiện dùng `agent/tools.py` để quan sát trang; `ui-map.yaml` chỉ còn
dùng ở các lệnh `step`.

---

## 7. Authoring agent — trái tim của tool

### 7.1 Mỗi AC chạy thế nào

```
generation.run_generation
  intents = mỗi AC → {id, req_id, given, when, expected}
  design_intents(intents, llm)                 LLM đặt tiêu đề; KHÔNG được thêm/bớt/sửa expected
  for intent:
     prepare_test_data(...)                    thiếu fixture/dữ liệu → blocked_env, bỏ qua agent
     policy = SafetyPolicy(...)                riêng cho intent này (route nguồn, safe_controls…)
     tools  = AgentTools(intent, policy, knowledge, storage_state)
     author_intent(intent, tools, llm, budget) ─┐
                                                │  lượt 1..max_turns:
                                                │    LLM chọn tool → tools.call(name, args)
                                                │    lỗi → trả nguyên văn lỗi cho model sửa
                                                │    draft_case qua gate + dry-run → READY
                                                └─ hết budget / lỗi lặp lại / model bỏ cuộc → case thủ công
```

**Tool model được dùng** (`loop.py::tool_definitions`):

| Tool | Việc |
|---|---|
| `read_docs` | Trả lại intent nguồn |
| `list_api` | Operation trong OpenAPI (khai báo, không phải sự thật) |
| `browser_observe` | Mở URL (tuỳ chọn) → ARIA snapshot đã che + danh sách `data-testid` |
| `browser_act` | Một thao tác an toàn: `ui.goto/session/click/fill/select` |
| `draft_case` | Nộp bản nháp → **gate** → nếu qua thì **dry-run** |
| `dry_run` | Chạy lại dry-run cho bản nháp hiện tại |
| `use_macro` | Chạy macro đã nhớ (vd `authenticate:active_user`), vẫn kiểm live |

### 7.2 Budget và lý do dừng

`config.AGENT_BUDGET` (mặc định cho mọi project qua `expand_project`): **14 lượt · 90.000 token ·
480 giây · 2.200 token/câu trả lời**. (Mặc định của dataclass `AgentBudget` nhỏ hơn — 6/22.000/240 — chỉ
áp dụng khi gọi trực tiếp không qua config.) Đặt riêng: `generation.budget` trong YAML.

| `stop_reason` | Nghĩa |
|---|---|
| `READY` | Qua gate + dry-run |
| `TOKEN_BUDGET` / `TIME_BUDGET` / `BUDGET` | Hết budget |
| `REPEATED_ERROR` | Gọi lại đúng tool + tham số + lỗi như trước → dừng sớm |
| `MODEL_ABSTAINED` | Model trả lời không gọi tool (thường: thiếu fixture, bị safety chặn) |
| `PROVIDER_ERROR` / `AGENT_ERROR` | Lỗi LLM provider / lỗi code |

Mọi lý do khác `READY` → `manual_case`: case thủ công, `Not Executed`, lý do nằm trong
`review_reasons` và `generation.json`.

### 7.3 Gate (`agent/gate.py::check_case`)

Bản nháp bị từ chối (lỗi trả về model) nếu:

- `TestCase.validate()` hỏng (verb lạ, thiếu tham số) hoặc `SafetyPolicy.check_case` chặn.
- Case UI không bắt đầu bằng `ui.session` (anonymous/authenticated tường minh).
- Route nêu trong Given/When (`source_routes`) **không có bước nào mở/gọi** nó.
- Assertion thiếu `source = {req_id, quote}` hoặc `quote` không phải chuỗi con nguyên văn của expected.
- Một mệnh đề expected không có assertion nào trích nó, hoặc chỉ được assert **trước** hành động cuối.
- `assert.url_matches` không phải regex path hợp lệ (có khoảng trắng, không có `/`).

Bị hạ xuống `needs_review` (vẫn chạy, chưa tính là sinh thành công) nếu: oracle chỉ là có/không hiển
thị, giá trị expected không xuất hiện nguyên văn trong quote, regex phức tạp, critic nghi ngờ, hoặc
có bước ghi chưa dry-run (`WRITE_NOT_DRY_RUN`).

### 7.4 Dry-run (`AgentTools.dry_run`)

Context trình duyệt **mới**, chạy lần lượt các bước:
- Bước `ui.*`: thực hiện qua `act(..., dry_run=True)` — safety vẫn áp dụng.
- Bước `assert.*`: **chỉ** kiểm locator tìm được đúng 1 element. Không đánh giá, không trả giá trị
  thực tế → model không thể "sửa expected theo sản phẩm".
- Gặp request ghi đầu tiên (write mode): dừng, **không gửi**; runner sẽ gửi đúng một lần lúc chạy.
- Lỗi ở bước không phải assert → trả kèm snapshot trang để model sửa.

Locator (`tools.py::locator`): `data-testid` → (role + accessible name chính xác) → text chính xác.
Phải ra **đúng 1** element; không bao giờ dùng `.first()`.

### 7.5 Trí nhớ của agent

- `AppKnowledge` (`2-crawl/app-model.yaml`) dùng chung cho mọi intent trong lượt chạy và **giữ qua
  các lượt** (`artifacts.KEEP`). Nó lưu toàn bộ quan sát trang + macro đăng nhập.
- Nhưng model của intent sau chỉ nhận `app_hints` = **danh sách URL đã thấy + tên macro**, không nhận
  element. Nên AC2 vẫn gọi `browser_observe` lại trang AC1 đã xem (≈ 2 giây + ~4k token mỗi lần).
- Macro `authenticate:<fixture>` được ghi khi một case có bước đăng nhập qua dry-run; intent sau gọi
  `use_macro`, vẫn kiểm live.
- Cố ý: DOM đổi theo phiên/thời gian; mọi locator phải được kiểm trên trang thật.
- Không lưu token/cookie/mật khẩu trong knowledge (`public()` che). Phiên đăng nhập nằm riêng ở
  `2-crawl/.auth-state.json`.

### 7.6 Safety (`agent/safety.py`)

| Cơ chế | Cấu hình |
|---|---|
| Chỉ origin của app (và origin trong OpenAPI) | — |
| Route rủi ro (`/admin`, `/delete`…) chỉ mở được nếu Given/When nêu đúng route đó hoặc nằm trong `exploration.safe_paths` | `safe_paths` |
| Control nhãn rủi ro (Đăng ký, Đăng xuất, Xoá, Thanh toán…) chỉ bấm được nếu đã duyệt | `exploration.safe_controls` (theo `data-testid`) |
| Request ghi (POST/PUT/PATCH/DELETE) bị chặn ở safe mode | `mode: write` hoặc `--write` + xác nhận |
| Ghi bị cấm ở mọi chế độ | `write.deny: ["PUT /api/x"]` |
| Request nền (Socket.IO) bị chặn lặng lẽ, không tính là "ghi chưa duyệt" | `exploration.background_paths` |
| `ui.fill` ô mật khẩu chỉ nhận fixture alias | `account.login_for`, `account.test_values` |

---

## 8. Runner và bốn trạng thái kết quả

`runner.py::_run_once` quyết định theo thứ tự:

| Điều kiện | Trạng thái |
|---|---|
| `case.execution == "manual"` | `Not Executed` |
| Cần setup/dữ liệu tool không tự tạo được | `Blocked` |
| `case.needs_mapping` (còn `*.unmapped`) | `Blocked` |
| Bước UI mà không có trình duyệt / chưa đăng nhập / không nạp được axe / lỗi mạng máy test (`NeedsEnvironment`, `NeedsLogin`) | `Blocked` + lý do |
| Một assertion sai, hoặc lỗi bất ngờ khi chạy bước | `Fail` |
| Mọi bước `[OK]` | `Pass` |

`run_case` thêm vòng **retry** (`ui.retry`, tối đa 3) chỉ khi lần đầu `Fail`:
- Lần sau `Pass` → `Pass` + `flaky=True` + giữ lý do lần hỏng đầu (báo cáo Mục 6).
- Lần sau `Blocked` → `Blocked` (không phải flaky).
- Hỏng mọi lần → `Fail` thật.

Validator chặn case `needs_mapping` mang `Pass`. Assert UI luôn qua `expect()` của Playwright (tự chờ),
không đọc DOM một lần.

---

## 9. Cấu hình: `project.yaml`, `qctool.yaml`, `.env`

Thứ tự gộp (`config.py::expand_project`): `project.yaml` → `<feature>/qctool.yaml` (feature thắng) →
dạng gọn mở rộng → khoá tường minh thắng mặc định. Cấu hình được trên web (§11) hoặc sửa file.

| Khoá | Mặc định | Ý nghĩa |
|---|---|---|
| `web` (= `web_url`) | — | Link webapp; có thì mở trình duyệt |
| `api` (= `run.base_url`) | = `web` | Host API |
| `llm: true` (= `llm.enabled`) | `false` | Bật authoring agent |
| `docs` (= `docs_dir`), `openapi`, `out.dir` | `.`, `openapi.yaml`, `artifacts` | Theo thư mục feature |
| `feature`, `module` | tên thư mục / IN HOA | ID testcase `TC_<MODULE>_<NNN>` |
| `account.role` | `user` (**không hợp lệ** khi có `login_for`) | Một trong `PUBLIC_FACT_VALUES["role"]` |
| `account.login_for: [001-1, …]` | — | AC được điền tài khoản thật (`active_user.*` ← `.env`) |
| `account.test_values: {"001-3": {password: "Sai123"}}` | — | Giá trị giả cho ô nhạy cảm, fixture `ac_<id>.<field>` |
| `auth.mode` | `browser` nếu có `login_for`, ngược lại `manual` | `manual` = **không** tự đăng nhập kể cả khi `.env` có tài khoản |
| `run.timeout_seconds` | 30 | Mỗi bước |
| `ui.evidence` | `on-fail` | `off` / `on-fail` / `always` |
| `ui.trace`, `ui.trace_sensitive` | `false` | Trace Playwright; `trace_sensitive` = trace cả case có mật khẩu (⚠ file chứa bí mật) |
| `ui.retry`, `ui.axe`, `ui.soft_assert`, `ui.viewport` | 0, false, false, 1440×900 | |
| `generation.budget` | `AGENT_BUDGET` | `{max_turns, max_tokens, max_seconds, completion_tokens}` |
| `generation.critic` | `false` | LLM thứ hai soát độ trung thành với nguồn |
| `mode` | `safe` | `write` = cho phép ghi dữ liệu thật (luôn hỏi xác nhận) |
| `write.deny` | — | Ghi bị cấm ở mọi chế độ |
| `exploration.safe_controls`, `safe_paths`, `background_paths`, `mutation` | —, —, `/socket.io/`, — | §7.6 |
| `provisioning.enabled`, `test_fixtures` | `false` | Nâng cao — `docs/test-data-*.md` |

**`.env`** (mẫu đầy đủ: `.env.example`): `QCTOOL_USERNAME`, `QCTOOL_PASSWORD`, `QCTOOL_BEARER_TOKEN`,
`QCTOOL_AUTH_MODE`, `QCTOOL_BASE_URL`, `QCTOOL_OIDC_ISSUER`, `QCTOOL_OIDC_CLIENT_ID`,
`QCTOOL_TIMEOUT_SECONDS`, `QCTOOL_VERIFY_SSL`, `QCTOOL_LLM_ENABLED`, `QCTOOL_LLM_BASE_URL`,
`QCTOOL_LLM_API_KEY`, `QCTOOL_LLM_MODEL`, `QCTOOL_LLM_TIMEOUT_SECONDS`, `QCTOOL_LLM_THINKING`.
Có API key **không** tự bật LLM — phải có `llm: true`.

---

## 10. Artifacts và cách truy vết một lượt chạy

```
projects/<p>/<f>/artifacts/
  run.json           trạng thái từng bước, file sinh ra, lỗi ở đâu  ← ĐỌC ĐẦU TIÊN
  events.jsonl       {t, stage, level, message} — web UI đọc trực tiếp
  pipeline.log       log đầy đủ (đã redact)       summary.json   tóm tắt + mã thoát
  1-ingest/   requirements.yaml
  2-crawl/    app-model.yaml (KEEP), .auth-state.json (KEEP), .token (KEEP)
  3-generate/ generation.json (agent_history, issues, coverage), testcases.yaml
  4-render/   testcases.xlsx
  5-execute/  results.json, results.csv, junit.xml, evidence/<MÃ>-*.png, <MÃ>.trace.zip
  6-report/   report.md
  <bước>/stage.log (+ error.log khi bước đó lỗi)
```

Mỗi lượt chạy **xoá và ghi lại** artifacts (trừ `KEEP`). Muốn giữ lịch sử → `projects/<p>/summary/<ngày_giờ>/`
(tự sinh khi chạy cả project hoặc chạy từ web/chat).

**Gỡ lỗi một kết quả lạ — đọc ngược:**

1. `5-execute/results.json` → case đó, `actual[]` cho biết bước nào `[X]`.
2. `evidence/` → ảnh cuối / ảnh lỗi; `qctool trace <p> <MÃ>` mở Playwright Trace Viewer (timeline, DOM
   từng bước, network, console). Web: nút **▶ Mở trace Playwright**.
3. `3-generate/testcases.yaml` → case gồm những bước gì, trích dẫn từ đâu.
4. `3-generate/generation.json` → `agent_history` theo intent: tool đã gọi, lỗi gate/dry-run, token,
   `stop_reason`. Case thủ công: xem `unresolved_cases` + `review_reasons`.
5. `run.json` + `<bước>/error.log` nếu pipeline hỏng giữa chừng.

**Trace và bí mật:** case có điền fixture mật khẩu hoặc `capture_*` **cố ý không có trace** (trace chứa
nguyên văn giá trị). Ảnh vẫn có và che ô password/ô đã điền fixture. Bật có chủ đích:
`ui.trace_sensitive: true` hoặc `--trace-sensitive` — chỉ dùng cục bộ với tài khoản test.

---

## 11. Web UI và chế độ chat

`qctool ui [--port 8080]` → `http://127.0.0.1:8080`

| Đường dẫn | Là gì |
|---|---|
| `/` | Chat (`chat_page.py`): trợ lý lập kế hoạch, người dùng bấm **▶ Chạy QC** mới chạy |
| `/console` | Bảng điều khiển chi tiết: chọn feature, tuỳ chọn chạy, log trực tiếp, tab agent/kết quả/file |
| `/api/setup/*` | Cấu hình project/feature/tài liệu/`.env` (`setup.py`) |
| `/api/chat/*` | Phiên chat, upload, kế hoạch, tài khoản (`chat.py`) |
| `/api/run`, `/api/runs`, `/api/download`, `/api/trace/open` | Chạy, xem lượt chạy (đọc từ đĩa), tải file, mở trace |

**Drawer "📎 Dữ liệu đầu vào"** (trang `/`):
1. Project: tên, URL web/API, ảnh bằng chứng, trace, timeout; *Nâng cao* sửa `project.yaml`.
2. Chức năng: thả `urd/srs/openapi` (tên chứa "urd"/"srs"/"openapi" được tự nhận); chọn chức năng →
   tick AC **dùng tài khoản thật** (`login_for`) + **giá trị giả** (`test_values`); *Nâng cao* sửa `qctool.yaml`.
3. Tài khoản test → `.env`; vai trò tài khoản → `project.yaml`.
4. LLM → `.env`, nút **Kiểm tra** gọi thử tool calling.

**Trợ lý chat** (`chat.py`): chỉ có tool **chỉ đọc** + `propose_test_plan` (mọi mã AC được đối chiếu với
tài liệu đã ingest; sai → trả lỗi cho model). Không viết testcase, không tự chạy. Phiên lưu ở
`projects/<p>/chat/<id>.json` — không có `reasoning_content`, username, mật khẩu (model chỉ thấy
`account_set`). Thông báo hệ thống (đã tải tài liệu, kế hoạch chạy xong) vào transcript ở tin nhắn kế
tiếp qua `pending_notes`. Scope `flow` chạy feature theo thứ tự nhưng **mỗi AC vẫn là case độc lập** —
không phải E2E.

Bảo vệ: POST chỉ nhận `Content-Type: application/json` cùng origin (chống CSRF tới 127.0.0.1);
feature `mode: write` bị web từ chối (không có bước xác nhận).

> Trang HTML là chuỗi Python trong bộ nhớ: sửa `chat_page.py`/`app.py` phải **khởi động lại `qctool ui`**.

---

## 12. Lệnh hay dùng và mã thoát

```bash
# Người dùng
qctool init <p>/<f>                  # tạo project.yaml + <f>/qctool.yaml
qctool check <p>                     # preflight mọi feature: config/docs/OpenAPI, không gọi model/browser/API
qctool run <p> [--<f> …]             # chạy; thêm --only 001-1 · --no-llm/--llm · --skip-run · --show-browser
                                     #       --write/--safe/--yes · --trace-sensitive · --docs/--openapi/--url/--out
qctool trace <p> <MÃ_TEST>           # playwright show-trace
qctool ui [--port N] [--no-browser]
qctool demo

# Từng chặng (không qua agent)
qctool step ingest   <feature-dir> --feature <tên>
qctool step generate --requirements <a>/1-ingest/requirements.yaml --openapi <spec> --xlsx <a>/4-render/testcases.xlsx
qctool step exec     <a>/3-generate/testcases.yaml --base-url <url> [--web-url <url>] --xlsx …
qctool step crawl    <url>

# Dev
uv run python -m pytest tests/ -q -m "not playwright"
uv run python -m pytest tests/test_agent.py -q -k gate
uv run scripts/validate_openapi.py <file.yaml>
uv run scripts/build_testcase_template.py
uv run python -m tests.mock_server --port 8099
```

**Mã thoát** (`cli_run.build_summary`, `cli._EXIT`):

| Mã | Trạng thái | Nghĩa |
|---|---|---|
| 0 | `SUCCESS` | Sinh đủ, chạy hết, không lỗi |
| 1 | `EXECUTION_FAILED` | Có case `Fail` → sản phẩm có lỗi |
| 2 | `PIPELINE_ERROR` / preflight | Lỗi cấu hình hoặc tool |
| 3 | `GENERATION_INCOMPLETE` | Có AC chưa thành case tự động |
| 4 | `EXECUTION_INCOMPLETE` | Có case `Blocked` |

Chạy nhiều feature: mã cuối cùng = mã lớn nhất.

---

## 13. Test

- `tests/conftest.py` trỏ `pipeline.ARTIFACTS_ROOT`/`WEB_ROOT` vào `tmp_path` — **test không được ghi
  file vào repo**. Test web/chat dùng fixture `project` (`monkeypatch.chdir(tmp_path)`).
- Marker `playwright` = mở Chromium thật (~60 test, chậm). Bỏ qua bằng `-m "not playwright"`.
- `tests/mock_server.py`: API + trang HTML có **8 bug cài sẵn** (4 API, 4 giao diện — liệt kê trong
  docstring). Test khẳng định tool **phát hiện được** chúng. Sửa mock → sửa cả docstring.
- `tests/fixtures/`, `projects/demo/` là **hư cấu**. Không trỏ tool vào URL trong đó.

| Khu vực | File test |
|---|---|
| Ingest, ID | `test_ingest.py` |
| OpenAPI generator, validate, coverage | `test_generate.py`, `test_coverage.py`, `test_executability.py`, `test_regressions_portal.py` |
| Agent, gate, safety, provider | `test_agent.py`, `test_agent_browser.py`, `test_agent_provider.py`, `test_llm_provider.py`, `test_generation.py`, `test_pipeline_generation.py`, `test_business_intent.py`, `test_write_mode.py` |
| Test data | `test_fixtures.py`, `test_fixture_facts.py`, `test_data_*.py` |
| Runner, trình duyệt | `test_execute.py`, `test_browser.py`, `test_browser_login.py`, `test_empty_login.py`, `test_ui_run.py`, `test_ui_vocabulary.py`, `test_ui_response_capture.py`, `test_crawl.py`, `test_explore.py`, `test_mapper.py` |
| Pipeline, CLI, artifacts | `test_pipeline.py`, `test_pipeline_scope.py`, `test_cli_product.py`, `test_cli_product_browser.py`, `test_artifacts.py`, `test_workflow_evidence.py` |
| Web/chat/setup | `test_chat.py` |
| Bất biến tài liệu SalonHub | `test_customer_documents.py` (cần `projects/salonhub/` cục bộ) |

---

## 14. Công thức cho các thay đổi thường gặp

**Thêm verb UI mới** — sửa **ba** chỗ (thiếu là lỗi khó thấy):
1. `core/testcase.py::ACTION_SPECS` (required/optional) **và** nhánh trong `Step.describe()` +
   `Step.expects()` — đây là chữ QC đọc trong Excel.
2. `execute/runner.py::UI_VERBS`.
3. `execute/runner.py::_run_ui_step` → phương thức mới trong `BrowserSession` (assert thì dùng `_check`/`expect()`).
Nếu agent được dùng verb đó: kiểm `loop.py::tool_definitions` (enum lấy từ `ACTION_SPECS ∩ UI_VERBS`) và
`gate.py`. Thêm test trong `test_ui_vocabulary.py` + `test_browser.py`.

**Thêm khoá cấu hình:** `PipelineConfig` (field + `from_file`) → dùng trong `run_pipeline` → nếu là dạng
gọn thì `config.expand_project` → nếu người dùng cần chỉnh trên web: `web/setup.py::_project_form`/
`_apply_project_form` (`PROJECT_FIELDS`) + input trong `chat_page.py` → ghi vào bảng §9 và `HUONG-DAN.md`.

**Thêm tool cho trợ lý chat:** `chat.py::TOOLS` (schema) + nhánh trong `call_tool` + câu trong `SYSTEM`.
Tool chỉ đọc; mọi ID phải đối chiếu với `catalog`.

**Thêm tool cho authoring agent:** `loop.py::tool_definitions` + nhánh trong `tools.py::AgentTools.call` +
mô tả trong `protocol()`. Mọi thứ trả về đi qua `public()`; không trả giá trị assertion.

**Thêm luật gate:** `gate.py::check_case`. Lỗi phải nói rõ **dạng đúng** (lỗi mơ hồ làm agent lặp tới hết
budget). Thêm test hồi quy trong `test_agent.py`.

**Đổi template Excel:** sửa `scripts/build_testcase_template.py` + `render/excel.py`, chạy lại script, ghi
changelog, báo người dùng. Không sửa tay `.xlsx`.

**Thêm project/feature mới:** `qctool init <p>/<f>` hoặc web drawer → đặt `urd.md` (+ `srs.md`,
`openapi.yaml`) → `account.role` + `login_for` cho AC cần đăng nhập → `exploration.safe_controls` cho
control nhãn rủi ro nhưng an toàn → `qctool check <p>` → `qctool run <p> --<f> --only <1 AC>` để thử rẻ.

**Mọi nhánh kết thúc của `run_pipeline`** phải gọi `tracker.finish()` hoặc `tracker.fail(...)`; file
output ghi qua `tracker.dir(<bước>)` + `tracker.output(...)`.

---

## 15. Giới hạn đã biết và cạm bẫy

| Vấn đề | Chi tiết |
|---|---|
| LLM không tất định | Hai lượt chạy có thể ra số case tự động khác nhau. So sánh phải nhìn `generation.json`, không chỉ số Pass |
| `Fail` cần người xác nhận | Gate chứng minh *nguồn* của assertion, không chứng minh assertion **tương đương ngữ nghĩa**. Vd đã gặp: AC "không chứa *Cảm ơn…*" bị agent assert "vùng thông báo bị ẩn" → `Fail` giả |
| Trí nhớ agent mỏng | §7.5 — mỗi AC quan sát lại trang |
| Không có E2E | Mỗi AC một context; luồng nhiều bước nối trạng thái chưa hỗ trợ |
| `account.role` mặc định `user` không hợp lệ | Có `login_for` mà không đặt `role` → loader báo *"Fixture facts require approved non-secret role/account_state labels"*. Web đã báo rõ hơn; CLI thì chưa |
| Heuristic `needs_login` của chat | `chat.py::LOGIN_HINTS` khớp chữ "đăng nhập" nên AC "Phiên anonymous chưa đăng nhập" bị coi là cần đăng nhập — chỉ sai ở lời trợ lý, không ảnh hưởng chạy |
| Project tạo từ web: trace tắt, không có `safe_controls` | Bật trace ở mục 1; control như "Đăng ký" bị safety chặn cho tới khi khai `exploration.safe_controls` |
| `projects/` bị gitignore | Clone mới thiếu tài liệu SalonHub → `test_customer_documents.py` hỏng. Cần chép `projects/salonhub/` từ máy gốc |
| Render free tier | Backend ngủ 30–60 giây; `_warm_up` + `run.timeout_seconds: 45` |
| `db.*`, `cli.run` | Có trong vocabulary, chưa có adapter chạy thật |
| Milestones | Theo `docs/tracking/milestones.md`: chưa milestone nào đủ DoD; thiếu ma trận traceability Requirement↔Testcase↔Kết quả (M05); feedback loop review→few-shot (M07) chưa làm |

---

_Cập nhật: 2026-10-20 · Viết từ code ở nhánh `agent-redesign`. Khi đổi kiến trúc/luồng, sửa file này
cùng commit đó._
