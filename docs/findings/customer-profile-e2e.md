---
type: finding
status: verified
created: 2026-10-08
updated: 2026-10-08
lang: vi
changelog:
  - 2026-10-08 | codex | Sửa evidence/synchronization; Profile chạy Chromium Pass
---

# Customer Profile: source → evidence → executable → Chromium

## Phạm vi và nguồn

Chỉ obligation `AC-customer-001-3`, candidate `TC_CUSTOMER_003` từ pass đầu
của pipeline bình thường. Các pass sau đổi ID candidate nhưng không đổi
obligation. Không sửa documents, fixture, `.env`, app hoặc proposal validator;
không chạy lại toàn bộ 7-case pilot trong task này.

Source gốc ở `samples/customer/urd.md`, dòng AC-001-3:

- Given: phiên anonymous ở `/login`; customer active và mật khẩu đúng từ
  trusted fixture `active_user`.
- When: nhập email; nhập password; bấm Đăng nhập ở form login; mở `/profile`.
- Then: hiển thị **Thông tin cá nhân**; hiển thị **Khách hàng**; URL `/profile`.

`samples/customer/flows.md` và `srs.md` giữ nguyên ba outcomes. OpenAPI hiện có
khai POST `/api/auth/login` và GET `/api/auth/profile` đúng backend server.
Source app `frontend/src/contexts/AuthContext.jsx` gọi GET profile khi reload
có token; nếu request lỗi thì xóa session. `pages/auth/Profile.jsx` render
heading và customer badge. Không dùng observation để sửa kỳ vọng này.

## Trace và root cause

1. Coverage planner giữ Given/When/Then thành ba logical steps. Proposal thật
   từ DeepSeek chuẩn hóa đủ clauses vào semantic IR; resolver/applier hiện có
   đã tạo session, navigation, hai fills, submit click và navigation Profile.
   Assertion compound vẫn giữ cả ba outcomes khi thiếu destination evidence.
2. Context chọn login POST làm operation evidence của prerequisite. Tuy nhiên
   không có đường truyền permission cho read operations đã khai trong contract.
   Explorer coi mọi foreign-origin read là lỗi phải dừng workflow: socket,
   notifications, cart, ảnh/font và cả GET profile đều bị abort.
3. Khi reload `/profile`, GET profile bị abort làm AuthContext xóa session rồi
   redirect `/login`. Đây là tác động của tool, không phải fixture sai/401.
4. Cờ truncation toàn sequence được gắn vào mọi state. Trang trước thiếu
   evidence khiến trang sau cũng bị coi thiếu. Đồng thời tổng limit 60 cho cả
   controls lẫn text witnesses thực sự clip detail page có khoảng 89 visible
   nodes; validator đúng khi không chứng minh name locator là duy nhất.
5. Sau khi evidence đủ, IR → existing validator → applier tạo testcase auto
   với đủ outcomes. Runner đầu trả Fail: plain click xong sau khoảng 61 ms,
   `networkidle` của document cũ đã satisfied, nên `goto /profile` chạy trước
   login POST hoàn tất. Login bị ngắt trước khi session được lưu. Đây là lỗi
   đồng bộ của tool; Fail này không chứng minh sản phẩm vi phạm expectation.

## Các sửa generic, không thêm framework

- Context có allowlist `interface_contract.background_reads` lấy đúng GET/HEAD
  operations và declared servers từ OpenAPI; có limit và omission count.
  Đây là permission transport, không phải assertion/source authority. Evidence
  catalog của LLM/validator vẫn chỉ cho cite các `api_operations` được chọn.
- Plan validator đưa selectors method/path/origin vào grounding đã duyệt;
  existing action fingerprint bao gồm permissions này. Runtime chỉ cho qua
  đúng selector và CORS preflight tương ứng, không mở toàn backend origin.
- Các read nền khác vẫn bị abort và báo `BACKGROUND_REQUEST_BLOCKED`, nhưng
  không hủy cả workflow đã duyệt. Write, navigation lạ và dangerous API reads
  vẫn bị chặn và dừng sequence. Không đọc body/header/cookie của reads.
- Truncation gắn đúng snapshot/state và giữ aggregate flags cho audit. Snapshot
  element bound là 120, vẫn hữu hạn; vượt bound vẫn không được coi name-only
  locator proof là đầy đủ. Không bỏ ambiguity/truncation check của validator.
- Sau approved navigation, explorer dùng đúng render wait budget đã cấu hình.
- Plain BrowserSession click chờ các fetch/XHR writes phát ra trong click
  window hoàn tất, hoặc navigation thực tế kết thúc interaction. Chờ bounded
  theo browser timeout; timeout là `UI_ACTION_RESPONSE_TIMEOUT` → Blocked.
  Không lưu URL/body/headers/credential từ bộ đồng bộ này; không thêm assertions.

## Lượt targeted và bằng chứng

Đầu vào lấy từ audit normal pipeline:
`artifacts/customer-e2e-corrected-email-vpn-20261008/generation.json`,
pass 1, obligation Profile. Dùng semantic IR và plan đã được DeepSeek trả thật
trong lượt đó, không tạo replay/fake completion mới và không sửa testcase tay.
Task targeted không gọi thêm LLM trên cùng nghĩa/evidence đã chuẩn hóa.

Plan được validator duyệt lại với trusted contract hiện tại, rồi Chromium mới
thực hiện actions thật. Sau đó context mới đi qua `run_resolution_loop()` một
cycle; deterministic semantic grounding → validator **VALID** → safe applier.
Original case/context được kiểm tra không mutate. Không tạo/chạy case khác.

State chain thu thật:

```text
/login → fill email → /login → fill password → /login
       → click submit → / → goto /profile → /profile
```

Exploration ghi metadata POST login 200, GET profile 200 và hai read operations
khác đã khai contract. Full cuối snapshot chứa heading và badge đúng source;
evidence refs của assertions gắn với đúng final validated state.
Unapproved background reads vẫn bị abort; không xem chúng là responses 200.

## Testcase executable thực tế

| Seq | Action | Arguments / expected |
|---|---|---|
| 1 | ui.session | mode=anonymous |
| 2 | ui.goto | `/login` |
| 3 | ui.fill | login-email-input = active_user.email |
| 4 | ui.fill | login-password-input = active_user.password |
| 5 | ui.click | login-submit-btn |
| 6 | ui.goto | `/profile` |
| 7 | assert.visible | Thông tin cá nhân |
| 8 | assert.text | Thông tin cá nhân, exact=true |
| 9 | assert.visible | Khách hàng |
| 10 | assert.text | Khách hàng, exact=true |
| 11 | assert.url_matches | `/profile$` |

Hai text elements không có test_id; dùng observed role/name, unique locator
proof trong complete destination snapshot và `by_name` cho runtime. Không bịa
test_id. `target` trong YAML là existing generated element ID của UI evidence.
Original compound assertion được thay thành đủ năm atoms, giữ source-clause
provenance. Exact text assertions dùng Playwright `to_have_text` auto-wait.

Sau runtime correction, Chromium runner chạy **11/11 steps OK, 1 Pass, 0 Fail,
0 Blocked, 0 Not Executed**, final URL `https://salonhub-soe.vercel.app/profile`.
Chạy với retry=0 và context mới; không reuse phiên exploration. Fail trước
runtime correction được giữ riêng, không xóa lịch sử hoặc gán lỗi cho website.
Các nguyên nhân/network capture từ exploration không được giả làm response
capture của lượt runner; Profile source không yêu cầu thêm HTTP assertion.

## Artifacts và giới hạn

Trong `artifacts/customer-profile-focused-20261008/`:

- `source-trace.json`: logical testcase, source audit, live proposal/plan gốc,
  telemetry hai calls cũ và thông tin targeted task có 0 calls mới.
- `initial-probe.json`: approved exploration, page states, sanitized network,
  background-block issues và enriched context của lượt exploration cuối.
- `resolution.json`: cycle, proof/validation/application, final executable IR.
- `testcases.yaml`: testcase do engine serialize, không author/sửa tay.
- `results.json`, `results.csv`, `junit.xml`, `report.md`: lượt runner cuối.
- `first-run-results.json`, `first-run-report.md`: Fail trước runtime fix.

Scan các text artifacts xác nhận không chứa email/password runtime hoặc API key.
Trace/HAR chứa secrets không được bật. Credentials chỉ resolve lúc runtime.
Không claim toàn bộ suite 7/7 hoặc coverage complete của pilot: chỉ Profile đã
được xử lý và thực thi ở đây. Không có blocker còn lại cho obligation Profile.
Trang khác vượt structural evidence limits vẫn có thể unresolved; không tự
loại bỏ assertion hoặc đổi expectation để vượt giới hạn.

## Regression tests

- `uv run python -m pytest tests/ -q -m 'not playwright'`:
  **1226 passed, 79 deselected**. Gồm offline semantic/validator/evaluation
  benchmarks, không gọi provider/browser live.
- `uv run python -m pytest tests/test_workflow_evidence.py tests/test_exploration_v2.py tests/test_exploration_v3.py tests/test_explore.py -q -m playwright`:
  **33 passed, 49 deselected**.
- `uv run python -m pytest tests/test_browser.py tests/test_autonomous_acceptance.py -q -m playwright`:
  **25 passed, 9 deselected**. Autonomous local regression vẫn 4/4 Pass; model
  completions trong test này là offline stub, không phải DeepSeek live.

Regressions mới kiểm tra denied background read không hủy approved workflow,
foreign write/dangerous read vẫn bị chặn, exact contract read mới được phép,
permission mutation bị fingerprint chặn, transport read không trở thành
assertion authority, per-state completeness, slow click request completion và
bounded timeout → Blocked. Immutability và secret redaction vẫn được kiểm tra.
