---
type: finding
status: partial
created: 2026-10-08
updated: 2026-10-08
lang: vi
changelog:
  - 2026-10-08 | codex | Ghi nhận pilot semantic 3/7 executable và blocker receipt
---
> Ghi chú 2026-10-09: finding này đo engine V1 (semantic resolution/exploration), đã retire ở
> QC-TOOL V2. Số liệu đúng tại thời điểm ghi; kết quả hiện tại: `docs/findings/agent-redesign.md`.


# Customer pilot: semantic resolution

## Kết quả cuối

Chạy nguyên tài liệu/config customer, không sửa testcase thủ công:

```bash
uv run qctool run --config qctool.customer.e2e.yaml --llm \
  --out artifacts/customer-semantic-final-validation
```

Baseline `artifacts/customer-e2e`: 0/7 executable, 7 Not Executed.
Lượt cuối: 3/7 executable, 2 Pass, 1 Fail, 4 Not Executed.
Executable coverage 3/7; generation_success=false, INCOMPLETE_COVERAGE.
PipelineResult.ok=true thể hiện pipeline hoàn tất; summary exit_code=1 vì
execution có Fail. Không đồng nghĩa generation hoặc sản phẩm đạt yêu cầu.

| Obligation gốc | ID cuối | Executable | Runtime | Blocker / tiến triển |
|---|---|---|---|---|
| AC-customer-001-1 | TC_CUSTOMER_001 | Có | Fail | Capture login HTTP401; source yêu cầu 200 |
| AC-customer-001-2 | TC_CUSTOMER_008 | Có | Pass | Form rỗng, alert, POST count0, URL/login |
| AC-customer-001-3 | TC_CUSTOMER_013 | Không | Not Executed | Semantic authority/UI grounding; sau đó receipt hết hạn |
| AC-customer-001-4 | TC_CUSTOMER_014 | Không | Not Executed | Interaction chưa có grounding an toàn; receipt hết hạn |
| AC-customer-001-5 | TC_CUSTOMER_015 | Không | Not Executed | Semantic clause chưa đầy đủ; receipt hết hạn |
| AC-customer-001-6 | TC_CUSTOMER_016 | Không | Not Executed | Semantic authority chưa chứng minh; receipt hết hạn |
| AC-customer-001-7 | TC_CUSTOMER_007 | Có | Pass | Anonymous/profile redirect/login đúng source |

ID thay đổi qua coverage pass; so sánh bằng traces_to, không suy ra nghĩa từ số ID.
Case form rỗng đi qua DeepSeek thật, approved interaction exploration và retry;
không dùng recorded completion hay script phục hồi source.

## Bằng chứng runtime

TC001: session anonymous → /login → fill hai fixture alias → submit/capture
POST/api/auth/login → HTTP401 → assert200 Fail. Không suy ra cụ thể sai password,
account không tồn tại hay account bị khóa từ một HTTP401. Không sửa expectation.

TC008: anonymous → /login → assert email/password rỗng → click submit với bounded
network window2000ms → assert hai field vẫn rỗng → alert visible → exact text
`Vui lòng điền đầy đủ thông tin` → request_count=0 → URL/login$. Tất cả Pass.
Alert có stable test_id; toast/status trùng text không bị dùng để chọn action.

TC007: anonymous → /profile → assert/login$; Pass.

## Thay đổi engine

Canonical IR gồm session/precondition/fill/activate/navigate/visible/url/api/
no_request/empty. LLM normalization vẫn untrusted; source quote, slot, polarity,
fixture fact, thứ tự và completeness phải qua validator. Không bỏ mọi grammar:
legacy compatibility còn tồn tại, semantics không chứng minh được vẫn unresolved.

Control grounding dùng semantic field/role/label thay toàn câu bằng DOM name.
Không tự chọn giữa các control cùng nghĩa. Chỉ expected visible/text đã chứng
minh state chain mới ưu tiên unique stable witness hơn toast trùng text.
Route Given/When literal có source authority được khám phá dù chưa có UIMap.
API reference không tạo browser-route authority. Rejection có validated source
IR có thể sinh evidence need; fabricated proposal không tự tạo quyền exploration.
Compound sibling/order và state/action/source provenance được giữ qua renumber.

## Calls và chi phí quan sát được

10 resolution + 5 exploration adapter calls; 16 HTTP attempts, 15 usage receipts.
Prompt121519 + completion65526 =187045 returned tokens.
Cache hit67072, miss54447. Attempt không có usage không được tính là zero billed
tokens. Nhiều lượt diagnostic trước đó không nằm trong các tổng lượt cuối này.

## Vấn đề còn lại

Preparation cache run-scoped có TTL300s. Khi receipt hết hạn, reuse rejection
trở thành UNVERIFIED_TEST_DATA/PREPARATION_RECEIPT_REJECTED dù initial acquisition
với operator-declared facts vẫn AVAILABLE. Đây là blocker tool/cache cần sửa
riêng; không kết luận người dùng thiếu account. Không thay policy hoặc fixture
trong task này. CLI còn liệt kê blocker từ các candidate pass cũ; số dòng đó
không phải số testcase cuối.

Semantic validation vẫn có giới hạn extractive slot proof, không phải theorem
prover cho prose tùy ý. Các control/state chưa có authority tiếp tục unresolved.
Không quan sát UI để thay business expectation. HTTP401 là runtime backend
observation; nguyên nhân fixture/backend chưa được kiểm chứng riêng.

## Kiểm tra

- Full offline cuối: 1178 passed, 69 deselected (36.05s).
- Local autonomous acceptance: 10 passed, gồm 4/4 Chromium Pass với offline
  replay completions; đây không phải live DeepSeek.
- Offline benchmark regression trong full suite giữ zero unsafe repairs.

Artifacts: `artifacts/customer-semantic-final-validation/generation.json`,
`summary.json`, `testcases.yaml`, `testcases.xlsx`, và
`runs/20261008-005229/{results.json,results.csv,report.md,junit.xml,evidence/}`.
Chi tiết ordered cycle/proposal/validation/exploration nằm trong generation.json.
