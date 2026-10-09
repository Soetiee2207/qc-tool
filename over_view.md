# Báo Cáo Phân Tích Kiến Trúc Toàn Diện Repository qc-tool

> **⚠ Tài liệu V1 — đã lỗi thời (cập nhật 2026-10-09).** Báo cáo này mô tả kiến trúc trước
> QC-TOOL V2: mapper prose → action, semantic IR, proposal validator, resolution/coverage loop,
> exploration plan. Các phần đó **đã bị gỡ khỏi code**. Kiến trúc hiện tại: authoring agent
> tool-calling (`qctool/agent/`) — đọc `AGENTS.md` (mục *Authoring agent*), `README.md`,
> `HUONG-DAN.md` và `docs/findings/agent-redesign.md`. Ingest, OpenAPI generator, runner,
> browser, report và template 14 cột trong tài liệu này vẫn đúng.


> **Tài liệu tham khảo kỹ thuật**: Dành cho việc nghiên cứu, tái sử dụng và phát triển QC Tool tự động hoá kiểm thử đa nền tảng (Web / API / E2E).
> **Nguồn phân tích**: Repository `/home/soetie/Documents/2026_Document/qc-tool`.

---

# 1. Tổng quan hệ thống

### Repository này dùng để làm gì?

`qc-tool` là công cụ tự động hoá kiểm thử chất lượng phần mềm (QC Tool) end-to-end theo tư tưởng **deterministic-first** (không phụ thuộc vào ảo giác của LLM). Tool nhận đầu vào gồm **tài liệu yêu cầu (URD/SRS/brainstorm markdown)**, **đặc tả OpenAPI (OAS 3.0)**, và **đường dẫn webapp**, sau đó tự động:

1. Trích xuất yêu cầu và luồng nghiệp vụ thành tập manifest chuẩn hoá có ID ổn định và băm nội dung ngữ nghĩa (`content_hash`).
2. Sinh bộ testcase trung gian (Testcase IR) áp dụng các kỹ thuật kiểm thử kinh điển (Equivalence Partitioning, Boundary Value Analysis, Decision Table, State Transition, Auth Matrix).
3. Thu thập bản đồ phần tử giao diện (`ui-map.yaml`) bằng trình duyệt Chromium thật qua Playwright (2 pha: ẩn danh và đã đăng nhập).
4. Ánh xạ (mapper) các bước văn xuôi nghiệp vụ thành hành động máy có thể thực thi (`http.request`, `ui.click`, `ui.fill`, `assert.*`).
5. Thực thi song song hoặc tuần tự các testcase trên API/HTTP và trình duyệt Chromium thật với ngữ cảnh cô lập (mỗi testcase một context riêng), tự động thu thập bằng chứng (ảnh chụp màn hình, Playwright trace zip, log console, request lỗi).
6. Xuất báo cáo đa định dạng (`report.md`, `junit.xml`, `results.csv`, `results.json`) và **ghi kết quả ngược vào chính template Excel 14 cột** của tổ chức (mô hình bản ghi hai pha).

### Input chính là gì?

1. **Tài liệu đặc tả yêu cầu**: Thư mục chứa các file Markdown (`urd.md`, `srs.md`, và các tài liệu phụ như sequence diagrams, state machines, bảng decision table trong `brainstorms/*.md` hoặc `srs/*flow*.md`).
2. **OpenAPI Spec (OAS)**: File OpenAPI YAML/JSON (ví dụ `openapi.yaml`) mô tả schemas, endpoints, methods, headers, status codes, query/path parameters, và các extension nội bộ (`x-qc-id`, `x-qc-priority`, `x-qc-latency-p95-ms`, `x-external`).
3. **Địa chỉ webapp / API base URL**: `--web-url` (để crawl DOM và chạy Chromium), `--base-url` (để gọi zxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxaAPI HTTP).
4. **Thông tin xác thực (Credentials)**: Tên đăng nhập, mật khẩu, Bearer token (lấy từ tham số CLI, file cấu hình `qctool.yaml`, hoặc file môi trường `.env`).

### Output chính là gì?

1. `requirements.yaml`: Manifest yêu cầu chuẩn hoá đã bóc tách từ markdown kèm `content_hash`, `source_ids`, trích dẫn dòng/file gốc.
2. `ui-map.yaml`: Bản đồ các element tương tác được trên webapp, gắn kèm `test_id` (`data-testid`), role, name, href, tag, selector.
3. `testcases.yaml`: Toàn bộ bộ testcase ở định dạng Testcase IR (Intermediate Representation) độc lập.
4. `testcases.xlsx`: Bảng testcase chuẩn 14 cột theo template Excel của team (10 cột sinh trước + 4 cột kết quả runtime được ghi ngược vào sau khi chạy).
5. `artifacts/<feature>/runs/<timestamp>/`:
   - `report.md`: Báo cáo kiểm thử tổng quan, thống kê lỗi, test chập chờn, test bị chặn, hướng dẫn tái hiện.
   - `results.json`: Kết quả chi tiết máy đọc được.
   - `results.csv`: Dữ liệu bảng phẳng để mở nhanh hoặc pivot table.
   - `junit.xml`: Kết quả chuẩn JUnit XML để tích hợp vào CI/CD pipeline (Jenkins, GitLab CI, GitHub Actions).
6. `artifacts/<feature>/evidence/`: Ảnh chụp màn hình khi fail/pass (`<TC_ID>-fail.png`), Playwright trace (`<TC_ID>.trace.zip`), snapshot bối cảnh lỗi.

### Luồng xử lý end-to-end từ khi nhận input đến khi có kết quả

Toàn bộ luồng được orchestrate bởi `qctool/pipeline.py::run_pipeline()`:

1. **Ingest Phase**: Quét tài liệu markdown (URD/SRS), bóc tách User Stories, Acceptance Criteria (Given/When/Then), Functional Requirements, Non-Functional Requirements (NFR), và các sơ đồ Mermaid/bảng trạng thái → lưu `requirements.yaml`.
2. **Generate Phase**:
   - Track 1 (OpenAPI): Nạp spec, giải quyết `$ref`/`allOf`, sinh testcase Happy Path, mã lỗi (400, 401, 403, 404, 409, 422, 500), biên tham số (BVA), thiếu trường bắt buộc, ma trận xác thực (Auth Matrix).
   - Track 2 (Requirements): Sinh testcase từ Acceptance Criteria, NFR đo được (`p95 < 100ms`).
   - Track 3 (Flows & Functions): Sinh testcase từ sequence diagrams, decision points, state transitions, và bảng error handling.
   - Batch Validation: Kiểm tra trùng ID, trùng nội dung, gap requirement, case mồ côi (orphan), validate action vocabulary.
   - Xuất sơ bộ ra `testcases.yaml` và `testcases.xlsx` (10 cột đầu).
3. **Crawl & Mapping Phase (2b)**:
   - Nếu có `--web-url` và có case cần map: Mở Chromium crawl webapp (Pha 1: anonymous; Pha 2: nạp cookie/storage-state sau khi login).
   - Lưu `ui-map.yaml`.
   - Chạy `mapper.py`: Phân tích câu văn xuôi của testcase, đối chiếu với element có thật trong `ui-map.yaml` và endpoint có thật trong OpenAPI → nâng cấp các bước `perform.unmapped`/`assert.unmapped` thành `ui.click`, `ui.fill`, `ui.goto`, `http.request`, `assert.url_matches`, `assert.text`... Case map hoàn tất được chuyển từ `execution: manual` sang `execution: auto`.
4. **Execute Phase**:
   - Khởi tạo `HttpSession` (với HTTP keep-alive, header UA tùy biến).
   - Khởi tạo `BrowserSession` (Playwright Chromium) nếu bộ test có chứa `UI_VERBS`.
   - Với mỗi case: Kiểm tra precondition/requires (nếu thiếu tài khoản/môi trường → gán `Blocked`). Nếu là case UI: tạo context trình duyệt riêng biệt (`start_case`), thực thi từng bước (dùng `expect()` tự chờ), bắt lỗi console/network, nếu fail thì chụp ảnh và lưu trace (`end_case`).
   - Hỗ trợ retry (0–3 lần) để phát hiện và gắn cờ `flaky` riêng biệt.
5. **Report & Backfill Phase**:
   - Ghi `results.json`, `results.csv`, `junit.xml`, `report.md`.
   - Gọi `render.fill_results()` để nạp lại `testcases.xlsx` và điền 4 cột runtime: `Actual Result`, `Status` (Pass/Fail/Blocked/Not Executed kèm format màu), `Environment`, `Executed By / Date`.

### Thành phần nào là core của hệ thống?

- **Testcase IR (`TestCase` & `Step` dataclass trong `qctool/testcase.py`)**: Đây là "trái tim" dữ liệu của toàn bộ tool. Mọi generator đều phải dịch ra format IR này và mọi executor/renderer đều đọc từ IR này.
- **Closed Action Vocabulary (`ACTION_SPECS` trong `qctool/testcase.py`)**: Bộ từ vựng đóng gồm 25 verbs. Bất kỳ step nào dùng verb ngoài danh mục này đều bị chặn ngay tại tầng validation.
- **Pipeline Runner (`qctool/pipeline.py::run_pipeline()`)**: Điểm nối duy nhất điều phối toàn bộ 4 chặng và chia sẻ chung giữa CLI, Web UI và CI.

### Có những worker/module/service chính nào?

1. `qctool.ingest`: Worker đọc và chuẩn hoá tài liệu markdown (`markdown.py`, `flows.py`, `ids.py`).
2. `qctool.generate`: Worker sinh testcase từ OpenAPI, requirements, flows và bộ ánh xạ (`loader.py`, `from_openapi.py`, `from_requirements.py`, `from_flows.py`, `from_functions.py`, `mapper.py`).
3. `qctool.ui`: Worker crawl cấu trúc DOM trang web thành `UIMap` (`crawl.py`).
4. `qctool.execute`: Engine thực thi testcase HTTP và Browser Playwright (`runner.py`, `browser.py`).
5. `qctool.validate`: Engine kiểm tra tính toàn vẹn và chất lượng bộ test trước khi chạy (`validate.py`).
6. `qctool.render`: Module xuất và cập nhật file Excel 14 cột (`excel.py`, `results.py`).
7. `qctool.report`: Module xuất báo cáo Markdown, JUnit XML, CSV, JSON (`report/__init__.py`).
8. `qctool.web`: Web server phục vụ giao diện điều khiển local (`web/app.py`).

### Sơ đồ End-to-End Flow (Text/ASCII)

```text
[ urd.md / srs.md / brainstorms ]              [ openapi.yaml ]
                 │                                      │
                 ▼ (ingest)                             │
       requirements.yaml                                │
                 │                                      │
                 ├──────────────────────┬───────────────┘
                 │                      │
                 ▼ (generate track 2,3) ▼ (generate track 1)
         [ Unmapped Testcases ]   [ Deterministic API Testcases ]
                 │                              │
                 └──────────────┬───────────────┘
                                │
                                ▼
                        testcases.yaml (IR) ──► render ──► testcases.xlsx
                                │                           (10 cột gen)
                                │
   [ webapp URL ]               │
         │                      │
         ▼ (crawl)              │
    ui-map.yaml                 │
         │                      │
         └──────────► mapper.py ┘
                         │
                         ▼
             Executable Testcases (IR)
                         │
                         ▼ (execute: runner.py)
         ┌───────────────────────────────┐
         │                               │
         ▼ (HTTP API)                    ▼ (Playwright Chromium)
    HttpSession                   BrowserSession
 (keep-alive, urllib)         (isolated context/case,
         │                     auto-wait expect, traces)
         │                               │
         └───────────────┬───────────────┘
                         │
                         ▼
                     RunResult
                         │
       ┌─────────────────┼───────────────────────────────┐
       ▼                 ▼                               ▼
  report.md          junit.xml                       results.csv
  results.json       evidence/*.png, *.trace.zip         │
                                                         ▼ (render: results.py)
                                                   testcases.xlsx
                                                   (điền ngược 4 cột runtime)
```

---

# 2. Entry point và execution flow

### Bắt đầu chạy từ file/function nào?

- **Console Script Entry Point**: Được định nghĩa trong `pyproject.toml`: `qctool = "qctool.cli:main"`.
- **Python Module Entry Point**: `qctool/__main__.py` gọi `sys.exit(main())` từ `qctool/cli.py`.

### Các CLI Commands / Subcommands

Parser trong `qctool/cli.py` định nghĩa 6 lệnh chính:

1. `qctool all` (`cmd_all`) — Chạy toàn bộ pipeline tự động.
2. `qctool ingest` (`cmd_ingest`) — Chỉ ingest tài liệu markdown thành `requirements.yaml`.
3. `qctool generate` (`cmd_generate`) — Chỉ sinh testcase ra `testcases.yaml` & `testcases.xlsx`.
4. `qctool run` (`cmd_run`) — Chạy tập `testcases.yaml` có sẵn trên một môi trường.
5. `qctool crawl` (`cmd_crawl`) — Crawl cấu trúc webapp ra `ui-map.yaml`.
6. `qctool serve` (`cmd_serve`) — Khởi chạy local Web server UI trên cổng 8080.

---

### Chi tiết Execution Flow 1: Full Pipeline (`qctool all`)

```text
qctool/cli.py::main()
  ↓
qctool/cli.py::cmd_all()
  ↓
qctool/pipeline.py::PipelineConfig.from_file()
  ↓
qctool/pipeline.py::run_pipeline()
  ├─► qctool/ingest/__init__.py::ingest_feature()
  │     └─► qctool/ingest/markdown.py::parse_markdown()
  │     └─► qctool/ingest/flows.py::extract()
  │     └─► qctool/ingest/__init__.py::write_yaml()
  │
  ├─► qctool/generate/__init__.py::generate_all()
  │     ├─► qctool/generate/from_requirements.py::generate_from_acceptance()
  │     ├─► qctool/generate/from_requirements.py::generate_from_nfr()
  │     ├─► qctool/generate/from_functions.py::generate_from_functions()
  │     ├─► qctool/generate/from_flows.py::generate_from_flows()
  │     ├─► qctool/generate/loader.py::load_endpoints()
  │     ├─► qctool/generate/from_openapi.py::generate_for_endpoint()
  │     └─► qctool/validate.py::validate_batch()
  │
  ├─► qctool/ui/crawl.py::crawl() (nếu có web_url)
  │
  ├─► qctool/generate/mapper.py::map_testcases() (nếu có ui_map)
  │
  ├─► qctool/generate/__init__.py::write_cases() (testcases.yaml)
  ├─► qctool/render/excel.py::render() (testcases.xlsx 10 cột đầu)
  │
  ├─► qctool/execute/browser.py::BrowserSession() (nếu có bước UI)
  ├─► qctool/execute/runner.py::HttpSession()
  ├─► qctool/execute/runner.py::run_cases()
  │     └─► qctool/execute/runner.py::run_case()
  │           ├─► qctool/execute/runner.py::_run_step() (HTTP / asserts)
  │           └─► qctool/execute/runner.py::_run_ui_step() (Browser dispatch)
  │
  ├─► qctool/report/__init__.py::write_json(), write_csv(), write_junit(), render_markdown()
  └─► qctool/render/results.py::fill_results() (ghi ngược kết quả vào testcases.xlsx)
```

**Bảng chi tiết các bước trong Full Pipeline Flow:**

| Bước | File Path                     | Class/Function                                              | Nhiệm vụ                                          | Input                         | Output                                      |
| ---- | ----------------------------- | ----------------------------------------------------------- | ------------------------------------------------- | ----------------------------- | ------------------------------------------- |
| 1    | `qctool/cli.py`               | `cmd_all(args)`                                             | Parse CLI arguments hoặc đọc `qctool.yaml`        | `argparse.Namespace`          | Exit code int (0 hoặc 1/2)                  |
| 2    | `qctool/pipeline.py`          | `PipelineConfig.from_file(path)`                            | Nạp cấu hình YAML, kết hợp biến môi trường `.env` | `Path(config_path)`           | `PipelineConfig` instance                   |
| 3    | `qctool/pipeline.py`          | `run_pipeline(cfg, on_progress)`                            | Nhạc trưởng điều phối 4 chặng                     | `PipelineConfig`, callback    | `PipelineResult`                            |
| 4    | `qctool/ingest/__init__.py`   | `ingest_feature(docs_dir, feature)`                         | Phân tích cây thư mục markdown, trích requirement | `Path(docs_dir)`, tên feature | `dict` cấu trúc manifest                    |
| 5    | `qctool/generate/__init__.py` | `generate_all(req_path, api_path, module)`                  | Sinh testcase từ requirements và OAS spec         | Paths tới YAML spec           | `tuple[list[TestCase], Report, dict]`       |
| 6    | `qctool/ui/crawl.py`          | `crawl(base_url, ...)`                                      | Dò DOM trang web bằng Playwright qua 2 pha        | URL web, storage_state        | `UIMap` instance                            |
| 7    | `qctool/generate/mapper.py`   | `map_testcases(cases, ui_map, ...)`                         | Map văn xuôi sang hành động máy cụ thể            | `list[TestCase]`, `UIMap`     | `MapStats` (sửa trực tiếp in-place `cases`) |
| 8    | `qctool/render/excel.py`      | `render(cases, out_path)`                                   | Vẽ template Excel 14 cột, nạp 10 cột spec         | `list[TestCase]`, `Path`      | File `testcases.xlsx`                       |
| 9    | `qctool/execute/runner.py`    | `run_cases(cases, session, browser, ...)`                   | Vòng lặp chạy từng testcase                       | `list[TestCase]`, sessions    | `RunResult`                                 |
| 10   | `qctool/report/__init__.py`   | `write_json`, `write_csv`, `write_junit`, `render_markdown` | Kết xuất các file báo cáo                         | `RunResult`, `Path`           | Các file report trên đĩa                    |
| 11   | `qctool/render/results.py`    | `fill_results(xlsx_path, result)`                           | Nạp file `.xlsx`, ghi đè 4 cột runtime            | `Path(xlsx)`, `RunResult`     | Cập nhật `testcases.xlsx`                   |

---

### Chi tiết Flow 2: Ingest Phase (`qctool ingest`)

- **Entry point**: `qctool/cli.py` -> `cmd_ingest(args)`.
- **Luồng gọi**:
  1. `cmd_ingest()` kiểm tra `feature_dir.is_dir()`.
  2. Gọi `qctool/ingest/__init__.py`: `ingest_feature(feature_dir, feature)`.
  3. Nếu `feature_dir` chứa `urd.md`/`srs.md` trực tiếp: gọi `ingest_one(feature_dir, feature)`. Nếu là thư mục mẹ chứa nhiều feature con: gọi `discover_features()` rồi `ingest_tree()`.
  4. Trong `ingest_one()`:
     - Gọi `qctool/ingest/markdown.py`: `parse_markdown()` phân loại `urd` (gọi `parse_urd()` parse User Stories và bảng Acceptance Criteria) và `srs` (gọi `parse_srs_functions()`, `parse_srs_responses()`, `parse_srs_nfr()`).
     - Chuẩn hoá ID qua `qctool/ingest/ids.py`: `canonical(raw_id, feature)`.
     - Gọi `qctool/ingest/flows.py`: `extract()` bóc tách Mermaid diagrams (sequence, flowchart, state), bảng decision points, transition tables, error surfaces, và numbered core flows.
     - Tính toán `content_hash` cho từng Requirement (`qctool/model.py`).
  5. Gọi `ingest.write_yaml(data, out)` ghi file `artifacts/<feature>/requirements.yaml`.

---

### Chi tiết Flow 3: Generate Phase (`qctool generate`)

- **Entry point**: `qctool/cli.py` -> `cmd_generate(args)`.
- **Luồng gọi**:
  1. Gọi `qctool/generate/__init__.py`: `generate_all(req_path, api_path, module_override)`.
  2. Nạp requirements nếu có:
     - Gọi `generate_from_acceptance()` trong `qctool/generate/from_requirements.py`: tạo các testcase Given/When/Then (trạng thái `execution="manual"`, verb `perform.unmapped` và `assert.unmapped`).
     - Gọi `generate_from_functions()` trong `qctool/generate/from_functions.py`: tạo testcase từ flow chức năng và bảng error handling.
     - Gọi `generate_from_nfr()` trong `qctool/generate/from_requirements.py`: lọc các NFR có ngưỡng đo định lượng (`assert.response_time`).
     - Gọi `generate_from_flows()` trong `qctool/generate/from_flows.py`: sinh testcase đa bước từ sequence diagrams và sinh 2 case cho mỗi decision point (nhánh Yes/No).
  3. Nạp OpenAPI nếu có:
     - Gọi `load_endpoints()` trong `qctool/generate/loader.py`: load YAML spec, resolve đệ quy `$ref`, bóc tách schema request/response, bỏ qua operation có `x-external: true`.
     - Với mỗi endpoint: gọi `generate_for_endpoint()` trong `qctool/generate/from_openapi.py`:
       - 1 Happy Path (`http.request` -> `assert.http_status`, `assert.json_schema`).
       - Error Codes (`_can_trigger()` kiểm tra xem có khả năng tạo input kích hoạt lỗi không; mã 403/404/409/500 được gắn cờ `requires`).
       - Boundary Value Analysis (BVA) trên query params và body properties (`minLength`, `maxLength`, `minimum`, `maximum`, `enum`).
       - Missing Required Field tests.
       - Auth Matrix test (gọi không token mong đợi 401).
  4. Traceability Linking: Gọi `_link_api_cases()` gắn các case API về FR ID tương ứng.
  5. Validation Guard: Gọi `qctool/validate.py`: `validate_batch()` kiểm tra lỗi ID trùng, nội dung trùng lặp (`content_hash`), orphan cases, coverage gaps.
  6. Xuất ra file `testcases.yaml` và nếu có cờ `--xlsx` thì gọi `render.render()` tạo `testcases.xlsx`.

---

### Chi tiết Flow 4: Execute Phase (`qctool run`)

- **Entry point**: `qctool/cli.py` -> `cmd_run(args)`.
- **Luồng gọi**:
  1. Nạp testcases từ file YAML qua `_load_cases()`.
  2. Tạo `HttpSession(base_url, bearer_token)`.
  3. Kiểm tra `needs_browser(cases)`: Nếu có bất kỳ action nào thuộc `UI_VERBS`, gọi `_open_browser()` để khởi tạo `BrowserSession(web_url, ...)` và đăng nhập nếu có `--login`.
  4. Gọi `qctool/execute/runner.py`: `run_cases()`.
  5. Vòng lặp từng case qua `run_case()`:
     - Nếu `case.execution == "manual"` -> gán `STATUS_NOT_EXECUTED`.
     - Nếu `case.requires` hoặc `case.needs_mapping` còn tồn tại -> gán `STATUS_BLOCKED`.
     - Nếu chạy UI: gọi `browser.start_case(case.id)` tạo browser context riêng biệt.
     - Chạy tuần tự các bước:
       - HTTP step: gọi `session.request()` -> kiểm tra status code, parse json, đo thời gian.
       - UI step: gọi `_run_ui_step()` chuyển tiếp sang `browser.click()`, `browser.fill()`, `browser.url_matches()`...
       - Assert step: so sánh dữ liệu hoặc gọi Playwright `expect()` tự chờ.
     - Bắt exception `NeedsEnvironment` (lỗi mạng test máy, không nạp được axe) -> đổi status thành `STATUS_BLOCKED` kèm lý do.
     - Nếu case fail và có cấu hình retry: chạy lại tối đa $N$ lần. Nếu pass ở lần sau -> status vẫn là `STATUS_PASS` nhưng bật cờ `flaky = True`.
     - Đóng context bằng `browser.end_case()`, chụp screenshot và zip trace file nếu bật.
  6. Xuất báo cáo qua `report.write_json()`, `write_csv()`, `write_junit()`, `render_markdown()`.
  7. Gọi `render.fill_results()` ghi ngược dữ liệu runtime vào file `.xlsx`.

---

### Chi tiết Flow 5: Crawl UI (`qctool crawl`)

- **Entry point**: `qctool/cli.py` -> `cmd_crawl(args)`.
- **Luồng gọi**:
  1. Gọi `qctool/ui/crawl.py`: `crawl(url, ...)`.
  2. Khởi tạo Playwright Chromium.
  3. **Pha 1 (Chưa đăng nhập)**: Duyệt các route ẩn danh (`/`, `/login`), chờ `_wait_for_render()`, tìm tất cả thẻ `button`, `a`, `input`, `select`, `textarea`. Trích xuất thuộc tính `data-testid`, name, role, href, disabled. Theo dõi link nội bộ (`_follow`).
  4. **Pha 2 (Sau khi đăng nhập)**: Nếu có file `storage_state`, nạp context mới có auth và crawl tiếp các protected routes (`/`, các extra paths trích từ SRS/URD).
  5. Gom thành đối tượng `UIMap` chứa danh sách `PageMap` và các `Element`.
  6. Lưu kết quả ra file YAML qua `ui_map.save(out_path)`.

---

### Chi tiết Flow 6: Web UI (`qctool serve`)

- **Entry point**: `qctool/cli.py` -> `cmd_serve(args)`.
- **Luồng gọi**:
  1. Gọi `qctool/web/app.py`: `serve(port, host, open_browser)`.
  2. Chạy `ThreadingHTTPServer` phục vụ giao diện Single-Page HTML thuần không phụ thuộc framework ngoài.
  3. API endpoints:
     - `GET /api/status`: Trả về trạng thái cấu hình hiện tại, danh sách features có sẵn trong `materials/review-docs` và specs trong `materials/review-oas`.
     - `POST /api/run`: Nhận payload cấu hình chạy, tạo một `Job` bất đồng bộ trong `STORE = JobStore()`, chạy thread ngầm gọi trực tiếp `run_pipeline(cfg, on_progress=job.log)`.
     - `GET /api/jobs/<job_id>`: Polling tiến trình log realtime và kết quả `PipelineResult`.

---

# 3. Kiến trúc thư mục

### Cây thư mục rút gọn

```text
qc-tool/
├── pyproject.toml                     # Cấu hình project, entry points, dependencies (openpyxl, playwright, pyyaml)
├── qctool.example.yaml                # File cấu hình mẫu đầy đủ các tham số pipeline
├── qc.sh                              # Bash script wrapper tiện dụng cho người dùng cuối
├── scripts/
│   ├── build_testcase_template.py     # Script sinh tự động template Excel 14 cột chuẩn
│   └── validate_openapi.py            # Tiện ích CLI kiểm tra tính hợp lệ của file OpenAPI spec
├── templates/
│   ├── testcase/
│   │   └── testcase-template.xlsx     # Template Excel 14 cột mẫu (sinh từ script)
│   ├── api/
│   │   └── openapi-template.yaml      # Template OpenAPI mẫu để người dùng điền
│   └── report/
│       └── report-template.md         # Template định dạng báo cáo markdown
├── samples/
│   └── openapi/
│       └── task-manager-sample.yaml   # Spec OpenAPI giả lập (hư cấu) đầy đủ case phức tạp để test tool
├── tests/
│   ├── mock_server.py                 # Mock server HTTP + HTML chứa sẵn 4 bug API + 4 bug UI
│   ├── test_browser.py                # Test Playwright mở Chromium thật kiểm tra phát hiện bug UI
│   ├── test_execute.py                # Test runner HTTP và assertion engine
│   ├── test_generate.py               # Test logic sinh testcase từ OAS và requirements
│   ├── test_ingest.py                 # Test parser markdown, flow diagrams và NFRs
│   ├── test_mapper.py                 # Test logic ánh xạ văn xuôi sang executable verbs
│   └── test_pipeline.py               # Test tích hợp end-to-end run_pipeline()
└── qctool/                            # SOURCE CODE CHÍNH
    ├── __init__.py                    # Khai báo version (0.0.1)
    ├── __main__.py                    # Entry point cho lệnh `python -m qctool`
    ├── cli.py                         # Parser CLI argparse, xử lý subcommands (all, ingest, generate, run, crawl, serve)
    ├── config.py                      # Load cấu hình từ .env, biến môi trường, validation auth modes
    ├── model.py                       # Data models lõi cho Ingest: Requirement, ApiSpec, SourceRef, content_hash
    ├── testcase.py                    # Data models lõi cho Testcase IR: TestCase, Step, ACTION_SPECS, StepKind, Priority
    ├── validate.py                    # Cửa kiểm soát chất lượng: validate_batch, orphan/duplicate/gap check
    ├── pipeline.py                    # Orchestrator trung tâm run_pipeline() nối 4 chặng
    ├── ingest/                        # CHẶNG 1: INGEST
    │   ├── __init__.py                # Ingest orchestrator: ingest_feature, discover_features, ingest_tree
    │   ├── markdown.py                # Parser cú pháp markdown URD/SRS (User story, Given/When/Then, NFRs)
    │   ├── flows.py                   # Parser luồng: Mermaid diagrams, state transitions, decision tables
    │   └── ids.py                     # Chuẩn hoá và cấp ID canonical: FR-{feature}-{NNN}, AC, US, NFR
    ├── generate/                      # CHẶNG 2: GENERATE
    │   ├── __init__.py                # Generator orchestrator: generate_all, write_cases
    │   ├── loader.py                  # Load OpenAPI spec, resolve đệ quy $ref/allOf, bóc tách operation
    │   ├── from_openapi.py            # Sinh testcase API: Happy path, BVA, Error codes, Auth matrix
    │   ├── from_requirements.py       # Sinh testcase từ Acceptance Criteria và NFR đo được
    │   ├── from_functions.py          # Sinh testcase từ Functional SRS và bảng error handling
    │   ├── from_flows.py              # Sinh testcase UI từ luồng Mermaid, decision points, state machines
    │   └── mapper.py                  # Mapper: ánh xạ văn xuôi (unmapped) sang executable actions dựa vào UIMap
    ├── ui/                            # BẢN ĐỒ GIAO DIỆN
    │   ├── __init__.py
    │   └── crawl.py                   # Crawler Playwright 2 pha trích xuất tương tác DOM -> UIMap
    ├── execute/                       # CHẶNG 3: EXECUTE
    │   ├── __init__.py
    │   ├── runner.py                  # Test runner điều phối HTTP và Browser execution, retry, soft asserts
    │   └── browser.py                 # Wrapper Playwright quản lý context, locator strategy, auto-wait expect, traces
    ├── render/                        # ADAPTER XUẤT EXCEL
    │   ├── __init__.py
    │   ├── excel.py                   # Render Testcase IR sang file Excel 14 cột theo chuẩn openpyxl
    │   └── results.py                 # Ghi kết quả chạy ngược vào 4 cột runtime của file Excel
    ├── report/                        # CHẶNG 4: REPORT
    │   └── __init__.py                # Kết xuất report.md, junit.xml, results.csv, results.json
    └── web/                           # GIAO DIỆN WEB LOCAL
        ├── __init__.py
        └── app.py                     # Local web server HTTP phục vụ UI và background job runner
```

---

# 4. Các artifact trung gian

Hệ thống có thiết kế phân tách trạng thái rõ ràng giữa các pha qua các artifact sau:

| Tên Artifact                              | Sinh ra ở đâu?                                                          | Ai đọc nó?                                                                              | Schema / Cấu trúc dữ liệu                                                                                                                  | Source of truth?                            | Disk hay Memory?                             | Phase sử dụng      | Model Python đại diện                                                |
| ----------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------- | -------------------------------------------- | ------------------ | -------------------------------------------------------------------- |
| `requirements.yaml`                       | `qctool/ingest/__init__.py::write_yaml()`                               | `qctool/generate/__init__.py::generate_all()`, `qctool/pipeline.py::_paths_from_docs()` | Dict gồm `feature`, `counts`, `sources`, `flows`, `requirements: list[dict]`                                                               | **CÓ** (cho pha requirements)               | Disk (trong `artifacts/<feature>/`)          | Ingest → Generate  | `Requirement`, `ApiSpec`, `SourceRef` (`qctool/model.py`)            |
| `ui-map.yaml`                             | `qctool/ui/crawl.py::UIMap.save()`                                      | `qctool/generate/mapper.py::map_testcases()`, `qctool/pipeline.py`                      | Dict gồm `base_url`, `crawled_at`, `pages: list[PageMap]` chứa các `Element`                                                               | **CÓ** (cho cấu trúc DOM webapp)            | Disk (trong `artifacts/<feature>/`)          | Crawl → Map        | `UIMap`, `PageMap`, `Element` (`qctool/ui/crawl.py`)                 |
| `testcases.yaml`                          | `qctool/generate/__init__.py::write_cases()`                            | `qctool/cli.py::cmd_run()`, `qctool/execute/runner.py`                                  | Dict gồm `summary`, `sources`, `testcases: list[dict]` (mỗi testcase chứa ID, title, steps, expected, provenance...)                       | **CÓ** (cho định dạng Testcase IR thực thi) | Disk (trong `artifacts/<feature>/`)          | Generate → Execute | `TestCase`, `Step`, `StepKind`, `Priority` (`qctool/testcase.py`)    |
| `testcases.xlsx` (Pha 1)                  | `qctool/render/excel.py::render()`                                      | Người dùng QC review, hoặc `render/results.py`                                          | Excel 14 cột chuẩn: 10 cột đầu có dữ liệu, 4 cột runtime để trống                                                                          | Không (là bản render ra cho người dùng)     | Disk                                         | Generate           | Được chuyển đổi từ `list[TestCase]`                                  |
| `.auth-state.json`                        | `qctool/execute/browser.py::save_state()`                               | `qctool/pipeline.py`, `qctool/execute/browser.py::start_case()`                         | JSON lưu `cookies` và `localStorage`/`origins` của Playwright                                                                              | Có (cho session người dùng)                 | Disk (trong `artifacts/<feature>/`)          | Crawl & Execute    | JSON file format chuẩn của Playwright                                |
| `.token`                                  | `qctool/pipeline.py::run_pipeline()` (bắt từ `browser.extract_token()`) | `qctool/pipeline.py` truyền cho `HttpSession`                                           | Plain text chứa Bearer JWT access token                                                                                                    | Không (dùng tạm cho lượt chạy)              | Disk (trong `artifacts/<feature>/`)          | Crawl → Execute    | `str`                                                                |
| `testcases.xlsx` (Pha 2)                  | `qctool/render/results.py::fill_results()`                              | Người dùng QC đọc báo cáo cuối cùng                                                     | Excel 14 cột: điền đầy đủ cả 4 cột runtime (`Actual Result`, `Status`, `Environment`, `Executed By / Date`) kèm màu conditional formatting | **CÓ** (cho báo cáo bàn giao team QC)       | Disk                                         | Report             | Được ghi từ `RunResult`                                              |
| `results.json`                            | `qctool/report/__init__.py::write_json()`                               | Hệ thống phân tích log / CI                                                             | Dict chứa `started_at`, `finished_at`, `summary`, danh sách `results` chi tiết từng step                                                   | Có (dữ liệu thô kết quả)                    | Disk (trong `runs/<timestamp>/`)             | Report             | `RunResult`, `CaseResult`, `StepResult` (`qctool/execute/runner.py`) |
| `junit.xml`                               | `qctool/report/__init__.py::write_junit()`                              | CI/CD engines (Jenkins/GitLab)                                                          | XML format chuẩn JUnit `testsuite` / `testcase`                                                                                            | Không (báo cáo phụ trợ)                     | Disk (trong `runs/<timestamp>/`)             | Report             | Sinh từ `RunResult`                                                  |
| `results.csv`                             | `qctool/report/__init__.py::write_csv()`                                | Excel import / Data analyst                                                             | CSV format: `Mã test, Module, Tên test, Kết quả, Thời gian (ms), Thực tế, Ghi chú, Bằng chứng, Chập chờn`                                  | Không (báo cáo phụ trợ)                     | Disk (trong `runs/<timestamp>/`)             | Report             | Sinh từ `RunResult`                                                  |
| `report.md`                               | `qctool/report/__init__.py::render_markdown()`                          | Tech Lead, PM, Developer đọc                                                            | Markdown định dạng chuẩn, chia 7 mục: Tóm tắt, Module, Lỗi, Cần chạy tay, Bị chặn, Chập chờn, Bằng chứng                                   | Có (báo cáo tổng quan cho người đọc)        | Disk (trong `runs/<timestamp>/`)             | Report             | Sinh từ `RunResult`                                                  |
| `evidence/<case_id>-*.png` & `.trace.zip` | `qctool/execute/browser.py`                                             | Developer xem chi tiết bug UI                                                           | Binary file PNG và Playwright Trace ZIP                                                                                                    | Có (bằng chứng thực tế)                     | Disk (trong `artifacts/<feature>/evidence/`) | Execute → Report   | `Evidence` (`qctool/execute/browser.py`)                             |

---

# 5. Requirement / input processing

### Input gồm những gì và parser nằm ở đâu?

- **Tài liệu Markdown**:
  - `urd.md`: Được parse bởi hàm `parse_urd()` trong `qctool/ingest/markdown.py`. Sử dụng regex `H_US = re.compile(r"^###\s+(US-\d{3})\s+—\s+(.+?)\s*$")` để lấy User Story (`As a`, `I want`, `So that`). Sau đó đọc bảng Acceptance Criteria dưới dạng hàng bảng markdown `| AC-001-1 | Given | When | Then |`.
  - `srs.md`: Được parse bởi `parse_srs_functions()`, `parse_srs_responses()`, và `parse_srs_nfr()` trong `qctool/ingest/markdown.py`. Bóc tách `#### 3.2.x F-01 Function`, bảng `Flow`, bảng `Request`, bảng `Response 200`, bảng `Error responses`, bảng `Error handling`, và bảng `NFR-SEC`, `NFR-PERF`, `NFR-AVAIL`, `NFR-I18N`, `NFR-OBS`.
  - `flows / brainstorms`: Được parse bởi `qctool/ingest/flows.py` (`extract()`). Bóc tách cú pháp Mermaid Sequence (`A->>B: msg`), State Diagram (`[*] --> Active: event`), Decision Point Tables (cột `Condition`, `Yes`, `No`), Transition Tables, Error Surface Tables.
- **OpenAPI Spec (YAML/JSON)**: Được parse bởi `qctool/generate/loader.py` (`load_endpoints()`).

### Clean, Normalize, Merge và Schema trung gian

- **Tách cell markdown an toàn**: Hàm `_cells()` trong `qctool/ingest/markdown.py` xử lý đặc biệt dấu `\|` để không làm vỡ các kiểu union như `string\|null` trong bảng markdown.
- **Normalize ID**: `qctool/ingest/ids.py` chuyển các ID ngắn và dễ xung đột thành ID canonical có namespace feature:
  - `US-001` -> `US-{feature}-001`
  - `AC-001-1` -> `AC-{feature}-001-1`
  - `F-01` -> `FR-{feature}-001`
  - `NFR-SEC-01` -> `NFR-{feature}-{index:03d}` (cấp số tuần tự duy nhất, giữ category `SEC` trong field riêng).
- **Loại bỏ trùng lặp (Deduplication)**: Hàm `_dedupe()` trong `qctool/ingest/__init__.py` giữ bản ghi đầu tiên nếu trùng ID và ghi warning.
- **Hệ thống content hashing**:
  - `Requirement._semantic_payload()` (`qctool/model.py`) chỉ băm các trường ngữ nghĩa (`id`, `kind`, `title`, `statement`, `category`, `given`, `when`, `then`, `traces_to`, `acceptance`, `api`).
  - **Cố ý KHÔNG băm `source.line`**: Để việc sửa chính tả hoặc chèn thêm dòng ở đầu file không làm đổi hash của các requirement khác.

### Xử lý thiếu thông tin, Fallback và Default

- Triết lý cốt lõi: **"Không đoán"**.
- Nếu Acceptance Criteria thiếu vế Given/When/Then: Bỏ qua và thêm vào `warnings`, không đoán vế còn lại (`from_requirements.py:64`).
- Nếu NFR không có ngưỡng định lượng (ví dụ "hệ thống phải thân thiện"): Đưa vào danh sách `unverifiable` và không sinh testcase (`from_requirements.py:134`).
- Nếu requirement không nêu rõ endpoint/element: Sinh testcase với action `perform.unmapped` và đánh dấu `execution="manual"`, runner sẽ không chạy tự động và báo cáo tách riêng vào mục "Cần người chạy thủ công" thay vì báo Fail giả (`from_requirements.py:81`).

### Phân tích riêng phần OAS / OpenAPI

- **Vị trí parse**: `qctool/generate/loader.py` (`load_spec()`, `resolve_ref()`, `load_endpoints()`).
- **Xử lý `$ref` và `allOf`**: Hàm `resolve_ref()` đệ quy thay thế các con trỏ JSON Pointer nội bộ (`#/components/schemas/...`). Theo dõi tập `_seen` để phát hiện và ném lỗi nếu có vòng lặp tham chiếu tròn (`$ref` cycle) (`loader.py:56`). Gộp danh sách `required` và `properties` trong mảng `allOf`.
- **Lưu trữ Endpoint**: Chuyển đổi thành dataclass `Endpoint` (`qctool/generate/from_openapi.py`) chứa method, path, operation_id, parameters (path/query), request_body schema, responses schema, và danh sách `servers` riêng ở cấp operation.
- **Có dùng OAS để sinh testcase không?** CÓ. Đây là nguồn sinh testcase API kỹ thuật chính:
  1. Happy path (mã 200/201/204).
  2. Các mã lỗi đã khai báo trong `responses` (400, 401, 403, 404, 409, 422, 500).
  3. Boundary Value Analysis (BVA) trên từng tham số và trường JSON body.
  4. Missing field tests cho các trường có tên trong mảng `required`.
  5. Auth matrix tests cho các operation có khai báo security.
- **Có dùng OAS để execute API test không?** CÓ. Trong chặng execute, các tham số method, path, headers, query, body được trích từ bước `http.request` (vốn đã được compile từ OAS) để `HttpSession` gửi request HTTP thật tới server.

---

# 6. Testcase generation

### Kỹ thuật sinh: Rule engine hay LLM?

- **100% Deterministic Rule Engine**: Kiểm tra trực tiếp toàn bộ source code cho thấy **hiện tại KHÔNG CÓ BẤT KỲ DÒNG CODE NÀO GỌI LLM**. Mọi testcase đều được sinh bằng rule engine thuần túy bằng Python và được đánh dấu cứng `generated_by: "engine"` (`testcase.py:600`, `README.md:38`).
- **Prompt**: Không có prompt nào trong codebase hiện tại.
- **Input cho Generator**:
  1. `requirements.yaml` (dữ liệu cấu trúc từ Ingest).
  2. Đối tượng `Endpoint` (từ OpenAPI parser).
  3. `flows` (các luồng, sơ đồ tuần tự, bảng quyết định từ tài liệu).
- **Structured Output / Schema**: Output là danh sách các thực thể `TestCase` và `Step` tuân thủ strict validation.

### Schema Testcase IR thực tế từ code

Trích xuất trực tiếp từ dataclass `TestCase` (`qctool/testcase.py:576`) và `Step` (`qctool/testcase.py:304`):

```yaml
# Schema thực tế của một testcase trong testcases.yaml
id: "TC_AUTH_001" # Quy ước: TC_<MODULE>_<NNN>
module: "AUTH" # Tên module/feature
title: "Lấy cấu hình xác thực — trả 200 khi dữ liệu hợp lệ"
objective: "Xác nhận «GET /auth/config» hoạt động đúng ở luồng chính"
priority: "High" # High | Medium | Low
type: "positive" # positive | negative | boundary | security | performance | state
technique:
  "equivalence_partitioning" # equivalence_partitioning | boundary_value | decision_table |
  # state_transition | acceptance_criterion | error_guessing |
  # schema_conformance | auth_matrix | performance_threshold
traces_to: # Traceability bắt buộc về requirement gốc
  - "FR-login-sso-001"
execution: "auto" # auto | manual (auto nếu máy chạy được, manual nếu còn bước chưa map)
preconditions: # Điều kiện tiên quyết
  - "Hệ thống đang chạy, dữ liệu nền đã sẵn sàng"
requires: null # Điều kiện môi trường thiếu (nếu có giá trị -> Blocked)
test_data: # Dữ liệu thử nghiệm
  preferred_locale: "vi"
steps: # Danh sách các bước tuần tự
  - seq: 1
    kind: "when" # given | when | then
    action: "http.request" # Phải nằm trong ACTION_SPECS (closed vocabulary)
    args:
      method: "GET"
      path: "/api/v1/auth/config"
      auth: "bearer"
      save_as: "res"
    note: ""
  - seq: 2
    kind: "then"
    action: "assert.http_status"
    args:
      expected: 200
      source: "res"
expected: # Render tự động từ các bước assert.*
  - "Hệ thống trả về HTTP 200"
content_hash: "sha256:a1b2c3d4e5f67890" # Hash ngữ nghĩa tính trên module, title, traces_to, steps
provenance: # Nguồn gốc sinh case
  source_quote: "GET /auth/config — Lấy cấu hình SSO"
  source_ref: "openapi:getAuthConfig"
# Các trường runtime (được điền sau khi execute):
status: "Pass" # Pass | Fail | Blocked | Not Executed
actual:
  - "[OK] GET /api/v1/auth/config → HTTP 200 (42ms, server 18ms)"
  - "[OK] HTTP 200 — đúng như mong đợi"
environment: "https://dev.example.com"
executed_by: "qc-tool"
executed_at: "2026-10-02 17:30:00"
created_by: "qc-tool"
created_at: "2026-10-02 17:00:00"
```

### Các representation của Testcase trong repo

1. **In-memory Model**: Class `TestCase` và `Step` (`qctool/testcase.py`) với đầy đủ methods: `validate()`, `describe()`, `expects()`, `steps_text()`, `expected_text()`, `content_hash()`.
2. **Persistence IR (`testcases.yaml`)**: File YAML chuẩn hoá dùng để lưu trữ trung gian và trao đổi giữa các phase.
3. **User Presentation (`testcases.xlsx`)**: Bản render 14 cột theo Excel spreadsheet để giao tiếp với con người (Product Owner, QA team, Stakeholders).

---

# 7. Từ testcase nghiệp vụ → testcase executable

Đây là cơ chế phức tạp và thông minh nhất của repository, nằm toàn bộ trong `qctool/generate/mapper.py`.

### Vấn đề bài toán

Khi sinh testcase từ tài liệu URD/SRS (Acceptance Criteria), các bước ban đầu chỉ là văn xuôi nghiệp vụ:

- _When_: `User mở /projects`
- _Then_: `Redirect /login?callback=%2Fprojects`
- _When_: `Bấm Sign in with Keycloak`
- _Then_: `Sang IdP`

Nếu để nguyên, executor máy tính không thể biết phải click vào đâu hoặc assert điều gì. Nếu để LLM đoán bừa selector, testcase sẽ sinh ra các selector ảo dẫn đến flake hoặc fail giả.

### Quy trình chuyển đổi: `Logical Testcase` → `Mapper` → `Executable Testcase`

```text
Logical Testcase (văn xuôi, execution="manual", actions="perform.unmapped", "assert.unmapped")
                                │
                                ▼
                    mapper.py::map_testcases()
  ┌─────────────────────────────────────────────────────────────┐
  │ 1. Xác định ngữ cảnh Session:                               │
  │    - Quét xem case có cần phiên ẩn danh không (Router guard, │
  │      check-sso, chưa login) -> Chèn step ui.session(mode=anon)│
  │    - Hay cần phiên đã đăng nhập -> ui.session(mode=auth)    │
  │                                                             │
  │ 2. Map Action (Vế WHEN):                                    │
  │    - Regex khớp HTTP endpoints có trong spec OAS            │
  │      -> http.request                                        │
  │    - Regex URL/Path (/login, /projects) -> ui.goto          │
  │    - Regex Click ("bấm X", "click Y") + ui_map.find(target) │
  │      -> ui.click(target=test_id, by_name=name)              │
  │    - Regex Fill ("nhập X vào Y") + ui_map.find(target)      │
  │      -> ui.fill(target=test_id, value=X)                    │
  │    - Nhãn trần kiểu tài liệu ("TopBar Sign Out")            │
  │      -> ui.click hoặc ui.goto                               │
  │                                                             │
  │ 3. Map Expectation (Vế THEN):                               │
  │    - Regex Redirect ("redirect /login")                     │
  │      -> assert.url_matches(pattern="/login")                │
  │    - Regex Visibility ("Nav Projects visible; Users hidden")│
  │      -> assert.visible(test_id), assert.not_visible(test_id)│
  │    - Regex Disabled ("nút Lưu bị vô hiệu hoá")              │
  │      -> assert.disabled(test_id)                            │
  │    - Regex NFR Performance ("/auth/config p95 < 100ms")     │
  │      -> assert.response_time(max_ms=100, samples=20)        │
  │    - Regex UX Errors ("không có lỗi JS")                    │
  │      -> assert.console_clean                                │
  │                                                             │
  │ 4. Kiểm tra điều kiện môi trường (Requires Guard):          │
  │    - Nếu case đòi hỏi quyền hạn (403, kiểm mục bị ẩn)       │
  │      -> case.requires = "Cần tài khoản KHÔNG có quyền..."   │
  │                                                             │
  │ 5. Đánh giá trạng thái thực thi:                            │
  │    - Nếu map hết tất cả bước unmapped:                      │
  │      case.execution = "auto" (máy chạy được!)               │
  │    - Nếu còn bước không thể map:                            │
  │      case.execution = "manual" (để người chạy tay)          │
  └─────────────────────────────────────────────────────────────┘
                                │
                                ▼
Executable Testcase (bộ verbs đóng, selector data-testid có thật từ DOM, máy chạy được)
```

### Các quy tắc cụ thể trong code:

1. **Độ ưu tiên của Locator**: Khi map với element trong `UIMap`, mapper gọi hàm `_target_of(element)` (`mapper.py:460`):
   - **Ưu tiên 1**: `test_id` (`data-testid`, `data-test-id`, `data-cy`). Đây là định danh bền nhất không bị vỡ khi giao diện đổi chữ.
   - **Ưu tiên 2**: `id` và nhãn hiển thị `by_name`.
2. **Resolve test data**:
   - Dữ liệu sinh từ schema (`_sample_value()` trong `from_openapi.py:154`): sinh UUID mẫu (`3f2504e0-4f89-11d3-9a0c-0305e82c3301`), email (`user@example.com`), ISO date-time, hoặc chuỗi độ dài `minLength`.
   - Với BVA: sinh giá trị vi phạm biên (`minLength - 1`, `maxLength + 1`, `minimum - 1`, chuỗi rỗng `""`, enum sai `__not_in_enum__`).
   - Với body lỗi 400: sinh JSON hỏng thật `MALFORMED_JSON = '{"name": "abc", '` qua trường `raw_body` (`from_openapi.py:492`).
3. **Chống map bịa (Guard chống Hallucination)**:
   - Hàm `_drop_unverified_http()` (`mapper.py:325`): Nếu một câu văn xuôi chứa đường dẫn HTTP nhưng đường dẫn đó **không có trong danh sách endpoint của OpenAPI spec**, mapper từ chối map và giữ nguyên văn xuôi. Không tự bịa URL.
   - Hàm `_looks_like_api()` (`mapper.py:535`): Ngăn không cho map các câu nói về API thành lệnh mở trình duyệt `ui.goto`.

---

# 8. UI crawling / UI mapping

### Crawler nằm ở đâu và dùng thư viện gì?

- File code: `qctool/ui/crawl.py`.
- Thư viện: Sử dụng **Playwright Python** (`sync_playwright`) điều khiển trình duyệt **Chromium** thật (`crawl.py:222`).

### Chiến lược crawl 2 pha (Two-Phase Crawling)

Crawler giải quyết bài toán hóc búa của web SPA có xác thực:

- **Pha 1 (Chưa đăng nhập - Anonymous)**:
  - Mở context sạch không có cookie/storage.
  - Mở các đường dẫn công khai: `/`, `/login`, và các đường dẫn trích từ tài liệu.
  - Mục đích: Ghi lại màn hình login, form nhập liệu, và nút SSO Keycloak. Nếu đăng nhập trước rồi mới crawl thì sẽ bị redirect thẳng vào dashboard và không bao giờ thấy màn hình login.
- **Pha 2 (Đã đăng nhập - Authenticated)**:
  - Nạp file `storage_state` (chứa cookie và session).
  - Duyệt các đường dẫn nội bộ và bảo vệ (dashboard, projects, settings).
- **Khám phá liên kết (Follow Links)**:
  - Hàm `_follow()` (`crawl.py:286`) gom tất cả thẻ `<a href="...">` cùng domain/origin và duyệt tiếp theo hàng đợi BFS với ngân sách giới hạn (`budget`, mặc định tối đa 15 trang) để không crawl vô tận.
- **Có click khám phá state mới không?** KHÔNG click form submit hoặc nút hành động một cách ngẫu nhiên nhằm tránh làm thay đổi dữ liệu hoặc kích hoạt logout; crawler chỉ duyệt theo URL và thẻ `<a>`.

### Chờ đợi SPA render (`_wait_for_render`)

- Không chỉ chờ sự kiện `domcontentloaded` hay `load`.
- Hàm `_wait_for_render()` (`crawl.py:384`) chờ `networkidle` tối đa 7s, sau đó polling mỗi 400ms kiểm tra xem trong DOM đã xuất hiện ít nhất một phần tử tương tác (`button`, `a`, `input`, `select`, `textarea`) hay chưa.

### Thông tin trích xuất của từng Element

Mỗi phần tử tương tác được lưu vào class `Element` (`crawl.py:34`) gồm:

- `id`: Slug định danh sinh từ tên hoặc test id.
- `role`: `button` | `link` | `input` | `combobox` | `textbox`.
- `name`: Tên trích xuất ưu tiên từ: `inner_text()` → `aria-label` → `placeholder` → `name` → `value` → `title`.
- `tag`: Tên thẻ HTML (`button`, `a`, `input`,...).
- `input_type`: Kiểu của input (`text`, `password`, `email`,...).
- `required`: Có thuộc tính required hay không.
- `href`: Đường dẫn nếu là thẻ `a`.
- `test_id`: Giá trị đọc từ các attribute: `data-testid`, `data-test-id`, `data-test`, `data-cy`, `data-qa`.
- `disabled`: Trạng thái bị vô hiệu hoá (`disabled` attribute hoặc `aria-disabled="true"`).
- `checked`: Trạng thái tick checkbox/radio.

### Ví dụ cấu trúc `ui-map.yaml` thực tế

```yaml
base_url: https://portal.example.com
crawled_at: "2026-10-02 17:15"
pages:
  - url: https://portal.example.com/login
    title: Đăng nhập — Data Platform
    text:
      - Đăng nhập hệ thống
      - Vui lòng sử dụng tài khoản doanh nghiệp SSO
    elements:
      - id: sign_in
        role: button
        name: Sign in with Keycloak
        tag: button
        test_id: btn-login-keycloak
      - id: username
        role: textbox
        name: Tên đăng nhập
        tag: input
        input_type: text
        required: true
  - url: https://portal.example.com/projects
    title: Danh sách dự án
    text:
      - Quản lý dự án
    elements:
      - id: nav_projects
        role: link
        name: Dự án
        tag: a
        href: /projects
        test_id: nav-projects
      - id: btn_add
        role: button
        name: Thêm dự án mới
        tag: button
        test_id: btn-add-project
```

---

# 9. Execution engine

### Phân loại testcase: API vs UI vs Hybrid

- **Router kiểm tra**: Hàm `needs_browser(cases)` trong `qctool/execute/runner.py:58` quét qua toàn bộ các bước của danh sách testcase:
  ```python
  def needs_browser(cases: list[TestCase]) -> bool:
      return any(step.action in UI_VERBS for case in cases for step in case.steps)
  ```
- **API test thuần**: Không chứa bất kỳ verb nào trong `UI_VERBS`. Runner chỉ dùng `HttpSession`, không khởi động Chromium để tiết kiệm RAM và thời gian.
- **UI test & Hybrid test**: Chứa các verb UI. Runner khởi động `BrowserSession`. Trong hàm `run_case()`, từng bước được điều hướng:
  ```python
  if step.action in UI_VERBS:
      ok, detail = _run_ui_step(step, browser)
  else:
      ok, detail = _run_step(step, session, saved)
  ```
  Nhờ đó, một testcase có thể vừa gọi HTTP để seed dữ liệu, vừa mở browser để verify UI (Hybrid test).

### HTTP / API Executor (`HttpSession`)

- **Thư viện**: Dùng thư viện chuẩn `http.client` và `urllib` (không dùng `requests` hay `httpx` để giảm phụ thuộc bên ngoài) (`runner.py:181`).
- **Keep-alive & Server-Timing**: Tự quản lý kết nối persistent `HTTPConnection` / `HTTPSConnection`. Tự động đọc header `Server-Timing` (`cfOrigin;dur=`) để phân biệt độ trễ mạng biên và độ trễ backend thực tế (`runner.py:301`).
- **Custom User-Agent**: Bắt buộc gửi `User-Agent: qc-tool/0.0.1...` để tránh bị WAF/môi trường dev chặn 403 do User-Agent mặc định của Python-urllib (`runner.py:35`).
- **Xử lý Auth**: Gửi header `Authorization: Bearer <token>` nếu `auth: "bearer"`.

### Playwright / UI Executor (`BrowserSession`)

- **Action Vocabulary thực tế**:
  1. `ui.goto`: Mở URL web (tự động retry nếu mạng đổi, kiểm tra `chrome-error://`).
  2. `ui.session`: Chuyển đổi trạng thái phiên (`anonymous`: xoá sạch cookie/localStorage/sessionStorage; `authenticated`: nạp lại storage_state).
  3. `ui.click`: Bấm element (tự chờ render).
  4. `ui.fill`: Điền text vào input.
  5. `ui.select`: Chọn option dropdown.
  6. `ui.hover`: Di chuột lên element.
  7. `ui.press`: Nhấn phím (`Enter`, `Escape`, `Tab`).
  8. `ui.check`: Tick/bỏ tick checkbox.
  9. `ui.scroll`: Cuộn trang (`up`/`down`/`top`/`bottom` hoặc cuộn tới element).
  10. `ui.wait_for`: Chờ element đạt trạng thái (`visible`, `hidden`, `attached`).

### Xử lý lỗi, Retry và Timeout

- **Một action fail có chắc chắn làm testcase fail không?**
  - **Mặc định (`soft_assert=False`)**: CÓ. Ngay khi một bước `assert.*` hoặc `http.request` trả về `ok=False`, vòng lặp bước dừng lại ngay lập tức và testcase nhận trạng thái `STATUS_FAIL` (`runner.py:508`).
  - **Khi bật Soft Assert (`soft_assert=True`)**: Bước kiểm tra sai sẽ được ghi nhận vào `soft_failures`, bước tiếp theo vẫn tiếp tục chạy. Cuối case, nếu có bất kỳ soft failure nào, status vẫn được chốt là `STATUS_FAIL` (`runner.py:526`).
- **Xử lý Exception ngoại lệ**:
  - Nếu bắt gặp `NeedsEnvironment` hoặc `NeedsLogin`: Ném ra và bắt tại `run_case()`, chuyển status thành `STATUS_BLOCKED` (không đổ lỗi cho sản phẩm) (`runner.py:495`).
  - Các exception khác: Đóng gói thành `ok=False`, ghi chi tiết lỗi vào `StepResult`.
- **Cơ chế Retry (Tách lỗi thật khỏi Flaky)**:
  - Nếu bật `--retry N` (tối đa 3) và lần đầu case bị `Fail`: Chạy lại case.
  - Nếu lần sau case `Pass`: Chốt status `Pass` nhưng đánh dấu cờ `flaky = True`, đồng thời ghi chú vết fail của lần chạy đầu vào `actual` và `attempts` (`runner.py:394`).
- **Timeout**:
  - HTTP timeout mặc định: 30s (`timeout_seconds`).
  - Playwright context timeout: 30s (`timeout_ms`).
- **Bằng chứng (Evidence)**:
  - Bắt lỗi console (`console.error`), page error (`window.onerror`), request thất bại (`requestfailed` hoặc response $\ge 400$).
  - Khi fail: tự động chụp màn hình full-page lưu vào `evidence/<TC_ID>-fail.png`.
  - Nếu bật trace: lưu `evidence/<TC_ID>.trace.zip` xem lại timeline bằng Playwright Trace Viewer (`browser.py:249`).

---

# 10. Validation / Assertion

### Danh mục assertion mà hệ thống hỗ trợ

Toàn bộ assertion được định nghĩa trong `ACTION_SPECS` (`qctool/testcase.py:144`):

| Assertion Action            | Tham số bắt buộc / tuỳ chọn                             | Thực thi tại đâu?            | Cách thức kiểm tra                                                                                                             |
| --------------------------- | ------------------------------------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `assert.http_status`        | `expected` (int), opt: `source`                         | `runner.py::_run_step`       | So khớp status code của HTTP response đã lưu                                                                                   |
| `assert.json_schema`        | `required` (list), opt: `types`, `source`               | `runner.py::_run_step`       | Kiểm tra body có đủ các field bắt buộc                                                                                         |
| `assert.json_field`         | `path` (`$.a.b`), `expected`, opt: `operator`, `source` | `runner.py::_run_step`       | Trích xuất đường dẫn JSON và so sánh theo operator (`eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `matches`, `exists`) |
| `assert.response_time`      | `max_ms`, opt: `percentile`, `samples`, `source`        | `runner.py::_run_step`       | Gọi lại $N$ mẫu (`samples`, mặc định 20), tính phân vị thứ $P$ (`percentile`, mặc định 95) và so sánh ngưỡng                   |
| `assert.contains`           | `actual`, `expected`                                    | `runner.py`                  | Kiểm tra chuỗi chứa substring                                                                                                  |
| `assert.not_contains`       | `actual`, `expected`                                    | `runner.py`                  | Kiểm tra chuỗi không chứa substring                                                                                            |
| `assert.equals`             | `actual`, `expected`                                    | `runner.py`                  | So sánh bằng tuyệt đối                                                                                                         |
| `assert.visible`            | `target`, opt: `by_name`                                | `browser.py::_check`         | Gọi Playwright `expect(locator).to_be_visible()` (auto-wait)                                                                   |
| `assert.not_visible`        | `target`, opt: `by_name`                                | `browser.py::_check`         | Gọi Playwright `expect(locator).to_be_hidden()`                                                                                |
| `assert.enabled`            | `target`, opt: `by_name`                                | `browser.py::_check`         | Gọi Playwright `expect(locator).to_be_enabled()`                                                                               |
| `assert.disabled`           | `target`, opt: `by_name`                                | `browser.py::_check`         | Gọi Playwright `expect(locator).to_be_disabled()`                                                                              |
| `assert.text`               | `target`, `expected`, opt: `operator`, `exact`          | `browser.py::_check`         | Gọi Playwright `expect(locator).to_have_text()` hoặc `to_contain_text()`                                                       |
| `assert.value`              | `target`, `expected`, opt: `operator`                   | `browser.py::_check`         | Gọi Playwright `expect(locator).to_have_value()`                                                                               |
| `assert.attr`               | `target`, `name`, `expected`                            | `browser.py::_check`         | Gọi Playwright `expect(locator).to_have_attribute()`                                                                           |
| `assert.count`              | `target`, `expected`, opt: `operator`                   | `browser.py::count`          | Đếm số lượng element khớp trên màn hình                                                                                        |
| `assert.focused`            | `target`, opt: `by_name`                                | `browser.py::_check`         | Gọi Playwright `expect(locator).to_be_focused()`                                                                               |
| `assert.checked`            | `target`, opt: `expected`                               | `browser.py::_check`         | Gọi Playwright `expect(locator).to_be_checked()`                                                                               |
| `assert.console_clean`      | opt: `forbidden`, `max_errors`                          | `browser.py::console_clean`  | Kiểm tra danh sách `_console` không có lỗi JS trong lượt chạy                                                                  |
| `assert.no_broken_requests` | opt: `allow`, `max_errors`                              | `browser.py::requests_clean` | Kiểm tra danh sách `_network` không có request nào trả mã $\ge 400$                                                            |
| `assert.url_matches`        | `pattern` (regex)                                       | `browser.py::url_matches`    | Kiểm tra URL hiện tại của browser khớp regex                                                                                   |
| `assert.axe`                | opt: `severity`, `tags`, `max_violations`               | `browser.py::axe_scan`       | Chèn axe-core JS vào trang web và quét vi phạm accessibility (A11y)                                                            |
| `assert.screenshot`         | `name`, opt: `full_page`                                | `browser.py::screenshot`     | Lưu ảnh chụp làm bằng chứng kiểm thử                                                                                           |
| `assert.unmapped`           | `expected`                                              | Không thực thi tự động       | Giữ nguyên câu văn xuôi, đánh dấu case `manual`                                                                                |

### Ai quyết định assertion?

- **Hoàn toàn do Rule Engine quyết định**:
  - Với OpenAPI: Engine đọc mã trạng thái (`responses`), schema required fields, và extension latency để sinh ra `assert.http_status`, `assert.json_schema`, `assert.response_time`.
  - Với Requirements/Flows: `mapper.py` dùng bộ quy tắc regex đối sánh từ khoá ngữ nghĩa ("chuyển tới /login" -> `assert.url_matches`, "nút Lưu bị vô hiệu hoá" -> `assert.disabled`, "không lộ lỗi JS" -> `assert.console_clean`).

### Có trường hợp chạy action thành công nhưng không có assertion mà vẫn PASS không?

- **TUYỆT ĐỐI KHÔNG**:
  - Tại tầng Validate (`qctool/testcase.py:641`), hàm `TestCase.validate()` quy định bắt buộc:
    ```python
    if not any(s.action.startswith("assert.") for s in self.steps):
        raise ValidationError(
            f"`{self.id}` không có bước kiểm tra nào (`assert.*`). "
            "Một testcase không kiểm gì cả thì không phải testcase."
        )
    ```
    Nếu một testcase không có assertion, tool sẽ báo lỗi ngay ở chặng Generate và từ chối xuất file / từ chối chạy.

---

# 11. Test data / fixtures

### Nguồn gốc Test Data

1. **Trích xuất từ OpenAPI Schema** (`qctool/generate/from_openapi.py:154`):
   - Hàm `_sample_value()` sinh data tự động dựa theo `type`, `format` (`uuid`, `email`, `date-time`), `enum`, `example`, `default`.
2. **Khai báo qua OpenAPI extension `x-qc-test-data`**:
   - Generator nạp data tĩnh được định nghĩa trước trong spec qua `x-qc-test-data` (`loader.py:151`).
3. **Trích xuất từ bảng tài liệu**:
   - Các tham số trong bảng Request của SRS được đưa vào dictionary `test_data` của testcase.
4. **Tài khoản người dùng**:
   - Nạp từ file `.env` hoặc tham số dòng lệnh (`QCTOOL_USERNAME`, `QCTOOL_PASSWORD`, `QCTOOL_BEARER_TOKEN`).

### Xử lý khi thiếu Test Data hoặc thiếu môi trường

- Code path: `TestCase.requires` (`qctool/testcase.py:596`) và `qctool/execute/runner.py:459`:
  - Khi một testcase kiểm tra mã 403 (cần tài khoản không có quyền), mã 404 (cần ID không tồn tại), hoặc mã 409 (cần dữ liệu xung đột sẵn có) mà tool chỉ có một tài khoản duy nhất:
  - Generator tự động gán chuỗi cảnh báo vào thuộc tính `case.requires = "Cần một tài khoản KHÔNG có quyền..."` (`from_openapi.py:442`).
  - Khi thực thi, runner kiểm tra nếu `case.requires` có giá trị thì **lập tức chuyển trạng thái sang `Blocked` kèm lý do rõ ràng, tuyệt đối KHÔNG chạy để rồi báo `Fail`**.
- **Không có dependency giữa các testcase**: Mỗi testcase độc lập hoàn toàn.
- **Không có cleanup/teardown cơ sở dữ liệu**: Tool không tự gọi API xoá dữ liệu hay can thiệp DB trực tiếp ở phiên bản hiện tại.

---

# 12. Execution status

Hệ thống có **4 trạng thái chính thức** và **1 dấu vết trạng thái (flag)** được quy định chặt chẽ trong `qctool/execute/runner.py:37`:

| Trạng thái             | Điều kiện dẫn đến trạng thái                                                                                                                                                                                                                                                                                                    | Ý nghĩa nghiệp vụ                                                                                                                                     |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Pass`                 | Tất cả các bước trong case chạy thành công và mọi assertion đều đúng.                                                                                                                                                                                                                                                           | Sản phẩm hoạt động đúng kỳ vọng.                                                                                                                      |
| `Fail`                 | - Một bước `assert.*` không đạt.<br>- Request `http.request` trả lỗi mạng không mong muốn hoặc status code khác expected.<br>- Bật `soft_assert=True` và có ít nhất 1 assert lỗi sau khi hết case.                                                                                                                              | **Sản phẩm có lỗi (Bug)**. Chỉ dùng khi môi trường test hợp lệ nhưng hệ thống trả sai.                                                                |
| `Blocked`              | - Case có khai báo `requires` (thiếu tài khoản phân quyền, thiếu dữ liệu nền).<br>- Case còn bước chưa map (`needs_mapping=True`).<br>- Gặp exception `NeedsEnvironment` (lỗi mạng máy test `ERR_NETWORK_CHANGED`, không tải được thư viện axe-core).<br>- Gặp exception `NeedsLogin` (bị redirect về login vì chưa đăng nhập). | **Chưa chạy được do thiếu điều kiện môi trường**, không phải lỗi của sản phẩm.                                                                        |
| `Not Executed`         | Case được đánh dấu `execution="manual"` (các case nghiệp vụ có bước viết bằng văn xuôi dành cho người thực hiện tay).                                                                                                                                                                                                           | Case chưa tới lượt chạy tự động, dành cho QC chạy thủ công.                                                                                           |
| `flaky` _(cờ dấu vết)_ | Case bị `Fail` ở lần chạy đầu tiên nhưng sau khi thử lại (`--retry`) thì `Pass`.                                                                                                                                                                                                                                                | Case vẫn tính `Pass` về mặt số lượng nhưng được gắn cờ `flaky=True` và tách riêng ở Mục 6 của báo cáo để cảnh báo race condition hoặc test viết giòn. |

### Xử lý các tình huống đặc biệt:

- **Action fail nhưng assertion không fail**: Nếu action chính (như `http.request` bị lỗi kết nối hoặc `ui.click` không tìm thấy phần tử) fail, runner lập tức set status là `Fail` (hoặc `Blocked` nếu là lỗi môi trường), không chạy các assertion phía sau.
- **Unsupported action (verb lạ)**: Bị chặn ngay từ tầng validate bằng `ValidationError`, không thể bước vào pha execute.
- **Missing locator**: Trong `browser.locate()`, nếu không tìm thấy locator sẽ ném `BrowserError`, bước fail -> testcase `Fail`.
- **Missing test data**: Nếu thiếu dữ liệu để gọi request hợp lệ (như method PATCH thiếu body), mapper từ chối map -> case giữ nguyên `manual` -> `Not Executed`.
- **Missing assertion**: Validator từ chối hợp lệ hóa testcase ngay từ chặng generate.

---

# 13. Reporting

Hệ thống hỗ trợ 5 hình thức kết xuất báo cáo:

### 1. Bảng Excel 14 cột (`testcases.xlsx`)

File Excel được tạo bởi `qctool/render/excel.py` và cập nhật bởi `qctool/render/results.py`. Danh sách 14 cột chính xác:

1. `Test Case ID` (Cột A, độ rộng 15, font bold xanh `#1F4E79`).
2. `Module / Feature Name` (Cột B, độ rộng 22).
3. `Test Title / Summary` (Cột C, độ rộng 46).
4. `Description / Objective` (Cột D, độ rộng 34, có gắn tiền tố `[Thủ công]` nếu là case manual).
5. `Preconditions` (Cột E, độ rộng 30, gạch đầu dòng từng điều kiện).
6. `Test Data` (Cột F, độ rộng 26, key: value).
7. `Test Steps` (Cột G, độ rộng 52, đánh số 1. 2. 3. bằng ngôn ngữ tiếng Việt dễ đọc qua hàm `describe()`).
8. `Expected Result` (Cột H, độ rộng 40, đánh số 1. 2. 3. bằng câu kỳ vọng qua hàm `expects()`).
9. `Actual Result` (Cột I, độ rộng 30, **Cột runtime 1**): Điền diễn biến thực tế từng bước (`[OK]`, `[X]`), lý do chặn, và đường dẫn bằng chứng.
10. `Status` (Cột J, độ rộng 14, **Cột runtime 2**): Dropdown list (`Pass`, `Fail`, `Blocked`, `Not Executed`), tự động tô màu theo Conditional Formatting (Pass = Xanh lá `#C6EFCE`, Fail = Đỏ `#FFC7CE`, Blocked = Vàng hổ phách `#FFEB9C`, Not Executed = Xám `#E7E6E6`).
11. `Priority / Severity` (Cột K, độ rộng 14, Dropdown list: `High`, `Medium`, `Low`).
12. `Environment` (Cột L, độ rộng 20, **Cột runtime 3**): Ghi URL môi trường test.
13. `Created By / Date` (Cột M, độ rộng 18): Người tạo và ngày tạo.
14. `Executed By / Date` (Cột N, độ rộng 18, **Cột runtime 4**): Người thực thi và ngày giờ hoàn thành.

### 2. Báo cáo Markdown (`report.md`)

Được tạo bởi `build_markdown()` trong `qctool/report/__init__.py:101`, chia thành 7 mục rõ ràng:

- **Mục 1. Tóm tắt**: Headline tỷ lệ đạt, bảng tổng quan (Tổng số test, Đạt, Lỗi, Bị chặn, Chưa chạy), cảnh báo test chập chờn (flaky).
- **Mục 2. Chi tiết theo module**: Bảng phân chia số lượng Pass/Fail/Blocked theo từng module.
- **Mục 3. Danh sách lỗi**: Chi tiết từng bug, URL lúc hỏng, danh sách request lỗi $\ge 400$, lỗi JavaScript console, log diễn biến các bước.
- **Mục 4. Cần người chạy thủ công**: Danh sách testcase `manual` kèm số bước để người QC thực hiện bằng tay.
- **Mục 5. Bị chặn — thiếu điều kiện môi trường**: Danh sách testcase `Blocked` kèm lý do môi trường cụ thể.
- **Mục 6. Test chập chờn — cần xem lại**: Danh sách case đạt sau khi retry kèm lý do lỗi của lần đầu tiên.
- **Mục 7. Bằng chứng**: Bảng tổng hợp ảnh chụp màn hình, file Playwright trace, số lỗi JS và request lỗi cho từng testcase.

### 3. JUnit XML (`junit.xml`)

Chuẩn hoá với thẻ `<testsuite>` và `<testcase>`, `<failure>` khi Fail, `<error>` khi Blocked, `<skipped>` khi Not Executed (`report/__init__.py:59`).

### 4. CSV Result (`results.csv`) & JSON Result (`results.json`)

Chứa toàn bộ dữ liệu thô, thời gian chạy từng mili-giây, snapshot bằng chứng.

---

# 14. LLM responsibilities vs deterministic engine

Bảng đối chiếu trách nhiệm dựa trên code thực tế hiện tại của repository:

| Trách nhiệm                   | LLM | Engine | Hybrid | Ghi chú từ Code thực tế                                                                                                                                        |
| ----------------------------- | :-: | :----: | :----: | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Requirement understanding** |     | **X**  |        | Parser regex/bảng trong `qctool/ingest/markdown.py` và `flows.py`.                                                                                             |
| **Testcase generation**       |     | **X**  |        | 100% Rule Engine sinh theo kỹ thuật EP, BVA, Decision Table, State Machine (`from_openapi.py`, `from_flows.py`). Mọi case đều gán cứng `generated_by: engine`. |
| **UI mapping**                |     | **X**  |        | Crawler Playwright trích xuất DOM thành `UIMap` (`crawl.py`).                                                                                                  |
| **Locator resolution**        |     | **X**  |        | Heuristics ưu tiên `test_id` (`data-testid`), sau đó tới role/name/placeholder trong `browser.py:524`.                                                         |
| **Test data**                 |     | **X**  |        | Sinh dữ liệu dựa trên schema constraints (format uuid/email, min/max bounds, enum) trong `from_openapi.py:154`.                                                |
| **Assertion generation**      |     | **X**  |        | Engine suy diễn assertion từ responses OpenAPI, ngưỡng NFR, và regex ngữ nghĩa trong `mapper.py`.                                                              |
| **Execution**                 |     | **X**  |        | `HttpSession` và `BrowserSession` thực thi tuần tự các bước.                                                                                                   |
| **Validation**                |     | **X**  |        | `validate_batch()` kiểm tra tính đúng đắn cấu trúc và coverage gaps (`validate.py`).                                                                           |

---

# 15. Những guard/safety check hiện có

Repository triển khai một hệ thống phòng thủ nhiều lớp trước và trong khi chạy:

```text
[Input Spec / Docs]
  ↓ (Guard 1: Schema & $ref Cycle Check)
[Intermediate Requirements / Endpoints]
  ↓ (Guard 2: Can-Trigger & External Filter)
[Testcase Generation]
  ↓ (Guard 3: Action Vocabulary Validation)
  ↓ (Guard 4: Missing Assertion Check)
  ↓ (Guard 5: Orphan & Duplicate Check)
  ↓ (Guard 6: Needs-Mapping & Pass Conflict Guard)
[Mapping Phase]
  ↓ (Guard 7: Unverified HTTP Path Drop)
  ↓ (Guard 8: Requires Precondition Check)
[Execution Phase]
  ↓ (Guard 9: NeedsEnvironment Exception Catch)
  ↓ (Guard 10: Flaky Retry Demarcation)
[Report & Backfill]
```

### Cách repository xử lý 8 tình huống rủi ro cụ thể:

1. **LLM/Engine sinh action mà runtime không hỗ trợ**:
   - `Step.validate()` (`testcase.py:312`) so khớp action với `ACTION_SPECS`. Nếu có verb lạ, ném ngay `ValidationError` và dùng thuật toán Levenshtein distance để gợi ý verb gần đúng.
2. **Locator không tồn tại**:
   - Trong `browser.locate()` (`browser.py:530`), nếu duyệt qua tất cả selector (test_id, role, name, placeholder...) mà `count() == 0`, hàm ném ngay `BrowserError("Không tìm thấy element...")`, không bao giờ trả về locator rỗng để tránh timeout 30s âm thầm.
3. **Thiếu test data**:
   - Nếu endpoint yêu cầu body nhưng tài liệu không có thông tin để dựng body hợp lệ (ví dụ PATCH /auth/me), mapper từ chối map (`mapper.py:662`) -> Case giữ nguyên `manual` -> Chuyển sang `Not Executed`.
4. **Expected result không thể validate**:
   - Với NFR không có ngưỡng định lượng, engine không sinh case mà đưa vào danh sách `unverifiable` (`from_requirements.py:134`).
   - Với câu văn xuôi không trích xuất được hành vi kiểm thử, case giữ nguyên `assert.unmapped` và gán trạng thái `Not Executed`.
5. **Một step fail nhưng testcase vẫn PASS**:
   - Trong `run_case()` (`runner.py:508`), ngay khi một bước trả về `ok=False`, vòng lặp ngắt và status lập tức chốt là `Fail`.
   - Với soft assert, biến `soft_failures` được kiểm tra ở cuối hàm; nếu có bất kỳ lỗi nào, status bắt buộc là `Fail` (`runner.py:526`).
   - Validator kiểm tra chặn đứng: Nếu case có `needs_mapping` hoặc `execution=manual` mà mang status `Pass`, validator sẽ ném lỗi (`testcase.py:650`).
6. **Assertion quá rộng nên luôn PASS**:
   - Với kiểm tra mã lỗi: Hàm `_can_trigger()` (`from_openapi.py:464`) kiểm tra endpoint có body hoặc query vi phạm không; nếu endpoint không có gì để gây lỗi 422 thì **bỏ qua không sinh case** thay vì sinh case gọi request bình thường rồi assert 422.
   - Với response error schema: Chỉ kiểm tra field bắt buộc khi spec OAS có định nghĩa `required`, không tự gán assert kiểm tra field `code` cứng (`from_openapi.py:341`).
7. **UI đã thay đổi so với UI map**:
   - `BrowserSession` ưu tiên selector `data-testid` (`browser.py:537`). Nếu dev đổi chữ hiển thị nhưng giữ test id, test vẫn chạy ổn định. Nếu UI đổi hoàn toàn mất cả element, `locate()` ném lỗi và case báo `Fail` kèm ảnh chụp màn hình bằng chứng.
   - Hàm `_keep_better_map()` (`pipeline.py:559`) bảo vệ không để lần crawl lỗi ghi đè làm mất UI map đầy đủ của lần trước.
8. **Testcase yêu cầu nhiều outcome nhưng chỉ validate một outcome**:
   - Hàm `_split_conditions()` (`mapper.py:773`) phát hiện dấu `;` hoặc `,` trong các câu nhiều vế (ví dụ: `Nav Projects visible; Users hidden`) để tách thành **nhiều assertion riêng biệt** (`assert.visible` và `assert.not_visible`). Cả hai đều phải pass thì testcase mới đạt.

---

# 16. Một testcase thực tế đi xuyên hệ thống

Chúng ta trace vòng đời của testcase **Đăng nhập điều hướng** từ tài liệu fixture thật trong `tests/fixtures/urd.md:19`.

### 1. Requirement gốc trong Markdown (`urd.md`)

```markdown
### US-001 — Đăng nhập

**Acceptance Criteria**
| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-001-1 | Chưa đăng nhập | Mở `/projects` | Redirect `/login` |
```

### 2. Manifest Ingest (`requirements.yaml`)

Hàm `parse_urd()` nạp và chuẩn hoá thành:

```yaml
id: AC-demo-001-1
feature: demo
kind: acceptance_criterion
title: Redirect /login
belongs_to: US-demo-001
traces_to: [US-demo-001]
given: Chưa đăng nhập
when: Mở `/projects`
then: Redirect `/login`
content_hash: sha256:7c9e12...
source:
  file: urd.md
  line: 19
  quote: Redirect `/login`
```

### 3. Generated Testcase sơ bộ (`from_requirements.py`)

Case được sinh với action unmapped và gán thủ công:

```yaml
id: TC_DEMO_001
module: demo
title: Mở /projects → Redirect /login
execution: manual
steps:
  - seq: 1
    kind: when
    action: perform.unmapped
    args: { description: "Mở `/projects`", expectation: "Redirect `/login`" }
  - seq: 2
    kind: then
    action: assert.unmapped
    args: { expected: "Redirect `/login`" }
```

### 4. Mapped Executable IR (`mapper.py`)

Mapper phát hiện `Chưa đăng nhập` -> chèn phiên ẩn danh `ui.session(mode=anonymous)`. Phát hiện `Mở /projects` -> chuyển thành `ui.goto`. Phát hiện `Redirect /login` -> chuyển thành `assert.url_matches`. Case map thành công 100% -> nâng lên `execution: auto`:

```yaml
id: TC_DEMO_001
module: demo
title: Mở /projects → Redirect /login
execution: auto
steps:
  - seq: 1
    kind: given
    action: ui.session
    args: { mode: anonymous }
  - seq: 2
    kind: when
    action: ui.goto
    args: { url: "https://dev.example.com/projects" }
  - seq: 3
    kind: then
    action: assert.url_matches
    args: { pattern: "/login" }
expected:
  - "URL hiện tại khớp `/login`"
```

### 5. Execution qua Runner & Browser

- `runner.py::run_case()` thấy `has_ui=True`: Gọi `browser.start_case("TC_DEMO_001")` mở Chromium context sạch.
- **Bước 1 (`ui.session`)**: `browser.set_session(mode="anonymous")` -> Xoá cookies, xoá localStorage, điều hướng về `about:blank`. Trả về `[OK] Đã xoá phiên`.
- **Bước 2 (`ui.goto`)**: `browser.goto("https://dev.example.com/projects")` -> Router guard của webapp phát hiện chưa đăng nhập -> tự động chuyển hướng trình duyệt sang `https://dev.example.com/login?callback=%2Fprojects`. Trả về `[OK] Mở ... -> https://dev.example.com/login...`.
- **Bước 3 (`assert.url_matches`)**: `browser.url_matches("/login")` -> URL hiện tại chứa `/login`. Trả về `[OK] URL hiện tại khớp «/login»`.
- Runner chốt: `status = "Pass"`.
- `browser.end_case()` thu thập bằng chứng.

### 6. Kết quả trong `results.json` & Báo cáo

```json
{
  "case_id": "TC_DEMO_001",
  "status": "Pass",
  "duration_ms": 1240.5,
  "actual": [
    "[OK] Đã xoá phiên — trình duyệt giờ chạy như người dùng chưa đăng nhập",
    "[OK] Mở https://dev.example.com/projects → https://dev.example.com/login?callback=%2Fprojects",
    "[OK] URL hiện tại khớp «/login»: https://dev.example.com/login?callback=%2Fprojects"
  ]
}
```

### 7. Điền ngược vào Excel 14 cột (`testcases.xlsx`)

Hàm `fill_results()` mở file Excel:

- Tìm dòng có `Test Case ID` = `TC_DEMO_001`.
- Cột I (`Actual Result`): Ghi diễn biến 3 bước `[OK]`.
- Cột J (`Status`): Ghi `Pass`, tô nền xanh lá `#C6EFCE`.
- Cột L (`Environment`): Ghi `https://dev.example.com`.
- Cột N (`Executed By / Date`): Ghi `qc-tool · 2026-10-02 17:45:00`.

---

# 17. Điểm mạnh kiến trúc hiện tại

1. **Nguyên tắc "Không nói dối" (No False Positives / No Hallucinations)**:
   - Tách biệt rạch ròi giữa `Fail` (sản phẩm có lỗi thật) và `Blocked` (thiếu tài khoản test, thiếu dữ liệu, mạng máy test chập chờn). Không bao giờ đổ lỗi cho sản phẩm vì thiếu môi trường test (`AGENTS.md:149`).
2. **Deterministic-First (Không phụ thuộc LLM cho execution)**:
   - Toàn bộ pipeline sinh testcase và execute dùng Rule Engine và Closed Action Vocabulary. Cùng một input luôn cho ra đúng một output, đảm bảo tính tái lập (reproducibility) trong CI/CD.
3. **Mô hình Bản ghi hai pha (Two-Phase Excel Recording)**:
   - File `.xlsx` 14 cột sinh ra một lần duy nhất, sau khi chạy thì kết quả được ghi ngược vào 4 cột runtime của chính file đó. QC và Quản lý không bao giờ phải so sánh đối chiếu giữa 2 file kết quả và spec.
4. **Auto-wait Assertions chống Flake**:
   - Tầng UI browser dùng trực tiếp `expect()` của Playwright (polling DOM tự động) thay vì đọc DOM một lần. Điều này loại bỏ hoàn toàn hiện tượng flake phổ biến ở các ứng dụng SPA (React/Vue/Angular).
5. **Context cô lập tuyệt đối cho từng testcase**:
   - Mỗi testcase UI chạy trong một Playwright browser context riêng biệt (`start_case` / `end_case`), xoá sạch cookie và storage. Giải quyết triệt để vấn đề "chạy riêng lẻ thì Pass, chạy cả bộ suite thì Fail".
6. **Nhận thức phân vị trong kiểm thử hiệu năng (Percentile-Aware NFR)**:
   - Nhận diện đúng bản chất phân vị của yêu cầu `p95 < 100ms`: Tự động lấy 20 mẫu request (`PERF_SAMPLES = 20`) để tính phân vị thứ 95 thay vì chỉ đo 1 request duy nhất rồi báo fail sai.

---

# 18. Các giới hạn hiện tại

### Confirmed limitation (Đã xác nhận trực tiếp từ code)

1. **Chưa hỗ trợ LLM track**: Toàn bộ codebase hiện tại là `generated_by: engine`. Các bước văn xuôi phức tạp chưa có LLM adapter để tự động suy diễn khi rule engine không khớp (`README.md:38`).
2. **Chỉ hỗ trợ tài liệu Markdown**: Chưa có parser cho `.docx`, `.pdf`, hay Google Docs (`qctool/ingest/markdown.py:3`).
3. **Thực thi tuần tự (Single-threaded Execution)**: Vòng lặp `run_cases()` chạy lần lượt từng case một. Chưa hỗ trợ worker chạy song song (parallel execution) nên với bộ test hàng nghìn case UI sẽ tốn nhiều thời gian.
4. **Thiếu các action UI phức tạp**: Vocabulary hiện tại chưa có verbs cho: Upload file (`input[type=file]`), tương tác `iframe`, xử lý alert/dialog native của trình duyệt (`window.confirm`, `window.prompt`), kéo thả (drag and drop) (`README.md:241`).
5. **Thiếu cơ chế tự động dọn dẹp dữ liệu (Teardown/Cleanup)**: Hệ thống chưa có adapter gọi API xoá dữ liệu hoặc rollback database sau khi thực thi testcase tạo mới (`POST`/`PUT`).
6. **Chỉ hỗ trợ trình duyệt Chromium**: Hardcoded `pw.chromium.launch()`, chưa hỗ trợ Firefox hoặc WebKit/Safari (`crawl.py:233`, `browser.py:181`).

### Possible limitation / Cần kiểm chứng

1. **Khả năng scale của UI Crawler**: Thuật toán `_follow()` giới hạn tối đa 15 trang (`max_pages=15`). Với các portal lớn có hàng trăm trang và menu đa cấp lồng nhau, crawler có thể bỏ sót các trang nằm sâu nếu không được cấu hình `extra_paths` đầy đủ từ tài liệu.
2. **Khả năng map ngữ nghĩa tự nhiên tiếng Việt**: Bộ regex trong `mapper.py` được tối ưu rất tốt cho tài liệu chuẩn mực của dự án pilot (chứa các từ khoá chuẩn như `Given`, `When`, `Then`, `Mở`, `Bấm`, `Redirect`). Với các tài liệu viết tự do không theo cấu trúc, tỷ lệ case rơi vào `manual` (chưa map được) có thể tăng cao.

---

# 19. Những phần có thể tái sử dụng cho QC Tool generic

Mục tiêu xây dựng hệ thống generic:
`OAS + URD + SRS` → `requirements.yaml` → `Generate testcase` → `Make testcase executable` → `HTTP / Playwright` → `Validate` → `testcases.xlsx`.

Dưới đây là đánh giá tái sử dụng:

### 1. Phần có thể tái sử dụng gần như nguyên bản (Reuse As-Is)

- **Data Model Testcase IR & Closed Vocabulary (`qctool/testcase.py`)**:
  - `TestCase`, `Step`, `ACTION_SPECS`, các Enum (`CaseType`, `Technique`, `Priority`). Đây là mô hình trung gian cực kỳ hoàn chỉnh, có thể đem sang project mới mà không cần sửa đổi.
- **Batch Validator (`qctool/validate.py`)**:
  - Toàn bộ logic phát hiện ID trùng, case trùng nội dung bằng `content_hash`, orphan cases, requirement gaps, và tính toán độ phủ (coverage line).
- **Template Excel Generator & Two-Phase Backfiller (`qctool/render/excel.py` & `results.py`)**:
  - Mã nguồn dựng bảng openpyxl 14 cột, drop-down data validation, conditional formatting màu sắc, và hàm `fill_results()` ghi ngược dữ liệu runtime.
- **Reporting Engine (`qctool/report/__init__.py`)**:
  - Các hàm kết xuất `report.md`, `junit.xml`, `results.csv`, `results.json`.

### 2. Phần có thể tham khảo Concept (Cần mở rộng/Refactor)

- **OpenAPI Loader & Generator (`from_openapi.py` & `loader.py`)**:
  - Concept sinh Happy Path, mã lỗi, BVA, missing field, auth matrix rất xuất sắc. Cần mở rộng thêm để hỗ trợ OpenAPI 3.1, `oneOf`, `anyOf`, và sinh body cho nested schemas phức tạp.
- **Playwright Browser Wrapper (`qctool/execute/browser.py`)**:
  - Rất đáng giá ở kiến trúc context cô lập theo testcase, auto-wait expect, gom bằng chứng và phân loại lỗi môi trường `NeedsEnvironment`. Cần bổ sung thêm các verbs upload file, drag-drop, dialog.
- **UI Crawler 2 Pha (`qctool/ui/crawl.py`)**:
  - Concept crawl 2 pha (trước login và sau login) để bắt trọn cả màn hình login lẫn appshell bên trong là chuẩn mực cho web SPA. Cần mở rộng thêm khả năng cấu hình depth và cơ chế click menu accordion để bung các element ẩn.
- **Natural Language Mapper (`qctool/generate/mapper.py`)**:
  - Kiến trúc biến đổi `perform.unmapped` → action có thật là điểm mấu chốt. Hiện tại đang dùng Regex + Heuristics. Bạn có thể cắm thêm một LLM adapter nhỏ ở tầng fallback của mapper để xử lý các câu văn xuôi tiếng Việt phức tạp mà regex không bắt được, nhưng **bắt buộc LLM phải map vào danh sách element có thật từ `UIMap`**.

### 3. Phần quá Domain-Specific (Không nên tái sử dụng)

- Logic parse đăng nhập form Keycloak hardcoded trong `BrowserSession.login()` (`browser.py:377`) (chứa selector `#kc-login`, `input[name='username']`). Cần biến thành cấu hình form login linh hoạt hoặc login script pluggable.
- Các quy tắc regex gắn chặt vào cấu trúc file markdown pilot của dự án cũ trong `qctool/ingest/markdown.py` (như bảng `Function List §3.1`, format `H_FUNC_DETAIL = #### 3.2.1. F-01`).

---

# 20. Kết luận cuối cùng

## A. Architecture Diagram

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                    QC-TOOL ARCHITECTURE                                │
└────────────────────────────────────────────────────────────────────────────────────────┘

  [INPUT SOURCES]
  ├── Markdown Docs (URD / SRS / Flows) ──────────────────────────┐
  ├── OpenAPI Spec (OAS 3.0 YAML/JSON) ─────────────┐             │
  ├── Webapp Base URL & Credentials ────┐           │             │
  └── Config (qctool.yaml / .env)       │           │             │
                                        │           │             │
                                        ▼           ▼             ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────┐
  │ 1. INGESTION MODULE (qctool/ingest/)                                                 │
  │    ├── markdown.py (Parse User Stories, Given/When/Then AC, NFRs)                    │
  │    ├── flows.py (Parse Mermaid Sequence, Flowchart, State, Decision Tables)          │
  │    └── ids.py (Canonical ID Normalization: FR-{feat}-{NNN}, AC, NFR)                 │
  │    OUTPUT: requirements.yaml (Semantic Content Hash, Traceability Refs)               │
  └─────────────────────────────────────┬────────────────────────────────────────────────┘
                                        │
                                        ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────┐
  │ 2. GENERATION MODULE (qctool/generate/)                                              │
  │    ├── loader.py (OpenAPI Loader, Recursive $ref / allOf Resolver)                   │
  │    ├── from_openapi.py (EP, BVA, Auth Matrix, Missing Fields, Error Codes)           │
  │    ├── from_requirements.py (Given/When/Then -> Unmapped Steps, NFR Thresholds)      │
  │    ├── from_flows.py (Multi-step Flow Cases, Decision Yes/No Cases)                  │
  │    └── from_functions.py (Flow Steps, Error Handling Cases)                          │
  │    OUTPUT: Testcase IR (TestCase, Step, Closed ACTION_SPECS)                         │
  └───────────────────┬───────────────────────────────────────────┬──────────────────────┘
                      │                                           │
                      ▼                                           ▼
  ┌──────────────────────────────────────────┐   ┌───────────────────────────────────────┐
  │ 2b. UI CRAWLER & MAPPER                  │   │ 2c. INITIAL RENDER                    │
  │   ├── qctool/ui/crawl.py                 │   │   ├── qctool/generate/write_cases()   │
  │   │   (Playwright Chromium 2-phase:      │   │   │   -> testcases.yaml               │
  │   │    Anonymous & Authenticated)        │   │   └── qctool/render/excel.py          │
  │   │   -> ui-map.yaml (test_ids, roles)   │   │       -> testcases.xlsx               │
  │   └── qctool/generate/mapper.py          │   │          (10 spec columns,            │
  │       (Unmapped Prose -> Concrete Verbs) │   │           openpyxl format)            │
  │       -> Promotes manual to auto cases   │   └───────────────────────────────────────┘
  └───────────────────┬──────────────────────┘
                      │
                      ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────┐
  │ 3. EXECUTION ENGINE (qctool/execute/)                                                │
  │    ├── runner.py (Execution Router, Soft Assert, Flaky Retry Controller)             │
  │    │     ├── API Cases ─────────► HttpSession (keep-alive, Server-Timing, urllib)    │
  │    │     └── UI/Hybrid Cases ───► BrowserSession (Playwright Chromium)               │
  │    │                                ├── Isolated context per testcase                │
  │    │                                ├── Auto-wait assertions via expect()            │
  │    │                                ├── Env failure guard (NeedsEnvironment)         │
  │    │                                └── Evidence Collector (screenshots, traces)     │
  │    OUTPUT: RunResult (Pass / Fail / Blocked / Not Executed + Flaky flags)            │
  └───────────────────┬──────────────────────────────────────────────────────────────────┘
                      │
                      ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────┐
  │ 4. REPORTING & BACKFILLING (qctool/report/ & qctool/render/)                         │
  │    ├── report/__init__.py                                                            │
  │    │     ├── report.md (7-section markdown human report)                             │
  │    │     ├── junit.xml (Standard CI/CD integration)                                  │
  │    │     ├── results.csv (Flat data table)                                           │
  │    │     └── results.json (Machine-readable full execution dump)                     │
  │    └── render/results.py (fill_results())                                            │
  │          └── Writes runtime actuals/status/env into the ORIGINAL testcases.xlsx      │
  └──────────────────────────────────────────────────────────────────────────────────────┘
```

---

## B. Runtime Flow Diagram

```text
[CLI: qctool all / Web UI / CI]
           │
           ▼
[pipeline.py::run_pipeline()]
  │
  ├──► [1. INGEST]
  │      Docs Dir ──► parse_markdown() + extract_flows()
  │               ──► Deduplicate & Canonicalize IDs
  │               ──► requirements.yaml written
  │
  ├──► [2. GENERATE]
  │      requirements.yaml + openapi.yaml
  │               ──► generate_all()
  │               ──► validate_batch() (Checks orphans, duplicates, gaps)
  │               ──► testcases.yaml + testcases.xlsx (10 cols) written
  │
  ├──► [3. CRAWL & MAP] (if web_url provided)
  │      web_url  ──► crawl() (P1: anon -> P2: auth) ──► ui-map.yaml
  │      cases + ui-map ──► map_testcases()
  │                     ──► Unmapped prose resolved to data-testid actions
  │                     ──► Promotes eligible cases from 'manual' to 'auto'
  │
  ├──► [4. EXECUTE]
  │      cases ──► needs_browser() check
  │            ──► Init HttpSession & BrowserSession
  │            ──► Loop each TestCase:
  │                  ├── Check 'manual' -> Mark STATUS_NOT_EXECUTED
  │                  ├── Check 'requires' -> Mark STATUS_BLOCKED
  │                  ├── BrowserSession.start_case(case_id) (clean context)
  │                  ├── Execute Steps (HTTP request or Browser action/expect)
  │                  ├── Catch NeedsEnvironment -> Mark STATUS_BLOCKED
  │                  ├── On Failure -> Retry up to N times (detect flaky)
  │                  └── BrowserSession.end_case() -> Collect evidence PNG/ZIP
  │
  └──► [5. REPORT & BACKFILL]
         RunResult ──► write_json(), write_csv(), write_junit(), render_markdown()
                   ──► fill_results(testcases.xlsx) (Backfill 4 runtime cols)
                   ──► Return PipelineResult (Success/Fail summary)
```

---

## C. Core Files Table

| File                              | Responsibility                                                                                                                                                                      |   Importance   |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------: |
| `qctool/pipeline.py`              | **Nhạc trưởng (Orchestrator)** điều phối toàn bộ 4 chặng: Ingest, Generate, Crawl, Map, Execute, Report. Điểm vào duy nhất cho CLI, Web UI và CI.                                   | **Tối thượng** |
| `qctool/testcase.py`              | Định nghĩa **Testcase IR** (`TestCase`, `Step`), **Closed Action Vocabulary** (`ACTION_SPECS` 25 verbs), Enums, validation rules và semantic content hash.                          | **Tối thượng** |
| `qctool/generate/mapper.py`       | **Ánh xạ nghiệp vụ thành máy thực thi**: Chuyển đổi các bước văn xuôi `perform.unmapped` / `assert.unmapped` thành thao tác UI/HTTP cụ thể dựa vào `UIMap` và OAS.                  | **Tối thượng** |
| `qctool/execute/runner.py`        | **Execution Engine**: Điều phối thực thi HTTP và Browser, kiểm tra precondition, xử lý retry, phát hiện cờ flaky, soft assertions, và phân loại trạng thái.                         | **Tối thượng** |
| `qctool/execute/browser.py`       | **Playwright Driver**: Quản lý context cô lập cho từng testcase, auto-wait assertions bằng `expect()`, locator strategy (`data-testid`), và thu thập bằng chứng (trace/screenshot). | **Tối thượng** |
| `qctool/generate/from_openapi.py` | **API Test Generator**: Sinh testcase deterministic từ OpenAPI (Happy Path, Error Codes, BVA biên tham số, Missing Fields, Auth Matrix).                                            |  **Rất cao**   |
| `qctool/ui/crawl.py`              | **UI Crawler 2 pha**: Mở Chromium quét DOM trang web (Pha 1 ẩn danh, Pha 2 có auth), trích xuất element tương tác kèm `test_id` ra `ui-map.yaml`.                                   |  **Rất cao**   |
| `qctool/validate.py`              | **Quality Gate**: Kiểm tra toàn bộ bộ testcase (trùng ID, trùng nội dung, gap requirement, case mồ côi orphan, vocabulary hợp lệ).                                                  |  **Rất cao**   |
| `qctool/render/excel.py`          | **Excel Generator**: Kết xuất Testcase IR thành template bảng tính Excel 14 cột chuẩn openpyxl kèm Data Validation dropdowns và format màu.                                         |    **Cao**     |
| `qctool/render/results.py`        | **Two-Phase Backfiller**: Nạp file Excel đã sinh và điền ngược 4 cột kết quả runtime (`Actual Result`, `Status`, `Environment`, `Executed By / Date`).                              |    **Cao**     |
| `qctool/ingest/markdown.py`       | **Markdown Parser**: Bóc tách User Stories, Acceptance Criteria (Given/When/Then), Functional APIs, và NFRs từ file URD/SRS.                                                        |    **Cao**     |
| `qctool/ingest/flows.py`          | **Flow Parser**: Trích xuất Mermaid sequence diagrams, state machines, decision points, error surfaces thành cấu trúc luồng.                                                        |    **Cao**     |
| `qctool/report/__init__.py`       | **Report Generator**: Kết xuất `report.md`, `junit.xml`, `results.csv`, `results.json`.                                                                                             |    **Cao**     |
| `qctool/cli.py`                   | **CLI Interface**: Khai báo và xử lý các lệnh dòng lệnh `qctool all`, `ingest`, `generate`, `run`, `crawl`, `serve`.                                                                | **Trung bình** |
| `qctool/model.py`                 | **Data Models Ingest**: Khai báo `Requirement`, `ApiSpec`, `SourceRef`, và thuật toán `content_hash`.                                                                               | **Trung bình** |
| `qctool/config.py`                | **Config & Secrets**: Nạp cấu hình từ `.env` và biến môi trường, xác thực auth modes.                                                                                               | **Trung bình** |
| `qctool/web/app.py`               | **Local Web App**: HTTP server phục vụ Web UI chạy test cục bộ không cần framework ngoài.                                                                                           | **Trung bình** |

---

## D. Key Findings (16 phát hiện quan trọng nhất)

1. **Không có LLM trong runtime hiện tại**: Mặc dù tài liệu đề cập đến AI và LLM track ở roadmap M07, toàn bộ 100% logic hiện tại là **Deterministic Python Rule Engine**. Mọi case đều mang cờ `generated_by: "engine"`.
2. **Triết lý "Không nói dối" (No False Failure)**: Nếu testcase không thể chạy do thiếu điều kiện (tài khoản không có quyền, lỗi mạng máy test, thiếu thư viện axe), hệ thống bắt buộc đánh dấu `Blocked`, tuyệt đối không đánh dấu `Fail`. `Fail` chỉ được dùng khi sản phẩm thật sự trả kết quả sai.
3. **Template Excel 14 cột là bản ghi hai pha (Two-Phase Recording)**: File `.xlsx` được tạo ở phase Generate (điền 10 cột đặc tả), sau khi Execute xong thì hàm `fill_results()` mở chính file đó ra để điền tiếp 4 cột runtime (`Actual Result`, `Status`, `Environment`, `Executed By / Date`). QC không bao giờ phải đối chiếu 2 file rời rạc.
4. **Closed Action Vocabulary 25 Verbs**: Bất kỳ bước test nào cũng phải dùng một trong 25 verbs định nghĩa trong `ACTION_SPECS`. Bất kỳ verb lạ nào (hoặc do LLM bịa ra trong tương lai) đều bị chặn ngay tại `Step.validate()`.
5. **Cơ chế Semantic Content Hash**: `content_hash` của Requirement và TestCase chỉ băm nội dung ngữ nghĩa, cố ý **không băm số dòng tài liệu (`source.line`) hay `TestCase.id`**. Nhờ đó sửa lỗi chính tả ở đầu file tài liệu không làm đổi hash của testcase cũ, và hai testcase trùng bước nhưng khác ID sẽ bị phát hiện ngay lập tức.
6. **Crawl giao diện 2 pha (Anonymous & Authenticated)**: Webapp SPA luôn chuyển hướng về `/login` nếu chưa đăng nhập. Crawler bắt buộc chạy Pha 1 ẩn danh để ghi lại nút Login/SSO, sau đó mới nạp cookie chạy Pha 2 để ghi lại dashboard.
7. **Ưu tiên Locator `data-testid`**: Mapper và browser locator luôn ưu tiên `data-testid` (hoặc `data-test-id`, `data-cy`) trước nhãn hiển thị. Điều này bảo vệ testcase không bị gãy khi dev sửa câu chữ trên UI.
8. **Mỗi testcase UI một Browser Context riêng**: `start_case()` và `end_case()` tạo và huỷ browser context độc lập cho từng case. Cookie/storage của case trước không bao giờ rò rỉ sang case sau, loại bỏ hoàn toàn bẫy "chạy lẻ pass, chạy cả suite fail".
9. **Auto-wait Playwright Assertion**: Toàn bộ assertion UI dùng `expect(locator).to_be_visible()`, `to_have_text()`... để Playwright tự động polling chờ DOM cập nhật, giải quyết triệt để vấn đề flake do bất đồng bộ mạng của SPA.
10. **Tách riêng cờ Flaky khỏi Pass sạch**: Nếu một testcase fail ở lần chạy đầu nhưng pass ở lần retry, status vẫn là `Pass` nhưng được gắn cờ `flaky=True` và tách riêng ở Mục 6 của báo cáo để dev điều tra race condition.
11. **Bắt buộc phải có ít nhất một Assertion**: Testcase không có bước `assert.*` sẽ bị `TestCase.validate()` ném ngoại lệ chặn đứng từ chặng Generate. Không cho phép tồn tại testcase "chỉ chạy action rồi mặc định Pass".
12. **Bảo vệ Endpoint không có trong Spec**: Mapper từ chối map các câu văn xuôi có đường dẫn API nếu đường dẫn đó không tồn tại trong OpenAPI spec (`_drop_unverified_http`), ngăn chặn triệt để việc sinh request vào endpoint ảo gây 404 giả.
13. **Kiểm tra khả năng kích hoạt lỗi (`_can_trigger`)**: Generator chỉ sinh case mong đợi lỗi 422 khi endpoint có body hoặc query param có ràng buộc vi phạm được; không sinh case gọi request bình thường vào endpoint không body rồi mong đợi 422.
14. **Phân biệt rạch ròi giữa `manual` và `Blocked`**: Case nghiệp vụ có bước văn xuôi chưa thể map tự động được gán `execution="manual"` và status `Not Executed` (việc dành cho người làm). Chỉ những case thiếu điều kiện môi trường mới vào `Blocked`.
15. **Hỗ trợ NFR hiệu năng chuẩn phân vị**: Nhận diện chuỗi `p95 < 100ms`, tự động lấy 20 mẫu request HTTP để tính phân vị thứ 95 thay vì chỉ đo 1 lần duy nhất.
16. **Tự động bắt JWT Token từ Browser cho API**: Khi người dùng đăng nhập qua form IdP trên trình duyệt, `BrowserSession` tự động lắng nghe header `Authorization: Bearer ...` từ network request thật của app để trích xuất token cho các test API chạy sau đó mà không cần decode token thủ công.
