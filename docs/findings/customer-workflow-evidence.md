---
type: finding
status: verified
created: 2026-10-08
updated: 2026-10-08
lang: vi
changelog:
  - 2026-10-08 | codex | Thu evidence theo source workflow; pilot executable tăng lên 4/7
---
> Ghi chú 2026-10-09: finding này đo engine V1 (semantic resolution/exploration), đã retire ở
> QC-TOOL V2. Số liệu đúng tại thời điểm ghi; kết quả hiện tại: `docs/findings/agent-redesign.md`.


# Evidence acquisition cho workflow nhiều trạng thái

## Phạm vi và nguyên nhân

Giữ nguyên `samples/customer/`, `qctool.customer.e2e.yaml`, fixture, test-data
preparation và kỳ vọng nghiệp vụ. Không thêm logic theo tên sản phẩm/testcase.

Trước sửa, executable coverage là 3/7; 2 Pass, 1 Blocked, 4 Not Executed.
Bốn obligation còn lại thiếu chuỗi chứng minh từ đăng nhập đến trạng thái đích.
Replay exploration chỉ chấp nhận fill/select/click; `ui.goto` trong WHEN làm
chuỗi không thể được duyệt trọn vẹn. Các request riêng biệt không chia sẻ phiên.
Context của các case đích có `/login` nhưng không có API contract của prerequisite
đăng nhập. Heading và text không tương tác chưa có locator evidence phù hợp.
Routing/prompt cũng chưa dùng đầy đủ các outcome atom đã được normalize.

## Các quy tắc generic đã thêm

- `outcome_needs()` tạo evidence need cho từng atom còn thiếu, không chỉ URL.
  Multiple-state WHEN cần full approved state chain. Thiếu hoặc mơ hồ element
  giữ UI_STATE need; thiếu chain giữ WORKFLOW_STATE need.
- Requirement khác chỉ là prerequisite khi Given giống hệt và WHEN là strict
  ordered clause prefix. Then của prerequisite có thể ground operation/transition
  trung gian; không được trở thành Then của testcase hiện tại.
- Planner nhận candidate đầy đủ gồm current step_seq, exact control, alias và
  source route trong một request. Candidate vẫn untrusted, validator phải duyệt.
- Exploration `ui.goto` chỉ cho next WHEN navigate clause có route chính xác.
  Entry target đã thực hiện GIVEN navigation, không được replay thêm GIVEN.
  Max 5 actions, same-origin, expected-state checks và fresh DOM grounding giữ nguyên.
- Trang access-denial chỉ được navigate read-only với redirect được source cho phép;
  không cấp quyền thao tác admin hay endpoint mutation.
- Explorer thu bounded heading/leaf text sau các interactive controls, dùng lại
  Element/PageMap; không đọc form values. Alias secret chỉ resolve ở runtime.
- Assertion heading/text không có test_id chỉ dùng by_name khi duy nhất, đúng state,
  không có element truncation. Stable test_id vẫn ưu tiên; ambiguity không bị xoá.
- Validator cần source → full actual WHEN → validated actions → final valid state.
  Login/intermediate/stale state không chứng minh outcome ở trang đích.
- `SOURCE_OUTCOME_INCOMPLETE` chặn mapped assertion subset khi full validated source
  IR vẫn yêu cầu thêm assertion atoms. Không tự sửa mapped steps.
- Fingerprint capability + testcase/evidence state ngăn gọi lại model với state
  không đổi; audit ghi SKIPPED_UNCHANGED_STATE / NO_NEW_EVIDENCE. Không response cache.
- Prompt dùng validated semantic meanings, không dùng narrow grammar để suy ra
  toàn bộ DOM là relevant. Source/session/fixture facts vẫn giữ nguyên; nested
  action snapshots chỉ loại elements không liên quan, giữ conflicts/provenance.

Không thêm phrase-specific regex hay rule cho `/profile`, `/my-orders`,
`/my-appointments`, tên control/message/fixture của pilot. Không thay data trust.

## Lệnh thật và kết quả

Preflight:

```bash
uv run qctool validate --config qctool.customer.e2e.yaml
```

OK: 8 requirement sources, 4 API operations, 2 warnings. Không model/browser/API.

Lượt đầu giữ timeout mặc định 30s:

```bash
uv run qctool run --config qctool.customer.e2e.yaml --llm \
  --out artifacts/customer-workflow-evidence-live
```

2/7 executable; 1 Pass, 1 Fail, 5 Not Executed. 15 adapter calls, 23 HTTP
attempts, trong đó 13 timeout. Completion trả về: 82,653 prompt + 32,776
completion = 115,429 tokens. Planner còn đề xuất replay GIVEN navigation;
parser gặp extra semantic args và timeout làm kết quả kém baseline. Đã làm rõ
contract bằng field sets từ semantic model, không auto-correct output.

Lượt tiếp theo giữ nguyên docs/config/app/expectations, chỉ tăng client deadline
bằng env cho lần chạy, không sửa provider:

```bash
QCTOOL_LLM_TIMEOUT_SECONDS=90 uv run qctool run \
  --config qctool.customer.e2e.yaml --llm \
  --out artifacts/customer-workflow-evidence-90s
```

**4/7 executable; 2 Pass, 1 Fail, 1 Blocked, 3 Not Executed.**
Executable coverage 57.14%, generation_success=false / INCOMPLETE_COVERAGE.
Pipeline hoàn tất (`pipeline_ok=true`); CLI exit 1 / EXECUTION_FAILED.
Không có unresolved test-data blocker; không provisioning/verification.
Declared fixture facts không được nâng thành live verification.

| Obligation | Missing proof trước sửa | Exploration / state / evidence thật | Sau / blocker |
|---|---|---|---|
| AC-customer-001-3: profile | Full login→destination; heading, customer text và URL | 4-action plan duyệt; fill email, fill password, click submit thực hiện; vẫn `/login`, transition invalid; goto `/profile` chưa chạy | Chưa executable; destination evidence thiếu. Pass sau còn precondition semantic binding và cycle cap |
| AC-customer-001-4: orders | Full login→destination; heading, nút All và URL | 4-action plan duyệt; hai fill và submit thực hiện; vẫn `/login`; goto `/my-orders` chưa chạy | Chưa executable; full destination state/outcomes chưa chứng minh |
| AC-customer-001-5: appointments | Full login→destination; heading, nút All và URL | 4-action plan duyệt; hai fill và submit thực hiện; POST backend login HTTP 401, count1; vẫn `/login`; goto `/my-appointments` chưa chạy | Chưa executable; full destination state/outcomes chưa chứng minh |
| AC-customer-001-6: customer/admin | Safe source-authorized access-denial navigation và expected URL | Không cần exploration; canonical source actions/URL đủ để tạo case. Runner mở `/admin`, thực tế redirect `/login` | Executable mới; runtime Blocked vì phiên chưa xác thực; chưa chứng minh access-denial behavior của customer |

Không có evidence chứng minh đã đến profile/orders/appointments. Profile/orders
không collect network metadata trong plan thật này: không gán HTTP 401 cho chúng
chỉ từ response của case khác. Action/count/state được giữ riêng theo request.

Các source outcome còn giữ đầy đủ trong assert.unmapped; không chấp nhận URL subset.
Case IDs được cấp lại qua coverage pass, nên đối chiếu bằng traces_to:

| Final case | Obligation | Executable | Runtime |
|---|---|---|---|
| TC_CUSTOMER_001 | happy login | Có | Fail: capture HTTP 401, expected 200 tại step6 |
| TC_CUSTOMER_002 | empty form | Có | Pass: hai ô rỗng, exact validation, POST count0/2000ms, `/login$` |
| TC_CUSTOMER_006 | customer/admin | Có | Blocked: `/admin` chuyển tới `/login`, chưa có authenticated session |
| TC_CUSTOMER_007 | anonymous/profile | Có | Pass: redirect `/login$` |
| TC_CUSTOMER_008 | profile | Không | Not Executed |
| TC_CUSTOMER_009 | orders | Không | Not Executed |
| TC_CUSTOMER_010 | appointments | Không | Not Executed |

HTTP 401 là response quan sát thật. Chưa đủ bằng chứng phân biệt lỗi tài khoản,
backend state hay sản phẩm; task này không sửa fixture, không probe backend riêng.
Admin Blocked không phải Pass/Fail và không chứng minh customer role access.

## Giới hạn còn lại và thay đổi sau lượt live

Audit live có PROMPT_BUDGET_EXCEEDED sau interaction snapshots: estimated tokens
14,229 (profile), 14,442 (orders), 15,084 (appointments), budget 12,000.
Projection cuối task giảm chúng offline xuống 12,916 / 13,127 / 13,735, vẫn block
an toàn thay vì bỏ source/required evidence. Đây là tool blocker riêng, không
đổ cho test data hay website. Không tuyên bố đã sửa hết budget.

Projection và tự bật sanitized network metadata khi prerequisite binding đã được
validator duyệt là refinement sau lượt live 90s. Đã kiểm chứng offline/local browser;
không tính là được live xác nhận. Không chạy thêm chuỗi login tương đương chỉ để
làm đẹp số liệu khi state đích vẫn chưa đạt được.

## DeepSeek thật

Lượt 90s: 19 adapter calls = 15 resolution + 4 exploration; 19 HTTP attempts,
tất cả có completion, không timeout. Usage do provider trả:

- Prompt: 175,394.
- Completion: 155,539.
- Total: 330,933.
- Cache hit: 77,056; miss: 98,338; prompt hit ratio ~43.93%.

Baseline trước task: 37 adapter calls / 44 attempts. Không gọi replay completion
là DeepSeek thật; local acceptance regression dùng replay LLM và Chromium thật.

## Artifact và kiểm chứng

Main run: `artifacts/customer-workflow-evidence-90s/` chứa generation.json,
summary.json, requirements.yaml, ui-map.yaml, testcase YAML/XLSX, pipeline.log.
Runner: `runs/20261008-112450/` chứa results.json/csv, report.md, junit.xml và evidence.
Quét 14 file text/archive/log không thấy env credential/API-key
values được cấu hình. Không lưu raw prompt hay provider body vào tài liệu này.

Generic local-browser regression: source-authorized login POST→home→unseen
destination, 5 states; heading/text/URL đủ để validate/apply executable case.
Xoá heading hoặc đổi current state về entry: không resolve Then. Duplicate heading
giữ ambiguity; đúng state có unique witness được chấp nhận. Inputs immutable.

Safety benchmark: resolution 24 cases, executable 0→13, gaps45→18, unsafe/false
repairs0, regressions0. Generation 25 scenarios, semantic25/25 correct, unsafe/
false repairs0, 15 expected abstentions. Corpus expectations không sửa.

- Full offline: **1216 passed, 70 deselected** (`-m 'not playwright'`).
- Explorer/V3/workflow/autonomous browser subset: **19 passed, 40 deselected**;
  gồm autonomous acceptance cũ **4/4 Pass** (replay LLM, Chromium thật).
- Workflow regressions sau kiểm tra ambiguity cuối: **22 passed**; gồm browser
  auth→destination, unique/missing/duplicate heading và state safety.
- `git diff --check`: sạch.
