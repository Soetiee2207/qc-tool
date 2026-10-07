---
type: finding
status: verified
created: 2026-10-08
updated: 2026-10-08
lang: vi
changelog:
  - 2026-10-08 | codex | Pilot không còn bị chặn bởi preparation receipt expiry
---

# Customer pilot sau sửa run-scoped freshness

## Lệnh và phạm vi

```bash
uv run qctool run --config qctool.customer.e2e.yaml --llm \
  --out artifacts/customer-freshness-live
```

Giữ nguyên customer docs/config, testcase semantics, validators và response capture.
Không sửa semantic blocker, không provision hay probe account production.
Lượt này dùng DeepSeek thật và Chromium thật, không dùng replay completions.

## Kết quả

8 requirement sources, 7 obligations; executable coverage 3/7.
generation_success=false / INCOMPLETE_COVERAGE; coverage loop dừng REPEATED_STATE.
PipelineResult.ok=true (pipeline hoàn tất), CLI exit3 / GENERATION_INCOMPLETE.
Runtime: 2 Pass, 0 Fail, 1 Blocked, 4 Not Executed. Executable không đồng nghĩa Pass.

| Obligation | Case cuối | Executable | Runtime | Blocker |
|---|---|---|---|---|
| AC-customer-001-1: happy login | TC_CUSTOMER_008 | Có | Blocked | UI_RESPONSE_TIMEOUT tại submit/capture |
| AC-customer-001-2: form rỗng | TC_CUSTOMER_002 | Có | Pass | Không |
| AC-customer-001-3: profile | TC_CUSTOMER_013 | Không | Not Executed | UI/workflow grounding chưa an toàn |
| AC-customer-001-4: orders | TC_CUSTOMER_014 | Không | Not Executed | Semantic completeness/expansion và grounding |
| AC-customer-001-5: appointments | TC_CUSTOMER_015 | Không | Not Executed | UI/workflow grounding chưa an toàn |
| AC-customer-001-6: customer/admin | TC_CUSTOMER_016 | Không | Not Executed | Semantic authority/expansion chưa chứng minh |
| AC-customer-001-7: anonymous/profile | TC_CUSTOMER_007 | Có | Pass | Không |

ID được cấp lại qua coverage pass; so sánh nghĩa bằng traces_to.
Form rỗng: hai field rỗng, click submit, exact validation alert, login POST count0
trong 2000ms, URL/login$. Anonymous/profile chuyển tới/login đúng source.
Happy login fill hai trusted alias thành công rồi submit không thu được unique
safe response trong bounded window. Không có HTTP status để kết luận password
sai/account không hợp lệ. Không sửa timeout/expectation để làm Pass.

## Preparation lifecycle

16 preparation results cấp resolution loop: 3 EXECUTED (gồm 2 NO_DATA_REQUIRED),
13 REUSED. Lifecycle có 1 PREPARED và 13 REUSED; 0 STALE, 0 REVERIFIED.
0 provisioning call, 0 verification/re-verification call. `unresolved_test_data=[]`.
Không có case bị PREPARATION_RECEIPT_REJECTED hay blocked chỉ vì receipt expiry.

Config customer tin operator declarations, require_verified=false, provisioning
OFF, không reviewed verification rule. DECLARED vẫn là DECLARED, không bị nâng
thành live VERIFIED và không bị áp TTL dành cho live assurance. Mỗi lần reuse
reacquire từ trusted config hiện tại. Các candidate obligation3–6 đã được thử
resolution ở cả 3 pass; trước đây các pass sau dừng ngay vì receipt expiry.

Offline time simulation cho trường hợp có provision/live proof: case A create+
verify → vượt freshness → case B same identity → verify lại → AVAILABLE;
tổng 1 create + 2 verify, không create lần hai. Missing/unsafe/failed/partial
proof vẫn unavailable, không provisioning loop. Không dùng fixture customer để
thực hiện thử nghiệm mutation này.

## DeepSeek metadata

37 adapter invocations: 22 resolution + 15 exploration. 44 HTTP attempts:
33 completions có usage, 11 timeout attempts. Returned prompt271678,
completion142373, total414051; cache hit155392, miss116286. Usage thiếu ở timeout
không chứng minh zero billing. Đây là số lượt cuối, không cộng diagnostic trước.
Các call preparation bằng0 không có nghĩa testcase không thực hiện login/API.

## Tests và artifacts

- Full offline: 1195 passed, 69 deselected (30.75s).
- Cache tests: 43 passed.
- Local autonomous acceptance: 10 passed, gồm 4/4 real Chromium Pass với offline
  completion fixtures; không gọi chúng là live DeepSeek.

Artifacts: `artifacts/customer-freshness-live/{generation.json,summary.json,
testcases.yaml,testcases.xlsx}`, và
`artifacts/customer-freshness-live/runs/20261008-014612/{results.json,results.csv,
junit.xml,report.md,evidence/}`. Generation audit giữ ordered preparation/cycle
history. Báo cáo này không tuyên bố 7/7 executable hoặc 7/7 Pass.
