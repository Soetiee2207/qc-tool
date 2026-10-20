---
type: finding
status: draft
created: 2026-10-12
updated: 2026-10-12
lang: vi
changelog:
  - 2026-10-12 | claude | Khảo sát read-only: CLI, pipeline, web app, artifacts → yêu cầu UI
---

# Frontend discovery — QC Tool V2

Khảo sát **chỉ đọc** trên nhánh `agent-redesign` @ `6f0e97f` (+ thay đổi chưa commit ở
`qctool/web/app.py`). Mọi khẳng định trỏ về file/hàm thật. Phần "Đề xuất" (§6–§8) là
**chưa có trong code**. Không gọi LLM, không chạy E2E; ví dụ dữ liệu lấy từ artifacts có sẵn
của `projects/salonhub/auth/artifacts/` (chạy 2026-10-10), đã lược bí mật.

---

## 1. Executive summary

- **Engine đủ chín cho một UI mỏng.** `run_pipeline()` (`qctool/pipeline.py`) đã ghi trạng thái
  dạng máy-đọc-được cho từng lượt: `run.json` (trạng thái từng bước, ghi nguyên tử),
  `events.jsonl` (sự kiện có `stage/level/message`, đã redact), `summary.json`,
  `generation.json`, `results.json`. Docstring `qctool/artifacts.py` ghi rõ "UI đọc trực tiếp".
  **Chưa có UI nào đọc chúng** (`docs/tracking/todo.md:168` vẫn mở — xác nhận đúng).
- **Web UI hiện tại (`qctool ui`) là một form "ad-hoc" tách khỏi mô hình project.**
  `Handler._to_config` (`qctool/web/app.py`) tự dựng `PipelineConfig` từ form, **không** dùng
  `projects/<p>/<f>/qctool.yaml`, `expand_project`, `preflight`, `build_summary`. Hệ quả:
  LLM luôn tắt (`llm_enabled` mặc định `False`) → web **không sinh được case UI từ tài liệu**;
  không có fixture (`account:`), không có `write.deny`/`safe_controls`; không có `summary.json`.
  Mâu thuẫn với AGENTS.md "không có logic nào chỉ tồn tại trong giao diện".
- **Có một lỗ hổng cần sửa trước khi làm UI mới:** `GET /api/download?path=` phục vụ **mọi
  file dưới thư mục làm việc** — gồm `.env` (khoá LLM, mật khẩu), `artifacts/2-crawl/.token`,
  `.auth-state.json` (`Handler._download`). Mặc định bind `127.0.0.1` giảm rủi ro, nhưng
  `--host` mở được ra mạng; không kiểm `Host` header.
- **Nhiều chức năng UI cần là MISSING ở backend:** danh sách project/lượt chạy, lịch sử, huỷ
  lượt chạy, chạy lại một testcase, ghi quyết định review, tiến trình thực thi từng case.
- **Đề xuất:** 3 màn hình chính (Projects & Runs · New Run · Run, trong đó Run có 4 tab:
  Tiến trình · Testcase · Kết quả · File). Backend: giữ `http.server` stdlib, thêm ~8 endpoint
  **chỉ đọc artifacts**, và chạy pipeline bằng **subprocess `qctool run`** để có huỷ, cô lập
  lỗi, và dùng lại 100% đường đi của CLI (preflight, redact, summary, xác nhận chế độ ghi).
  Polling (theo offset `events.jsonl`) đủ dùng; SSE không cần cho MVP.

---

## 2. Current system diagram

```
                         ┌──────────────────────── CLI (qctool/cli.py) ───────────────────────┐
 projects/<p>/project.yaml│ init · check · run <p> [--<feature>] [--only AC] [--llm/--no-llm]   │
 projects/<p>/<f>/        │      [--skip-run] [--write|--safe] [--yes] [--trace-sensitive]      │
   qctool.yaml, urd.md,   │ trace <p> <TC> · demo · ui · step ingest|generate|exec|crawl        │
   srs.md, openapi.yaml   └───────┬────────────────────────────────────────────────────────────┘
 .env (QCTOOL_*)                  │ cli._each_feature → cli_run.cmd_project
                                  │   preflight() → run_pipeline() → build_summary() → redact()
                                  ▼
 ┌─────────────────────────── qctool/pipeline.py::run_pipeline(cfg, on_progress) ───────────────┐
 │ 1-ingest  ingest.ingest_feature → requirements.yaml                                          │
 │ 2-crawl   BrowserSession.login (chỉ auth.mode=browser) → .auth-state.json, .token,           │
 │           app-model.yaml (KEEP qua các lượt)                                                  │
 │ 3-generate generate.generate_all (OpenAPI, tất định) + generation.run_generation            │
 │           └─ agent/loop.author_intent  ── tool: read_docs · list_api · browser_observe ·     │
 │              browser_act · draft_case · dry_run · use_macro  (agent/tools.py, safety.py,     │
 │              gate.py)  → generation.json, testcases.yaml                                     │
 │ 4-render  render.render → testcases.xlsx (14 cột + sheet Review)                             │
 │ 5-execute execute.run_cases (HttpSession + BrowserSession) → results.json/.csv, junit.xml,   │
 │           evidence/ (*.png, *.trace.zip)                                                      │
 │ 6-report  report.render_markdown → report.md ; render.fill_results ghi ngược vào .xlsx       │
 │ Ghi chép: artifacts.RunTracker → run.json + events.jsonl + <bước>/stage.log, error.log       │
 └───────────────────────────────────────────────────────────────────────────────────────────────┘
                                  ▲
 ┌──────── Web (qctool/web/app.py, http.server stdlib) ────────┐
 │ GET /  · GET /api/config · POST /api/run · GET /api/jobs/<id>│  form ad-hoc → _to_config()
 │ GET /api/download?path=&inline=                              │  → thread → run_pipeline()
 │ JobStore trong RAM (mất khi tắt server)                       │  out: projects/web/<f>/artifacts
 └──────────────────────────────────────────────────────────────┘
 Sau `qctool run <p>`: summary.write_project_summary → projects/<p>/summary/<YYYY-MM-DD_HH-MM-SS>/
```

### Cái gì chạy được / dở dang / legacy

| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| CLI `init/check/run/trace/demo/step` | Chạy được | `cli.py::build_parser`, artifacts thật của SalonHub |
| Pipeline 6 bước + `run.json`/`events.jsonl` | Chạy được | `artifacts.py`, `projects/salonhub/auth/artifacts/run.json` |
| Authoring agent (LLM tool-calling + gate + dry-run) | Chạy được, `status: verified-partial` | `docs/findings/agent-redesign.md` |
| Báo cáo tổng hợp project + lịch sử | Chạy được, **chỉ CLI** | `summary.py`, `projects/salonhub/summary/README.md` |
| Web UI | **Dở dang**: chạy ad-hoc, không LLM, không project | `web/app.py::_to_config` |
| Web UI bản redesign (dark theme, danh sách case, evidence) | **Chưa commit** (+1400/−214 dòng) | `git diff --stat` |
| Sheet "Review" trong XLSX | Ghi ra được; **không ai đọc lại** | `render/excel.py:73`; `read_review_labels` chỉ dùng ở `tests/test_agent.py:218` |
| Chạy song song testcase | Chưa có | `todo.md:99` |
| `generation.profile: business/legacy`, scope `LEGACY_DIAGNOSTIC`, `legacy_testcases_path` | Deprecated (alias) | `PipelineConfig.from_file`, `cli_run.build_summary` |
| `step crawl` → `ui-map.yaml` (`ui/crawl.py`) | Legacy so với V2 (`app-model.yaml`); vẫn còn lệnh | AGENTS.md, `pipeline.py` không gọi crawl.py |
| Tên cũ `qctool serve` / `qctool all` | Đã thay bằng `ui` / `run` | `milestones.md:13` vs `cli.py` |

---

## 3. Real user workflows

### A. Tạo project/lượt chạy (tài liệu + OpenAPI + URL + credential)
1. `qctool init <p>/<f>` → `cli.cmd_init` ghi `project.yaml` (`PROJECT_TEMPLATE`) + `<f>/qctool.yaml` (`FEATURE_TEMPLATE`).
2. Người dùng **tự chép** `urd.md`, `srs.md`, `openapi.yaml` vào `projects/<p>/<f>/`.
3. Sửa YAML: `web`, `api`, `llm: true`, `account: {role, login_for: [AC…], test_values}`.
4. Credential **chỉ ở `.env`** (`QCTOOL_USERNAME/PASSWORD/BEARER_TOKEN`, `QCTOOL_LLM_*`).
- Web hiện tại: form nhập *đường dẫn trên đĩa* `docs_dir`, `openapi`, `base_url`, `web_url`, `auth_mode`, `username/password/bearer_token` (gửi trong JSON). Không upload file, không tạo project.

### B. Cấu hình LLM, trình duyệt, fixture, an toàn, budget
| Nhóm | Nơi cấu hình | Đọc bởi |
|---|---|---|
| LLM | `.env`: `QCTOOL_LLM_ENABLED/BASE_URL/API_KEY/MODEL/TIMEOUT_SECONDS/THINKING`; YAML `llm: true`; CLI `--llm/--no-llm` | `agent/llm_provider.py::load_llm_provider`, `PipelineConfig.from_file` |
| Trình duyệt | YAML `ui.{evidence, trace, trace_sensitive, retry, axe, soft_assert, viewport}`, `out.headless`; CLI `--show-browser`, `--trace-sensitive` | `PipelineConfig.from_file`, `_viewport_of` |
| Fixture | `account:` (gọn) → `test_fixtures` (đầy đủ) | `config._expand_account`, `data/fixtures.py::load_fixture_store` |
| An toàn | `mode: safe|write`, `write.deny`, `exploration.{safe_controls, safe_paths, background_paths}`, `provisioning.enabled` | `PipelineConfig`, `agent/safety.py` |
| Budget | `generation.budget` (mặc định `AGENT_BUDGET = {max_turns:14, max_tokens:90000, max_seconds:480, completion_tokens:2200}`), giới hạn cứng trong `loop.Budget` | `config.py:135`, `agent/loop.py:22-32` |
- Web: chỉ `timeout_seconds`, `verify_ssl`, `skip_run`, `ui_retry/evidence/trace/axe/headless`, `soft_assert`. **Không có** LLM, fixture, an toàn, budget.

### C. Kiểm tra đầu vào trước khi chạy
- `qctool check <p>` → `cli_run.preflight(args, require_target=False)`: đọc YAML, `expand_project`, kiểu boolean, URL hợp lệ, `auth.mode`, ingest tài liệu, `load_endpoints(openapi)`, `load_llm_provider()` nếu LLM bật. **Không** gọi model/browser/API. In `PREFLIGHT OK | Requirements | API operations | Warnings`.
- Web: chỉ kiểm đường dẫn tồn tại + URL bắt đầu `http(s)` trong `_to_config`. **Không có preflight.**

### D. Chạy toàn bộ generation → execution
- `qctool run <p> [--<f>]` → `_each_feature` → (xác nhận chế độ ghi: `confirm_write`, cần TTY hoặc `--yes`) → `cmd_project` → `run_pipeline(cfg, on_progress, resolution_llm, exploration_llm)` → `summary.json`, `pipeline.log` → `summary.write_project_summary` (khi chạy cả project).
- Exit code: `0 OK · 1 lỗi sản phẩm · 2 lỗi cấu hình/pipeline · 3 sinh case chưa đủ · 4 có case bị chặn` (`cli._EXIT`).
- Web: `POST /api/run` → `_start_job` → thread daemon → `run_pipeline(cfg, on_progress=job.log)`.

### E. Theo dõi tiến trình
- CLI: in từng dòng `[stage] message` và ghi `artifacts/pipeline.log` trực tiếp.
- Dữ liệu sẵn có: `run.json` (`current_stage`, `stages.*.status/started_at/finished_at/last_message/outputs/error_log`), `events.jsonl`.
- **Tool call của agent** có trong events: `AgentTools` gọi `on_progress('agent', f'{case_id}: {tool} → OK|cần sửa')` (`agent/tools.py:320`), alias `agent→generate`. Ví dụ thật: `TC_AUTH_001: browser_observe → OK`.
- **Hành động Playwright khi thực thi: không có tiến trình live** — `execute.run_cases` không nhận callback; chỉ có "Chạy 13 testcase…" rồi tới kết quả cuối.
- Web: poll `GET /api/jobs/<id>` mỗi 750 ms, trả toàn bộ `messages`.

### F. Xem testcase sinh ra, expected, nguồn, review
- `3-generate/testcases.yaml` (bước runner chạy), `3-generate/generation.json` (cases + `generation_status` + `review_reasons` + `provenance` + `source_intent` + `agent_history` + coverage theo requirement/obligation), `4-render/testcases.xlsx` (14 cột + sheet Review), `6-report/report.md` mục "Testcase cần review oracle".
- Web: chỉ hiện kết quả chạy (`CaseResult.to_dict`), không hiện testcase/nguồn/review.

### G. Xem Pass/Fail/Blocked/Not Executed + bằng chứng
- `5-execute/results.json` (`summary` + `results[]` với `steps[]`, `actual[]`, `blocked_reason`, `flaky`, `attempts`, `evidence`), `results.csv`, `report.md`.
- Web (bản chưa commit): danh sách case có lọc theo trạng thái, bảng bước, nút ảnh/trace — **nhưng link bằng chứng hỏng** (xem §4.3).

### H. Tải báo cáo, Excel, ảnh, trace
- CLI: mở file trong `artifacts/`; `qctool trace <p> <TC>` → `playwright show-trace`.
- Web: `GET /api/download?path=<path>` cho report.md, xlsx, yaml, csv, junit.

### I. Mở lại lượt chạy cũ / chạy lại testcase có sẵn
- Lượt mới nhất của mỗi feature: đọc `<f>/artifacts/` (bị **ghi đè** mỗi lượt, trừ `KEEP`).
- Lượt cũ: `projects/<p>/summary/<ts>/` (chép `COPY` trong `summary.py`) + `summary/README.md` (index). Chỉ có khi chạy bằng `qctool run <p>`.
- Chạy lại testcase đã có: `qctool step exec <a>/3-generate/testcases.yaml --base-url … --xlsx …` (`cli.cmd_run_testcases`) — chạy **cả file**, không lọc theo case, dùng `.env` chứ không dùng config project. `--only` của `run` lọc **intent AC lúc sinh**, không phải lúc chạy.
- Web: `JobStore` trong RAM; không liệt kê, không mở lại sau khi restart.

---

## 4. Existing web/API capabilities

### 4.1 Endpoint có thật (`qctool/web/app.py::Handler`)

| Method | Path | Request | Response | Ghi chú |
|---|---|---|---|---|
| GET | `/`, `/index.html` | — | HTML một trang (`PAGE`) | Bản chưa commit tải font từ Google Fonts |
| GET | `/api/config` | — | `{base_url, auth_mode, username, oidc_issuer}` từ `.env` | Lộ username (không lộ password) |
| POST | `/api/run` | JSON: `docs_dir, openapi, feature, module, base_url, web_url, auth_mode, username, password, bearer_token, timeout_seconds, verify_ssl, skip_run, created_by, ui_headless, ui_retry, ui_evidence, ui_trace, ui_axe, soft_assert` | `202 {job_id}` · `400 {error}` | Tối đa 2 MB; không kiểm `Content-Type` |
| GET | `/api/jobs/<id>` | — | `Job.snapshot()` (xem §5.7) | 404 nếu không có trong RAM |
| GET | `/api/download` | `?path=<bất kỳ>&inline=1` | file | Chỉ chặn ngoài `cwd` |

### 4.2 Phân loại năng lực

| Năng lực | Mức | Căn cứ |
|---|---|---|
| Bắt đầu lượt chạy qua HTTP | **PARTIAL** | Có `POST /api/run` nhưng chỉ ad-hoc: không project, không LLM, không fixture, không preflight |
| Dừng/huỷ lượt chạy | **MISSING** | Không có endpoint; thread daemon; không có cờ huỷ trong `run_pipeline`/`run_generation`/`run_cases` |
| Theo dõi tiến trình | **PARTIAL** | Poll `/api/jobs/<id>`; không đọc `run.json`/`events.jsonl`; không có tiến trình từng case khi thực thi |
| Stream log (SSE/WebSocket) | **MISSING** | Chỉ polling |
| Liệt kê/xem testcase sinh ra | **MISSING** (HTTP) / **EXISTING** (file) | `generation.json`, `testcases.yaml` có; không endpoint |
| Review / sửa / duyệt testcase | **MISSING** (HTTP) · **PARTIAL** (Excel) | Sheet Review ghi ra; `read_review_labels` không được pipeline gọi |
| Chạy lại một testcase | **MISSING** | `run_cases` chạy cả danh sách; `step exec` không lọc |
| Tải report/artifact an toàn | **PARTIAL — không an toàn** | Đọc được mọi file dưới `cwd`, gồm `.env`, `.token` |
| Lịch sử lượt chạy | **MISSING** (HTTP) · **PARTIAL** (file, chỉ CLI project run) | `summary/<ts>/summary.json`; JobStore trong RAM |
| Nhiều lượt chạy đồng thời | **PARTIAL — không an toàn** | `ThreadingHTTPServer` cho phép; hai job cùng `feature` dùng chung `out_dir`, `RunTracker._clean` xoá artifacts của nhau |
| Liệt kê project/feature | **MISSING** (HTTP) · **EXISTING** (`cli.features_of`, `resolve_targets`) | |
| Preflight | **MISSING** (HTTP) · **EXISTING** (`cli_run.preflight`) | |
| Chế độ ghi | **MISSING** trên web (đúng ý — cần xác nhận) | `confirm_write` cần TTY/`--yes` |

### 4.3 Lỗi cụ thể trong web UI hiện tại (đọc code, không chạy)

1. **Lộ file bí mật** — `_download` chỉ kiểm `resolved.relative_to(Path.cwd())`; `.env` nằm ở gốc repo. Không có kiểm `Host` (DNS rebinding) và `_read_json` không bắt buộc `application/json` (POST "simple request" từ trang khác vẫn khởi chạy được job).
2. **Link bằng chứng hỏng** — UI đọc `c.evidence.screenshot`, nhưng `browser.py` ghi `evidence.screenshots` (list) và `evidence.trace` chỉ là **tên file** (`"TC_AUTH_005.trace.zip"`), không kèm `5-execute/evidence/` → `/api/download` tìm ở `cwd` → 404.
3. **Lệnh trace sai** — UI gợi ý `qctool trace <feature> <TC>`, nhưng lượt web ghi vào `projects/web/<f>/artifacts` không có `qctool.yaml` → `resolve_targets` báo không thấy project.
4. **Timeline nhảy lùi** — `Job.stage` nhận tên thô (`agent`, `run`, `ui`, `crawl`, `done`); `stageMap` trong JS thiếu `agent`/`ui`/`done` → trong lúc agent chạy, mọi bước về "chưa chạy"; `stage_durations` khoá theo `run` nên ô "execute" không bao giờ có thời gian. (`artifacts.ALIASES` đã giải quyết đúng việc này — web không dùng.)
5. **Mất kết quả một phần khi lỗi** — `_start_job` chỉ dựng `job.result` khi không lỗi; khi `Generation INVALID_TESTCASES` vẫn có `generation.json`, `testcases.xlsx`, `error.log` nhưng UI không chỉ tới.
6. **Không redact theo fixture** — web không nạp `fixture_store`, nên `run_pipeline.safe()` không redact; cũng không qua `cli_run.redact`.

---

## 5. Data schemas and artifacts

### 5.1 Bố cục artifacts (`qctool/artifacts.py`)

```
projects/<p>/
  project.yaml
  <f>/qctool.yaml, urd.md, srs.md, openapi.yaml
  <f>/artifacts/                      # ghi đè mỗi lượt (trừ KEEP)
    run.json  events.jsonl  pipeline.log*  summary.json*       (* chỉ khi chạy bằng CLI)
    1-ingest/requirements.yaml, stage.log
    2-crawl/app-model.yaml, .auth-state.json†, .token†, stage.log   († KEEP, BÍ MẬT)
    3-generate/generation.json, testcases.yaml, stage.log
    4-render/testcases.xlsx
    5-execute/results.json, results.csv, junit.xml, evidence/<TC>*.png|.trace.zip
    6-report/report.md
    <bước>/error.log                  # khi tracker.fail()
  summary/<YYYY-MM-DD_HH-MM-SS>/summary.json, summary.md, testcases.csv, <f>/…  (bản chép)
  summary/README.md                   # index lịch sử
projects/web/<f>/artifacts/           # lượt chạy từ web UI (WEB_ROOT)
```

### 5.2 Cấu hình pipeline (thật, `projects/salonhub/`)

```yaml
# project.yaml (gọn)                      # auth/qctool.yaml
web: https://salonhub-soe.vercel.app       account:
api: https://salonhub-3cg8.onrender.com      login_for: [001-1, 001-4, 003-1, 003-3]
llm: true                                    test_values:
account: {role: customer}                      "001-3": {email: "...@example.com", password: "<giá trị giả>"}
run: {timeout_seconds: 45}
ui: {evidence: always, trace: true}
mode: safe
write: {deny: [PUT /api/auth/change-password]}
exploration: {safe_controls: [...], safe_paths: [/register]}
```
`expand_project` mở thành dạng đầy đủ: `docs_dir`, `web_url`, `run.base_url`, `llm.enabled`,
`feature`, `module`, `out.dir`, `generation.budget`, `auth.mode: browser`, `test_fixtures.{fixtures,
bindings, acquisition}`. Trường của `PipelineConfig`: xem `pipeline.py:46-100`.

### 5.3 Requirement (`1-ingest/requirements.yaml`)
Top-level: `feature, feature_dir, generated_by, counts, sources, attachments, flows, warnings, requirements[], features`.
```json
{"id":"AC-auth-001-1","kind":"acceptance_criterion","belongs_to":"US-auth-001","source_ids":["AC-001-1"],
 "title":"POST /api/auth/login trả 200 với success=true; URL chuyển tới /",
 "given":"Phiên anonymous ở /login; …","when":"Nhập email; nhập password; bấm Đăng nhập…",
 "then":"POST /api/auth/login trả 200 …","traces_to":["US-auth-001"],
 "content_hash":"sha256:…","source":{"file":"urd.md","line":21,"quote":"POST /api/auth/login trả 200 …"}}
```

### 5.4 Kết quả generation (`3-generate/generation.json` = `GenerationResult.to_dict()`)
Keys: `cases[] · executable_cases[] · unresolved_cases[] · generated_cases[] · coverage.requirements[] ·
intent_coverage · validation{total, errors, warnings, gaps, needs_mapping, manual_cases, by_*} ·
issues[{stage, code, message, testcase_id}] · status · agent_history[] · design_audit[] ·
test_data_preparations[] · success · generation_profile · case_scopes`.

- `status` (`generation.GenerationStatus`): `SUCCESS · NEEDS_REVIEW · INVALID_TESTCASES · UNASSESSABLE_COVERAGE · INCOMPLETE_COVERAGE · FAILED`.
- Coverage theo requirement: `{requirement_id, kind, status: covered|…, source{file,line,quote}, traced_testcase_ids[], obligations[{id, expected, status, testcase_ids, reason}]}`.

### 5.5 Lịch sử tool call (`agent_history[]`)
```json
{"case":{…TestCase…},"intent":{"id","req_id","given","when","expected","title","source_ref"},
 "history":[{"turn":2,"tool":"browser_observe","ok":true,"failed_step":null,"error":null,
             "errors":[],"arguments":{"url":"https://…/login"}}],
 "provider_attempts":[{"attempt":1,"http_status":200,"finish_reason":"…",
   "usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0},"cache_usage":{…},"error_code":null}],
 "stop_reason":"READY","dry_run_passed":true,"issues":[],"last_draft":{…}}
```
`stop_reason` (`agent/loop.py`): `READY · TIME_BUDGET · TOKEN_BUDGET · MODEL_ABSTAINED · REPEATED_ERROR · PROVIDER_ERROR · AGENT_ERROR`.

### 5.6 Testcase sinh ra (`TestCase`, `qctool/core/testcase.py`)
```json
{"id":"TC_AUTH_001","module":"AUTH","title":"AC-auth-001-1: Đăng nhập thành công …","objective":"…",
 "priority":"Medium","type":"positive","technique":"schema_conformance","traces_to":["AC-auth-001-1"],
 "generated_by":"llm","execution":"manual?","preconditions":["…"],
 "test_data":{"email":"active_user.email","password":"active_user.password",
   "_fixture_refs":{"active_user.password":{"fixture":"active_user","available":true,
                    "source":{"type":"env","name":"QCTOOL_PASSWORD"}}}},
 "steps":[{"seq":3,"kind":"when","action":"ui.fill","args":{"target":"login-email-input","value":"active_user.email"},
           "source":{"req_id":"AC-auth-001-1","quote":"Nhập email; …"}}],
 "expected":["…"],"content_hash":"sha256:…","provenance":{"source_quote":"…","source_ref":"urd.md"},
 "generation_status":"ready","review_reasons":[],"obligation_ids":["AC-auth-001-1:then"],"source_intent":{…}}
```
`test_data` chỉ chứa **alias** fixture, không chứa giá trị thật (đã kiểm). `action` thuộc 40 verb của
`ACTION_SPECS`; `perform.unmapped` / `assert.unmapped` = case chưa map (thủ công). Văn bản người đọc
lấy qua `describe()`/`expects()` (cùng nguồn với cột Excel).

### 5.7 Trạng thái review
- Theo case: `generation_status ∈ {ready, needs_review, manual, blocked_env}` + `review_reasons[]` (vd `TOKEN_BUDGET`, mã blocker test-data).
- Quyết định người: sheet `Review` của XLSX — cột `Decision` (accepted/rejected), `Reviewer note`. **Không được đọc lại** bởi pipeline.

### 5.8 Kết quả thực thi (`5-execute/results.json`, `RunResult`/`CaseResult`/`StepResult`)
```json
{"started_at":"2026-10-10 16:16:14","finished_at":"…","base_url":"https://…","environment":"https://…",
 "summary":{"total":13,"Pass":11,"Fail":0,"Blocked":0,"Not Executed":2,"pass_rate":100.0},
 "results":[{"case_id":"TC_AUTH_003","module":"AUTH","title":"…","status":"Pass",
   "actual":["[OK] HTTP 401 — đúng như mong đợi", "…"],"duration_ms":3772.8,
   "steps":[{"seq":5,"action":"ui.click","ok":true,"detail":"Captured POST /api/auth/login → HTTP 401","duration_ms":1490.3}],
   "generation_status":"ready","review_reasons":[],"step_count":8,
   "blocked_reason":"(khi Blocked)","manual":true,"attempts":["…"],"flaky":true,
   "evidence":{"screenshots":["TC_X-fail.png"],"trace":"TC_AUTH_005.trace.zip","console":["…"],"network":["POST … → HTTP 401"]}}]}
```
Trạng thái: `Pass · Fail · Blocked · Not Executed` + cờ `flaky` (chỉ khi Pass ở lần chạy lại).
Đường dẫn bằng chứng **tương đối với `5-execute/evidence/`**.

### 5.9 Tóm tắt lượt chạy
- `run.json` (`RunTracker.state`): `{feature, status: running|done|failed, started_at, finished_at, current_stage, error{stage,message,log}, mode: safe|write, stages{<bước>:{dir, status: pending|running|done|skipped|failed, started_at, finished_at, last_message, outputs[], reason, error_log}}}`.
- `events.jsonl`: `{"t":"2026-10-10T16:11:36+07:00","stage":"generate","level":"info|detail|error","message":"TC_AUTH_001: draft_case → OK"}`.
- `summary.json` (`cli_run.build_summary`, chỉ CLI): `status ∈ {SUCCESS, EXECUTION_FAILED, DIAGNOSTIC_EXECUTION_FAILED, GENERATION_INCOMPLETE, EXECUTION_INCOMPLETE, PIPELINE_ERROR}`, `exit_code`, `counts`, `generation_status`, `requirements`, `obligations`, `generated_testcases`, `executable_testcases`, `executable_coverage{covered,total,complete}`, `unresolved_cases[{testcase_id, code, user_action, runtime_status}]`, `unresolved_test_data[]`, `execution_blockers[]`, `flaky_cases`, `artifacts{…paths}`.
- Web `Job.snapshot()`: `{id, started_at, stage, messages[], done, result{feature,total_cases,counts,pass_rate,*_path,run_dir,gaps,needs_mapping,cases[]}, error, stage_durations, elapsed_seconds, current_action}`.

### 5.10 Lịch sử
`projects/<p>/summary/<ts>/summary.json`: `{project, started_at, finished_at, duration_seconds, exit_code, write_features[], totals{Pass,Fail,Blocked,Not Executed,total,flaky}, features[{name, exit_code, status, …}]}` + `summary/README.md`. Không có lịch sử cho lượt chạy một feature lẻ ngoài bản ghi đè trong `artifacts/` — trừ khi chạy qua `qctool run <p> --<f>` (vẫn ghi summary vì targets thuộc cùng project).

---

## 6. Proposed minimal screens (đề xuất — chưa có)

Ba màn hình; mọi chi tiết của một lượt chạy gom vào **một** màn hình có tab. Không có màn
Settings: cấu hình nằm trong YAML/.env và được **hiển thị chỉ đọc** ở New Run.

### 6.1 Projects & Runs (trang chủ)
- **Mục tiêu:** biết feature nào đang ổn/hỏng, mở lượt gần nhất, bắt đầu chạy.
- **Thông tin:** bảng project → feature: trạng thái lượt cuối (`run.json.status`), thời điểm, `counts` 4 trạng thái + flaky, `summary.json.status` (nhãn `cli._EXIT`), chế độ `safe/write`. Dưới mỗi project: lịch sử `summary/<ts>/` (5 lượt gần nhất).
- **Hành động:** Mở lượt · Check · Run feature · Run cả project.
- **Nguồn:** `cli.features_of`, `<f>/artifacts/run.json`, `summary.json`, `summary/*/summary.json`.
- **Thiếu:** endpoint liệt kê; endpoint lịch sử.
- **Trạng thái rỗng:** "Chưa có project — `qctool init <p>/<f>`" (UI không tạo project trong MVP). Feature chưa chạy: "Chưa chạy". `run.json` `running` nhưng không có tiến trình sống → "Bị gián đoạn" (không được hiện "đang chạy").

### 6.2 New Run (một panel/drawer, không phải trang wizard)
- **Mục tiêu:** chọn đích và chạy an toàn.
- **Thông tin:** project/feature đã chọn; cấu hình đã mở rộng **chỉ đọc, đã redact** (web, api, LLM bật/tắt + model, auth.mode, fixture alias và trạng thái env có/không, `mode`, `write.deny`, budget); kết quả preflight (số requirement, số operation, cảnh báo).
- **Hành động:** override giống cờ CLI: `--only AC…`, `--no-llm`, `--skip-run`, `--show-browser`, (tuỳ chọn) `--trace-sensitive` có cảnh báo. Nút **Check** rồi **Run**.
- **Không đưa vào MVP:** chế độ ghi (chỉ CLI có xác nhận), nhập mật khẩu/token trên web.
- **Nguồn:** `PipelineConfig.from_file` + logic override của `cli_run.preflight`.
- **Lỗi:** hiện nguyên thông điệp `PreflightError` (đã được viết cho người đọc).

### 6.3 Run (một lượt của một feature) — 4 tab
| Tab | Mục tiêu | Nội dung | Nguồn |
|---|---|---|---|
| **Tiến trình** | Biết đang ở đâu, kẹt ở đâu | Stepper 6 bước (`stages.*.status`, thời lượng), dòng sự kiện (lọc `info`/`detail`/`error`), nhóm tool call theo `TC_…`, link `error.log`, nút Huỷ | `run.json`, `events.jsonl` |
| **Testcase** | Kiểm tra case sinh ra có cơ sở không | Bảng: ID, tiêu đề, `generation_status`, `review_reasons`, AC; chi tiết: bước (qua `describe()`), expected (qua `expects()`), trích dẫn nguồn (`provenance`, `source_intent`), lịch sử tool call + `stop_reason` + token; coverage theo requirement/obligation; mục "chưa có test" (`validation.gaps`) | `generation.json`, `testcases.yaml` |
| **Kết quả** | Xem lỗi sản phẩm và bằng chứng | Đếm Pass/Fail/Blocked/Not Executed + flaky **kèm mẫu số**; mặc định lọc Fail; chi tiết bước, `blocked_reason`, `attempts`, ảnh inline, link trace + lệnh `qctool trace`; khối "Cần hành động" từ `summary.json.unresolved_cases/execution_blockers` | `results.json`, `summary.json` |
| **File** | Tải về | report.md, testcases.xlsx, yaml, csv, junit, evidence/*.zip — từ `stages.*.outputs` | `run.json` |

- **Rỗng/đang tải:** tab Kết quả khi `execute` = `skipped` → hiện `reason` ("Bỏ qua chạy test (skip_run)"); khi `failed` → hiện `error.message` + link `error.log` + các output đã có.
- Không biểu đồ, không KPI trang trí; số liệu phải giữ đúng nghĩa 4 trạng thái (AGENTS.md "KHÔNG NÓI DỐI").

### Bảng ánh xạ UI → backend

| UI element / action | Backend function / endpoint | Data source | Trạng thái |
|---|---|---|---|
| Danh sách project/feature | `cli.features_of`, `cli.resolve_targets` → *đề xuất* `GET /api/projects` | `projects/*/*/qctool.yaml` | Function EXISTING · endpoint MISSING |
| Trạng thái lượt cuối mỗi feature | *đề xuất* `GET /api/projects` | `<f>/artifacts/run.json`, `summary.json` | File EXISTING · endpoint MISSING |
| Lịch sử lượt chạy project | `summary.write_project_summary` (ghi) → *đề xuất* `GET /api/projects/<p>/history` | `summary/<ts>/summary.json` | PARTIAL (chỉ CLI project run) |
| Xem cấu hình đã mở rộng | `PipelineConfig.from_file`, `config.expand_project` | YAML + `.env` | Function EXISTING · endpoint MISSING |
| Nút Check | `cli_run.preflight` → *đề xuất* `POST /api/check` | YAML, docs, OpenAPI | Function EXISTING · endpoint MISSING |
| Nút Run (project/feature) | `cli_run.cmd_project` / `qctool run` → *đề xuất* `POST /api/runs` | — | PARTIAL (`POST /api/run` chỉ ad-hoc) |
| Form ad-hoc (đường dẫn + URL) | `POST /api/run`, `Handler._to_config` | form | EXISTING (thiếu LLM/fixture) |
| Nút Huỷ | — | — | MISSING |
| Stepper tiến trình | `RunTracker` → *đề xuất* `GET /api/runs/<p>/<f>/state` | `run.json` | File EXISTING · endpoint MISSING |
| Dòng sự kiện + tool call agent | `RunTracker.event`, `AgentTools` progress → *đề xuất* `GET …/events?after=N` | `events.jsonl` | File EXISTING · endpoint MISSING (web chỉ có `/api/jobs/<id>.messages`) |
| Tiến trình từng case khi thực thi | `execute.run_cases` | — | MISSING (không có callback) |
| Bảng testcase + generation status | *đề xuất* `GET …/testcases` | `generation.json`, `testcases.yaml` | File EXISTING · endpoint MISSING |
| Bước/expected dạng câu | `TestCase.describe()`/`expects()` | `testcases.yaml` | Function EXISTING · endpoint MISSING |
| Trích dẫn nguồn, coverage | — | `generation.json.cases[].provenance`, `.coverage` | File EXISTING · endpoint MISSING |
| Lịch sử tool call, token | — | `generation.json.agent_history` | File EXISTING · endpoint MISSING |
| Ghi quyết định review | `render.excel.read_review_labels` (chỉ đọc, chưa dùng) | XLSX sheet Review | MISSING |
| Sửa testcase | — | — | MISSING (và nên giữ ngoài MVP) |
| Kết quả Pass/Fail/Blocked/NE + flaky | `CaseResult.to_dict`; `/api/jobs/<id>.result.cases` (chưa commit) | `results.json` | PARTIAL (chỉ job còn trong RAM) |
| Ảnh lỗi / trace | `/api/download` | `5-execute/evidence/` | PARTIAL — link hỏng (§4.3-2), không an toàn (§4.3-1) |
| "Cần hành động" | `cli_run.build_summary` | `summary.json` | File EXISTING (CLI) · web không tạo |
| Tải report/xlsx/csv/junit | `/api/download?path=` | `stages.*.outputs` | PARTIAL — không an toàn |
| Mở trace bằng Playwright | `cli.cmd_trace` | evidence | EXISTING (CLI), lệnh gợi ý trên web sai |
| Chạy lại một testcase | — | `testcases.yaml` | MISSING |
| Chạy lại testcase đã có (cả file) | `cli.cmd_run_testcases` | `testcases.yaml` | EXISTING (CLI) · endpoint MISSING |

---

## 7. Backend/API gaps (đề xuất tích hợp tối thiểu)

### 7.1 Nguyên tắc
- Giữ `http.server` stdlib (docstring `web/app.py`: không thêm phụ thuộc). Không cần framework.
- **Artifacts là nguồn sự thật**, không phải RAM: mọi endpoint đọc đều đọc file → mở lại được sau restart, và lượt chạy bằng CLI hiện lên UI như lượt chạy bằng web.
- **Chạy bằng subprocess** `python -m qctool run <p> --<f> [cờ]` thay cho thread gọi `run_pipeline` trực tiếp:
  - dùng lại nguyên `preflight → run_pipeline → build_summary → redact → summary` của CLI (đúng luật "không có logic chỉ ở giao diện");
  - **huỷ được** (terminate process group, kéo theo Chromium);
  - chế độ ghi tự bị từ chối vì không có TTY/`--yes` (`confirm_write`) — an toàn mặc định;
  - lỗi/treo của Playwright không làm sập server.
  - Đánh đổi: khi bị kill, `run.json` kẹt `running`. Web phải ghi dấu huỷ (vd `artifacts/.cancelled` hoặc gọi `RunTracker`-tương đương để đặt `failed` + lý do "Người dùng huỷ") — nếu không là vi phạm luật "`run.json` mãi `running` là UI nói dối".

### 7.2 Endpoint cho MVP

| Endpoint | Làm gì | Tái dụng |
|---|---|---|
| `GET /api/projects` | project → feature → `run.json` tóm tắt + `summary.json.status` | `cli.features_of` |
| `GET /api/projects/<p>/history` | danh sách `summary/<ts>/summary.json` | `summary._json` |
| `POST /api/check` `{project, feature?, overrides}` | preflight, trả số liệu hoặc thông điệp lỗi | `cli_run.preflight` (dựng `argparse.Namespace`) |
| `POST /api/runs` `{project, features?, only?, llm?, skip_run?, show_browser?}` | spawn subprocess; 409 nếu feature đang chạy | `qctool run` |
| `POST /api/runs/<p>/<f>/cancel` | kill process group + ghi trạng thái huỷ | mới |
| `GET /api/runs/<p>/<f>/state` | `run.json` + `{alive: bool}` | file |
| `GET /api/runs/<p>/<f>/events?after=<n>` | dòng `events.jsonl` từ offset n | file |
| `GET /api/runs/<p>/<f>/testcases` | chiếu gọn `generation.json` (+ `describe()/expects()`) | `TestCase`, `generate.loader` |
| `GET /api/runs/<p>/<f>/results` | `results.json` + `summary.json` | file |
| `GET /api/runs/<p>/<f>/files/<rel>` | tải file trong `artifacts/` của feature đó | thay `/api/download` |

Lịch sử chạy cũ (`summary/<ts>/<f>/`) dùng chung các GET trên với tham số `?snapshot=<ts>`.

### 7.3 Polling hay SSE
**Polling**, 1–2 s, theo offset `events.jsonl` + đọc `run.json`. Lý do: file đã ghi nguyên tử
(`RunTracker._save` dùng `replace`), polling tự phục hồi khi đóng/mở tab, không giữ kết nối dài
trên `http.server`. Lượt `auth` thật mất ~6 phút (16:11:27 → 16:17:27), sự kiện thưa (111 dòng) —
SSE không mang lại gì đáng kể.

### 7.4 Kiểm tra đường dẫn và bí mật
- Đích chạy chỉ là **tên** `project`/`feature` đã có trong danh sách `features_of` — không nhận đường dẫn tuỳ ý.
- File phục vụ: `resolve()` rồi `relative_to(<f>/artifacts)` (hoặc `summary/<ts>`); **chặn dotfile** (`.token`, `.auth-state.json`, `.env`); chặn symlink ra ngoài.
- Bỏ (hoặc giới hạn) `/api/download?path=` hiện tại.
- Kiểm `Host` ∈ {`127.0.0.1:<port>`, `localhost:<port>`}; POST bắt buộc `Content-Type: application/json` (chặn CSRF dạng form); cảnh báo khi `--host` khác loopback.
- Không nhận mật khẩu/token qua web ở chế độ project; chỉ hiện "`QCTOOL_USERNAME`: đã đặt/chưa đặt". `/api/config` không trả `username` nữa.
- Trace có `trace_sensitive`: hiện cảnh báo trước khi tải.
- Mọi text trả về đã qua `RunTracker.redact`/`cli_run.redact` vì đọc từ file; không đọc `pipeline.log` thô qua API nếu chưa chắc đã redact (nó đã được `cmd_project` redact khi ghi — giữ như vậy).

### 7.5 Đồng thời
Mỗi `artifacts/` là một khoá: tối đa **một** lượt đang chạy mỗi feature (409 nếu trùng). Đề xuất MVP
giới hạn **một** lượt toàn cục (trình duyệt + chi phí LLM; CLI cũng chạy tuần tự từng feature).

### 7.6 Thay đổi engine nhỏ, chỉ khi cần (sau MVP)
- Callback tiến trình cho `execute.run_cases` (một `notify('run', f'{case_id}: {status}')` mỗi case) để tab Tiến trình có dữ liệu ở bước execute.
- Lọc `case_ids` cho `run_cases`/`step exec` → "chạy lại một testcase".
- Đọc sheet Review (hoặc sidecar JSON khoá theo `content_hash`) — chỉ làm **nhãn**, không đổi trạng thái runtime (AGENTS.md).

---

## 8. Recommended MVP implementation order

1. **Vá an toàn** (không phụ thuộc UI mới): giới hạn `/api/download` vào `artifacts/`, chặn dotfile, kiểm `Host` + `Content-Type`; sửa đường dẫn bằng chứng (`5-execute/evidence/` + `screenshots[]`).
2. **Chỉ đọc**: `GET /api/projects`, `…/state`, `…/events`, `…/testcases`, `…/results`, `…/files`. Màn Projects & Runs + màn Run (4 tab) trên artifacts **đã có** của SalonHub — có ích ngay, không tốn LLM.
3. **Check**: `POST /api/check` + panel New Run (cấu hình chỉ đọc + preflight).
4. **Run + Cancel** qua subprocess, polling, khoá theo feature, ghi trạng thái huỷ.
5. **Lịch sử** (`summary/<ts>`).
6. *(Sau MVP)* tiến trình từng case; chạy lại một testcase; ghi quyết định review.
7. *(Quyết định)* giữ hay bỏ form ad-hoc hiện tại — xem D-câu hỏi dưới.

---

## 9. Risks and unresolved questions

| # | Vấn đề | Tác động | Cần ai quyết |
|---|---|---|---|
| R1 | `/api/download` đọc được `.env`, `.token` | Lộ khoá LLM, mật khẩu tài khoản test | Sửa ngay (bước 1) |
| R2 | Artifacts bị **ghi đè** mỗi lượt; lịch sử chỉ có khi chạy cả project qua CLI | "Mở lại lượt cũ" chỉ đúng cho bản chép trong `summary/` | Có cần thư mục lượt chạy theo timestamp cho mọi lượt? (thay đổi engine) |
| R3 | Bản redesign `web/app.py` **chưa commit** (+1400 dòng, dark theme, Google Fonts từ mạng ngoài) | Dễ xung đột; UI phụ thuộc mạng | Giữ, thay, hay bỏ? |
| R4 | Form ad-hoc hiện tại không có LLM/fixture → kết quả khác hẳn CLI cho cùng tài liệu | Người dùng tưởng tool kém | Bỏ, hay chuyển thành "tạo project" (ghi YAML)? |
| R5 | Kill subprocess để lại `run.json` `running` và có thể để lại dữ liệu/phiên dở | Báo cáo sai trạng thái | Thiết kế dấu huỷ (§7.1) |
| R6 | Quyết định review lưu ở đâu: XLSX (bị ghi đè khi chạy lại) hay sidecar theo `content_hash` | Mất review | Người dùng |
| R7 | Chế độ ghi trên web | Rủi ro dữ liệu thật | Đề xuất: không hỗ trợ trên web |
| R8 | Lượt chạy dài (generation ~4,5 phút cho 13 case) và tốn token | UX chờ; chi phí khi bấm nhầm | Hiện budget + xác nhận trước khi chạy cả project |
| R9 | Không có tiến trình execute từng case | Tab Tiến trình "đứng" ở bước execute | Thêm callback (§7.6) |
| R10 | `--host 0.0.0.0` không có xác thực | Ai trong mạng cũng chạy/tải được | Cảnh báo hoặc cấm bind ngoài loopback |

### Khác biệt giữa tài liệu và code (code là chuẩn)
- AGENTS.md: "CLI, web UI và CI dùng chung một hàm — không có logic nào chỉ tồn tại trong giao diện." → đúng ở mức `run_pipeline`, **sai** ở mức cấu hình: web dùng `_to_config` riêng, bỏ qua `preflight`/`build_summary`/`redact`/`summary`.
- AGENTS.md mô tả "Tầng artifacts: UI đọc trực tiếp `events.jsonl`" (`artifacts.py` docstring) → chưa UI nào đọc; `todo.md:168` thừa nhận.
- `HUONG-DAN.md` chỉ có một dòng `qctool ui`; không mô tả giới hạn (không LLM, không project).
- `milestones.md:13` còn nhắc `qctool serve`/`qctool all` — lệnh hiện là `ui`/`run`.
- Docstring `PipelineConfig.out_dir` ghi "mặc định: artifacts/<feature>/" — đúng cho lượt không gắn project; web thực tế ghi `projects/web/<feature>/artifacts`.
