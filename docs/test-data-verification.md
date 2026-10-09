---
type: guide
status: implemented
created: 2026-10-07
updated: 2026-10-09
lang: vi
changelog:
  - 2026-10-09 | claude | V2: preparation chạy trong run_generation; resolution loop retire
  - 2026-10-07 | codex | Liên kết provisioning opt-in, giữ verification độc lập
  - 2026-10-07 | codex | Nối preparation hữu hạn vào generation và resolution
  - 2026-10-07 | codex | Thêm verification có policy và receipt, không provisioning
---

# Kiểm chứng dữ liệu test hiện có

Acquisition chỉ đọc dữ liệu. Credential và facts trong config là khai báo,
không phải bằng chứng backend. Generation và resolution dùng preparation tự động,
nhưng chỉ được gọi verification khi thiếu facts bắt buộc và có rule đã được
người vận hành review/cho phép. Có credentials không tự kích hoạt lời gọi.

## Rule trong config

Đặt dưới `test_fixtures.acquisition.verification`. Ví dụ cấu trúc dưới đây
**chưa cho phép gọi** (`approved: false`); người vận hành phải review contract
và tác động thật của operation trước khi bật. Không suy đoán an toàn từ tên login.

```yaml
test_fixtures:
  fixtures:
    active_user:
      email: {env: SMOKE_ACTIVE_EMAIL}
      password: {env: SMOKE_ACTIVE_PASSWORD}
  bindings:
    AC-LOGIN:
      email: active_user.email
      correct_password: active_user.password
  acquisition:
    verification:
      - fixture: active_user
        operation_id: login
        body_aliases:
          email: active_user.email
          password: active_user.password
        expected:
          status: 200
          json: {$.success: true}
        proves:
          account_exists: true
          password_valid: true
        policy:
          approved: false
          test_data_mutation: false
          side_effects: [session_creation]
        source_ref: reviewed-contract:login
```

`proves` là implication được policy tin cậy xác nhận, không suy từ model.
Ví dụ này không chứng minh `role` hoặc `account_state`; nếu case cần chúng,
case vẫn thiếu bằng chứng. Muốn chứng minh thêm phải có rule/contract được
review riêng. Role/state trong config vẫn là `DECLARED`.

## API và trust boundary

```python
prepared = prepare_test_data(
    case, fixture_store=store, endpoints=endpoints, base_url=backend_url,
)
if not prepared.available:
    # Inspect prepared.status / prepared.blockers; no provisioning or LLM guess.
    return prepared

# Các API dưới đây vẫn dùng được riêng cho chẩn đoán/replay:
before = acquire_test_data(case, fixture_store=store, endpoints=endpoints)
verification = verify_test_data(
    before, fixture_store=store, endpoints=endpoints, base_url=backend_url,
)
after = acquire_test_data(
    before.case, fixture_store=store, endpoints=endpoints,
    verification=verification,
)
# Optional: dùng receipt, không gọi verification lại trong resolution.
cycle = run_resolution_cycle(
    after.case, context, fixture_store=store, endpoints=endpoints,
    data_verification=verification,
)
```

Receipt chỉ dùng trong tiến trình hiện tại, gắn testcase ID, requirements,
FixtureStore và credential snapshot riêng. `to_dict()` là audit, không phải
receipt dùng để nạp lại facts. Config không được khai assurance `VERIFIED`.
Nếu đổi dữ liệu/config/requirements, phải kiểm chứng lại. Receipt không có TTL;
backend có thể thay đổi sau verification, nên nên sử dụng ngay và vẫn thực thi
assertion bình thường. Verification không bảo đảm testcase sẽ Pass.

## Safety và giới hạn V1

- Operation ID phải khớp đúng một Endpoint từ OpenAPI. Không tìm endpoint bằng prose.
- Cần policy `approved: true`, `test_data_mutation: false`. Chỉ chấp nhận GET,
  HEAD hoặc POST; tác động khai báo duy nhất được hỗ trợ là `session_creation`.
- GET/HEAD không có body hoặc side effect; được ưu tiên trước POST. Write method
  không tự an toàn dù tên là login. Policy là cam kết đã review, không phải suy
  luận tự động từ source code.
- Chặn route/operation admin, seed, registration/OTP, destructive, payment, upload;
  không hỗ trợ operation cần bearer auth, path/query parameter, route template.
- Base URL phải hợp lệ, không userinfo/query/fragment; khớp server OpenAPI khi có.
  Không follow redirect. Không gửi credential trong URL/query.
- Tối đa 3 rules/calls, timeout cấu hình tối đa 10 giây/call; không retry.
  Request body tối đa 4 KiB, response tối đa 64 KiB. Rules trùng hoặc đã được
  chứng minh đầy đủ được bỏ qua, có audit `REDUNDANT_RULE_SKIPPED`.
- Chỉ resolve alias sau safety validation. Chỉ ghi status, facts public được
  chứng minh, operation/policy provenance và timestamp. Không ghi response body,
  token, cookie, header, credential, exception text hay backend message.
- Predicates V1 là field JSON top-level: `success`, `account_exists`, `role`,
  `account_state`, `password_valid`, `entity_exists`. Giá trị phải đúng kiểu;
  không dùng string bí mật hoặc token predicate.

## Outcome và acquisition

| Outcome | Nghĩa |
|---|---|
| VERIFIED | Signature khớp; chỉ các facts trong `proves` được chứng minh |
| INVALID | Probe 4xx hoặc predicate public sai; không chẩn đoán nguyên nhân |
| UNVERIFIED | Không có rule, lỗi transport, redirect, 5xx, signature thiếu |
| UNSAFE_TO_VERIFY | Policy chưa duyệt, tác động/contract/request không hỗ trợ |
| AMBIGUOUS | Operation không duy nhất hoặc evidence live/config xung đột |

401 không phân biệt tài khoản không tồn tại, sai password hay bị khóa. V1 không
hỗ trợ rule dùng 401 để chứng minh trạng thái khóa; cần read-only state contract
riêng. Response không khớp không sinh fact phủ định. Acquisition chỉ trở thành
`AVAILABLE` nếu mọi alias cần thiết có dữ liệu và từng fact cần thiết đã đủ
assurance; một fact verified không chứng minh sibling facts.

`data_verification=` của cycle/loop đưa audit vào `ResolutionContext.data_acquisition`.
Không thay đổi facts trong FixtureStore, business semantics, fixtures validator,
hoặc tự provision dữ liệu. Mọi input vẫn nguyên vẹn.

Provisioning có thể được bật riêng qua `prepare_test_data(allow_provisioning=True,
environment=...)`; xem [gate và schema provisioning](test-data-provisioning.md).
Mặc định vẫn OFF; policy verification không tự cho phép creation/mutation.

## Preparation trong generation/resolution

`prepare_test_data()` trả case copy, acquisition ban đầu/cuối, verification
receipt, attempted/reason, rule decisions, stages và blockers. Đường đi:

1. Không có metadata/alias/source Given được hỗ trợ: `NO_DATA_REQUIRED`, bỏ qua
   acquisition và verification; case không đổi.
2. Acquisition phát hiện aliases/facts cần thiết. Nếu đã đủ assurance: `AVAILABLE`,
   không gọi mạng. Receipt hợp lệ có thể được dùng lại; receipt fake/stale trả
   `VERIFICATION_RECEIPT_REJECTED`, không thử gọi thay thế.
3. Chỉ xét rule có implication cho fact còn thiếu và fixture có đủ giá trị.
   Mỗi rule qua chung `validate_verification_rule()` trước execution. Rule unsafe,
   operation ambiguous hoặc thiếu grounding không được chuyển cho verifier.
4. Tối đa một verification phase (tối đa 3 calls). Reacquire bằng receipt thật;
   facts không được chứng minh vẫn thiếu. Không retry hoặc provisioning.
5. 401 tạo blocker `INVALID_TEST_DATA`, không biến thành `MISSING_FIXTURE` và không
   kết luận sai password/locked. Phân biệt `UNVERIFIED_TEST_DATA`, `UNSAFE_TO_VERIFY`,
   `AMBIGUOUS`, `PROVISIONABLE`, `UNSAFE_TO_PROVISION` và thiếu values.

Base API lấy từ operation server OpenAPI khi có một lựa chọn chính xác; nếu
không có server thì dùng `base_url`. Có nhiều server thì phải có base URL khớp;
nhiều backend khác nhau trong cùng phase giữ unresolved, không đoán host.
Server API không bị thay bằng URL frontend. Một alternative unsafe không chặn
rule độc lập an toàn đã được duyệt.

V2: `run_generation()` (`qctool/generation.py`) prepare dữ liệu cho từng intent trước
khi agent viết case, dùng một `PreparationCache` cho cả lượt chạy; không lặp verification.
Blocker dữ liệu giữ case ở trạng thái blocked trước khi gọi LLM/Playwright.
(Resolution loop/cycle cũ đã retire.) Blockers có trong
generation audit/issues và context; coverage pass dùng contextual executability.

Case copy có blocker được đánh `execution: manual`, để runner hoặc coverage
không có context cũng không chấp nhận auto. Các source steps/expectations không
bị sửa; caller original không đổi. Preparation không tự promote manual → auto.
Không provision kể cả status `PROVISIONABLE`. Receipt audit JSON không thể dùng
để nạp lại verified evidence.

## Chạy tests offline

```bash
uv run python -m pytest tests/test_test_data_verification.py tests/test_test_data_acquisition.py -q
uv run python -m pytest tests/test_test_data_preparation.py -q
uv run python -m pytest tests/ -q -m 'not playwright'
```
