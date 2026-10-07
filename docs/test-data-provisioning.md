---
type: guide
status: implemented
created: 2026-10-07
updated: 2026-10-07
lang: vi
changelog:
  - 2026-10-07 | codex | Thêm provisioning opt-in, một attempt và verification sau đó
---

# Provision fixture trong môi trường test

Mặc định **OFF**. Pipeline/resolution không tự bật provisioning. LLM không chọn
operation, environment, policy, input hay facts. Tài liệu này mô tả config cho
API test đã được review; **không phải registration flow của SalonHub**.

## Metadata và execution rule

Giữ `acquisition.provisioning` hiện có để discovery trả `PROVISIONABLE`. Thêm
`provisioning_rules` riêng để cho phép thực thi; declaration không tự cho phép
mutation. Operation ID, request fields và signature phải có trong contract test.

```yaml
acquisition:
  provisioning:
    - fixture: active_user
      operation_id: createCustomer
      provides:
        account_exists: true
        role: customer
        account_state: active
        password_valid: true
      external_interaction: false
  provisioning_rules:
    - fixture: active_user
      operation_id: createCustomer
      inputs:
        email: {alias: active_user.email}
        password: {alias: active_user.password}
        role: {literal: customer}
      expected:
        status: 201
        json: {$.success: true}
      establishes:
        account_exists: true
        role: customer
        account_state: active
        password_valid: true
      verification_required: true
      cleanup: {}
      policy:
        approved: false
        allowed_environment: test
        allowed_base_urls: [http://127.0.0.1:8099]
        mutation_type: create_fixture
        external_interaction: false
        whitelisted_operations: []
      source_ref: reviewed-test-contract:createCustomer
```

Ví dụ chưa được phép chạy: `approved: false`. Review contract/environment rồi
mới bật. Credentials phải có sẵn qua env-backed aliases trong FixtureStore.
V1 không sinh password/alias mới và không lấy token/credentials từ response.
Literals là giá trị public trong trusted config; secret/email/password fields
phải dùng aliases. Input JSON phải khớp properties/type/enum và required fields.

## API

```python
prepared = prepare_test_data(
    case,
    fixture_store=store,
    endpoints=endpoints,
    base_url="http://127.0.0.1:8099",
    allow_provisioning=True,
    environment="test",
)
```

Option, policy approved, environment và backend URL phải cùng cho phép.
Environment chỉ hỗ trợ `local`, `test`, `staging`; `production` bị từ chối.
Label environment không tự chứng minh host là test: người vận hành phải review
`allowed_base_urls` và OpenAPI servers. Provisioning không tự suy ra backend URL.

## State machine

```text
initial acquisition
  ├─ NO_DATA_REQUIRED / AVAILABLE → không provision
  ├─ default OFF → preparation/verification cũ
  └─ PROVISIONABLE + opt-in
       → đúng một reviewed rule khớp fixture/operation candidate
       → validate policy, contract, aliases, literals, facts
       → một POST creation attempt
       ├─ failed → blocker, không retry/verify tiếp
       └─ PROVISIONED
            → reacquire bằng receipt
            → verification hiện có khi facts còn thiếu
            → final acquisition → AVAILABLE hoặc blocker
```

Nếu `verification_required: true`, creation success không cấp fact proof; cần
verification độc lập. Nếu `false`, chỉ facts trong `establishes` có thể được
chứng minh bởi signature được review. Facts khác vẫn thiếu, và evidence xung đột
không bị ghi đè. `PROVISIONED` không đồng nghĩa testcase executable/Pass.

## Safety và outcomes

- Chỉ một POST JSON creation contract có declared/expected 201; operation ID
  phải duy nhất. Không bearer/admin auth, path/query parameters, route templates,
  arbitrary JS hay file upload body.
- Admin/seed/payment/destructive/upload path hoặc operation bị chặn trừ khi
  **exact operation ID** nằm trong `whitelisted_operations`. Whitelist không bỏ
  qua test-environment gate, auth/body/method/signature constraints.
- Registration/OTP hoặc policy yêu cầu external interaction luôn trả
  `NEEDS_EXTERNAL_INTERACTION`; không có whitelist bypass cho chúng.
- Một provisioning call/attempt; không retry hay follow redirect. Transport dùng
  chung one-shot verification: timeout tối đa 10 giây, request 4 KiB, response
  64 KiB. Verification phase sau đó vẫn tối đa 3 calls theo policy cũ.
- Response chỉ giữ status và fact implications được cho phép; không giữ body,
  token, headers, cookies hoặc exception text. Audit giữ alias names, test backend,
  operation/policy reference và thời điểm.
- Cleanup chỉ là declaration `{operation_id, source_ref}` tùy chọn. Không tự
  validate/execute cleanup flow, không khẳng định dữ liệu đã được xóa.
- Receipt runtime gắn testcase/requirements, FixtureStore/config/credentials và
  contract snapshot. Đổi contract/environment/backend hoặc dùng JSON/fake receipt
  bị từ chối. Reuse phải truyền rõ `provisioning_receipt=` và environment; không
  silently retry sau receipt lỗi. Receipt không có TTL; backend có thể thay đổi
  sau đó, nên verification/test execution vẫn cần thực hiện khi policy yêu cầu.
- Input testcase/config/context giữ nguyên; chỉ copy mang aliases/facts/audit.

Outcomes: `PROVISIONED`, `FAILED`, `UNSAFE_TO_PROVISION`, `AMBIGUOUS`,
`NEEDS_EXTERNAL_INTERACTION`. Preparation dùng `PROVISIONING_FAILED` cho attempt
thất bại, `INVALID_TEST_DATA` khi verification không đạt signature, hoặc
`UNVERIFIED_TEST_DATA` khi facts vẫn chưa được chứng minh. Không đổi testcase
expectations để vượt blocker.

## Tests offline

```bash
uv run python -m pytest tests/test_test_data_provisioning.py -q
uv run python -m pytest tests/ -q -m 'not playwright'
```
