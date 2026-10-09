---
type: finding
status: verified-partial
created: 2026-10-09
updated: 2026-10-09
lang: vi
changelog:
  - 2026-10-09 | claude | customer_e2e_test_1: 9/11 Pass, 0 Fail
  - 2026-10-09 | claude | Chạy đủ 7 intent customer 4 lượt; sửa gate/feedback/retry; 5/7 Pass
  - 2026-10-09 | codex | Agent Orders Pass 11/11; ghi rõ chi phí debug và phạm vi kiểm chứng
---

# Agent redesign — kiểm chứng giới hạn

## Quyết định và đường đi

Nhánh `agent-redesign`, thay trực tiếp patch stack. Docs/OpenAPI giữ nguyên nguồn.
Prose đi vào `generation.run_generation` → source intents → một call design →
`agent.loop.author_intent` với tools → gate schema/safety/citation → fresh dry-run →
runner thật. Không có nhánh legacy engine; business/legacy trong config cũ chỉ là
alias tương thích, không phục hồi resolver cũ.

Các verb/schema lấy từ ACTION_SPECS. Lỗi draft/dry-run được trả lại cùng session;
turn/token/time budget chặn vòng vô hạn. `draft_case` hợp lệ tự dry-run để tránh
thêm một call chỉ yêu cầu model gọi dry_run. Tool dry_run vẫn có thể gọi riêng.

Agent đọc ARIA và stable IDs; locator kiểm live, không chứng minh bằng crawl cap.
Trích dẫn chứng minh nguồn expected, không phải một theorem prover về ngữ nghĩa.
Expected literal thiếu/weak oracle đi `needs_review`; không được gọi generation
success. Source Given/When/Then nguyên văn còn trong `source_intent` và step source.
Các obligations không có expected đủ assessable vẫn giữ trạng thái unassessable;
không bịa testcase/coverage để lấp chỗ trống.

## Thay và giữ

Retire: patch proposal/resolver/semantic grammar, source grounding, gap routing,
resolution cycle/loop, coverage planner/loop/resolution, exploration plan/execution,
mapper/from_requirements/from_flows/from_functions. Test riêng cho các API đó được
retire; test schema/runtime/redaction/test-data và mixed modules còn phù hợp được giữ.
Kiểm chứng pipeline/CLI được chuyển sang tool replay, không gọi completion giả là live.

Giữ: ingest/models, deterministic OpenAPI, native runner/browser, response capture,
14 cột Test Cases, report JSON/CSV/JUnit/Markdown, fixtures và reviewed data policies.
Thêm sheet Review và đọc accepted/rejected làm labels, không đổi runtime status.
Critic optional/default-off chỉ được downgrade review, không sửa expected.

**Ngoại lệ an toàn có chủ ý:** preparation cache backend vẫn run-scoped và freshness
vẫn có hiệu lực. DOM hash/public knowledge không chứng minh account còn tồn tại,
role/state hay password hợp lệ. Không thay proof backend bằng persistent DOM cache.

`app-model.yaml` chứa public route/ARIA/stable locator/macro aliases; live revalidate
mỗi reuse. Không lưu credential, auth state hay assurance receipt trong knowledge.
Mutation cần reviewed policy; dry-run không tạo entity rồi runner tạo lần nữa.
Workflow ghi không có cách dry-run an toàn vẫn unresolved/review, chưa tuyên bố hỗ trợ.

## Root cause runtime được phát hiện

Context mới nạp storage_state có localStorage ngay cả khi page còn about:blank.
Anonymous trước đây chỉ clear storage của page đang mở, nên localStorage đã nạp có
thể sống sót. Goto /login redirect sang home, rồi fill timeout. Sửa generic:

- Agent bắt đầu với context không nạp state; chỉ ui.session authenticated mới restore.
- BrowserSession anonymous xoá storage ở known origins bằng CDP, không cần mở route.
- Stable test ID ưu tiên role/name; duplicate ID không fallback. Locator chưa render
  được chờ attached trước khi kiểm uniqueness, không `.first()`.

## Live: chỉ hai intent, lượt cuối chỉ Orders

Không chạy full 7 cases, không tạo đơn hàng, không dùng replay cho live generation.
Nguồn `samples/customer/` và fixture không chỉnh. DeepSeek configured model
`deepseek-flash`, OpenAI-compatible tool calling; thinking disabled cho lượt cuối.
Named tool_choice bị provider từ chối trong thinking mode; dùng auto, parser vẫn strict.

Lượt cuối qua public CLI:

```bash
QCTOOL_LLM_TIMEOUT_SECONDS=90 QCTOOL_LLM_THINKING=disabled \
  uv run qctool run --config .qctool.agent-acceptance.yaml --llm
```

Config runtime chọn `AC-customer-001-4:then`, max_intents=1, budget 12 turns/
60.000 tokens/480 seconds, completion 2.200; auth browser, provisioning OFF.
Config local này không commit vì chứa tham chiếu deployment/policy riêng. Mẫu generic:
`qctool.agent.example.yaml`. Để tái lập trên customer config, giữ nguyên inputs và
thêm generation.profile=agent, intent_ids=[AC-customer-001-4:then], max_intents=1,
budget như trên, headless=true, out.dir=artifacts/agent-redesign-acceptance.

Agent thực hiện read_docs/list_api (cùng round), observe login, reuse authenticate
macro, observe /my-orders, draft_case → automatic dry-run. Không sửa tay testcase.

Generated `TC_CUSTOMER_001` (ID được cấp lại trong subset, là obligation Orders):

1. ui.session anonymous
2. ui.goto /login
3. ui.fill login-email-input = active_user.email
4. ui.fill login-password-input = active_user.password
5. ui.click login-submit-btn
6. ui.goto /my-orders
7. assert.url_matches /my-orders
8. assert.visible heading Đơn hàng của tôi
9. assert.text heading = Đơn hàng của tôi, exact
10. assert.visible order-tab-all
11. assert.text order-tab-all = Tất cả, exact

Generation tier ready, dry-run passed. **Real Chromium: Pass 11/11**. Final URL
`https://salonhub-soe.vercel.app/my-orders`. Mọi expected outcome của source Orders
được assert, không đổi kỳ vọng theo DOM. Không suy ra Profile hay toàn suite đã Pass.
Profile đã được thử trong các lượt debug nhưng không ready; lượt cuối không chạy lại.

Toàn nguồn vẫn có 7 obligations: executable coverage **1/7**, generation_success=false,
pipeline_ok=true, CLI exit **3** (generation incomplete). Đây là phân biệt có chủ ý
cho subset; không báo success toàn bộ tài liệu từ một case Pass.

Artifact chính:

- artifacts/agent-redesign-acceptance/generation.json
- artifacts/agent-redesign-acceptance/app-model.yaml
- artifacts/agent-redesign-acceptance/testcases.yaml và testcases.xlsx
- artifacts/agent-redesign-acceptance/runs/20261009-002116/results.json
- cùng run: results.csv, junit.xml, report.md
- artifacts/agent-redesign-acceptance/agent-benchmark.json

## Chi phí — không chỉ báo lượt cuối

Lượt thành công: **5 calls** = 1 design + 4 authoring; prompt **18.628**, completion
**1.127**, total **19.755** tokens. Prompt cache hit **13.696** / miss **4.932**,
hit ratio **73,52%**. Cache đã warm trong debug; không coi đây là cold-cache benchmark.

Các audit debug được giữ trong attempt-*-generation.json: **83 attempts**, usage
đã ghi **363.800 tokens**, 2 attempts thiếu usage. Cộng lượt thành công: **88 attempts,
383.555 tokens đã ghi**. Lượt HTTP400 đầu tiên không giữ đủ audit, không thể kết luận
chi phí bằng zero. Đây là chi phí phát triển lớn, **không** phải một lần chạy kinh tế.

Baseline lịch sử 3–4/7 runnable, khoảng 330.933 tokens từ finding customer; không chạy
lại baseline legacy đầy đủ, để giữ phạm vi 1–2 E2E và tránh mutation. Không so sánh
19.755-token/1-intent như thể thắng 330k-token/7-intent cùng điều kiện.

## Giới hạn xác nhận

- Chưa chứng minh ≥6/7 customer, full order_product checkout hay smoke suite mới.
- Citation và dry-run không tự chứng minh đầy đủ faithfulness; QC/critic vẫn cần.
- False-fail, fitted-oracle rate, review acceptance rate **unknown** nếu thiếu labels;
  evaluator không giả định 0 unsafe từ việc runtime Pass.
- Replay benchmark cũ thuộc patch schema đã retire, không tuyên bố đã chạy lại hay
  tương đương với benchmark agent mới.
- CLI/web/CI vẫn qua cùng pipeline; model opt-in, provisioning OFF mặc định.

## Chạy đủ 7 intent customer — 2026-10-09 (claude)

Cùng config acceptance, bỏ `intent_ids`/`max_intents` (đủ 7 obligation). Budget 12 turns /
60.000 tokens / 480 s mỗi intent, DeepSeek thinking tắt, timeout 90 s, provisioning OFF.
Config chạy nằm ngoài repo (scratchpad), không commit.

### Lỗi lộ ra và cách sửa (generic, không theo tên trang/câu của pilot)

| # | Triệu chứng thật | Nguyên nhân | Sửa |
|---|---|---|---|
| 1 | TC001 hết budget, lặp `capture_response không hợp lệ` | `Step.validate` nuốt lý do; protocol chỉ liệt kê tên tham số | Lỗi nêu dạng đúng `{method, path, origin[, save_as, timeout_ms]}`; protocol mô tả capture + cách assert `request_count` |
| 2 | TC002 không viết được "ô vẫn trống" | `expected: ""` bị coi là thiếu (cả `testcase.py` lẫn `executability.py`) | `""` là oracle hợp lệ cho `expected`; tham số khác rỗng vẫn là thiếu |
| 3 | Lỗi browser chỉ trả `ResponseCaptureError` | Tool chỉ lộ tên class | Trả `exc.code` đã kiểm soát (không lộ body/transport) |
| 4 | TC006 không thể mở `/admin` | `high_risk(path)` chặn mọi navigation | Mở read-only khi Given/When nêu đúng route; expected URL không cấp quyền; write vẫn chặn |
| 5 | TC006 **Pass giả**: assert `/` trước `goto /admin`, rồi lượt sau bỏ hẳn `goto` | Gate chỉ kiểm trích dẫn, không kiểm thứ tự/bước | Mỗi mệnh đề expected phải assert **sau** action cuối; route trong Given/When phải được thực hiện |
| 6 | TC001 **Fail giả**: `pattern: "URL chuyển tới /"` | Văn xuôi lọt qua vì là substring của quote; dry-run không chạy assert | `url_matches` phải là regex path/URL hợp lệ, không khoảng trắng; URL tuyệt đối cùng origin so theo path |
| 7 | Mất cả intent vì 1 timeout | `chat()` không retry (khác `complete()`) | Retry đúng 1 lần cho TIMEOUT/429/5xx, như `complete()` |
| 8 | Design hỏng → cả suite thành manual | `llm=None` với mọi lỗi design | Chỉ dừng khi lỗi provider; design sai dạng thì dùng intent gốc |

Lỗi 5 và 6 là đúng loại "nói dối" AGENTS.md cấm: case chạy được nhưng không kiểm
outcome, hoặc đổ `Fail` cho sản phẩm vì lỗi tool. Cả hai đều do dry-run (cố ý) không
đánh giá giá trị assert — nên gate phải kiểm cấu trúc: thứ tự, bước nguồn, dạng oracle.

### Kết quả 4 lượt đủ 7 intent

| Lượt | Gate | Executable | Pass | Fail | Calls | Tokens (cache hit) |
|---|---|---|---|---|---|---|
| full | cũ | 5/7 | 5 | 0 | — | — |
| final | + sửa 1–4 | 6/7 | 6 | 0 | 34 | 184.273 (149.760) |
| final2 | + sửa 5 | 5/7 | 4 | **1 giả** | 36 | 220.005 (180.736) |
| final4 | + sửa 6–7 | **5/7** | **5** | **0** | 37 | 221.603 (182.016) |

Lượt `final3` (4/7, 2 timeout không retry) bị thay bởi `final4` sau sửa 7.
Lượt `final` 6/7 chạy **trước** khi có rule 5–6; không dùng làm số nghiệm thu.

Số nghiệm thu: **`final4` — 5/7 executable, 5 Pass, 0 Fail, 0 Blocked, 2 Not Executed.**
Baseline cũ 3–4/7, ~330.933 tokens. Mỗi intent đã `ready` ở ít nhất một lượt.

Còn lại:

- **Profile (AC-001-3):** lặp `Locator must resolve to exactly one current element` rồi hết
  token budget. Text "Thông tin cá nhân"/"Khách hàng" xuất hiện >1 chỗ; agent cần dùng
  `role` + name thay vì text trần. Không nới uniqueness check.
- **Timeout DeepSeek:** vẫn 2 timeout/37 call ở `final4` (AC-001-7 timeout cả lần retry).
  Đây là biến động provider, không phải lỗi sản phẩm hay tài liệu.
- Kết quả từng intent còn dao động giữa các lượt (5/7 ↔ 6/7). Cần chạy nhiều lượt để
  báo tỉ lệ, không báo một lượt đẹp nhất.
- `needs_review` (TC002, TC007…) chưa có nhãn QC; tỉ lệ chấp nhận review vẫn **unknown**.

Kiểm thử: offline 423 pass; Chromium (`-m playwright`) 63 pass.
Artifacts: `artifacts/agent-customer-final4/` (generation.json, testcases.yaml/xlsx,
`runs/*/results.json`, report.md).

## customer_e2e_test_1 — 11 AC (đăng nhập, mua hàng, đặt lịch, read-only)

Tài liệu mới `samples/customer_e2e_test_1/` lấy từ source SalonHub; config
`qctool.customer_e2e_test_1.e2e.yaml`. Một lượt (`runs/20261009-104001`):
**9/11 executable, 9 Pass, 0 Fail, 0 Blocked, 2 Not Executed**. Hai case chưa ready do
TOKEN_BUDGET: AC-002-2 (anonymous Thêm vào giỏ — ID sản phẩm phụ thuộc dữ liệu) và
AC-002-4 (/my-orders). Case đăng nhập không có trace (cố ý, tránh lộ mật khẩu).
