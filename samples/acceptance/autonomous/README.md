---
type: acceptance
status: implemented
created: 2026-10-07
updated: 2026-10-07
lang: vi
changelog:
  - 2026-10-07 | codex | Ghi nhận hai lượt live cache reuse đạt 4/4 Pass
  - 2026-10-07 | codex | Thêm acceptance autonomous trên ứng dụng loopback mới
---

# Acceptance autonomous — local, không dữ liệu production

```bash
uv run python scripts/run_autonomous_acceptance.py --enable-llm \
  --out artifacts/autonomous-acceptance-live
```

Provider dùng cấu hình hiện có `QCTOOL_LLM_BASE_URL`, `QCTOOL_LLM_API_KEY`,
`QCTOOL_LLM_MODEL` (xem `qctool/llm_provider.py`); timeout acceptance 90 giây.
Không có `--enable-llm` thì script dừng trước browser/model. Không đưa live
acceptance vào offline CI. Script kết thúc với mã 1 nếu mục tiêu tối thiểu chưa
đạt; không tự sửa proposal bị từ chối, không tự gọi lại harness để lấy Pass.

## Đầu vào và phạm vi

- `urd.md`: một user story, bốn AC Given/When/Then.
- `srs.md`: hành vi ứng dụng local; không suy expected từ UI quan sát.
- `openapi.yaml`: createCustomer và establishSession.
- `policy.yaml`: fixture aliases env-only, facts cần verify, rule provisioning và
  verification reviewed. `APPLICATION_BASE` được thay bằng origin loopback mới.
- `scripts/autonomous_acceptance_app.py`: app trong bộ nhớ, database rỗng mỗi run,
  không mail/OTP, không database ngoài process, không credential trong log.

Không có testcase YAML, proposal hay completion đầu vào. Script ingest tài liệu,
bootstrap UI bằng crawler anonymous tại các route trích từ docs, rồi gọi
`run_generation()` với không có existing cases. Cơ chế coverage/resolution loop,
context builder, validators, explorer, safe applier và runner đều là code hiện có.
Script không khôi phục/sửa bước testcase thủ công. Không cần SalonHub.

## Bốn nghĩa vụ

1. Form email/password trống: assert cả hai ô trống → Login → alert đúng text,
   POST /api/session count=0 trong cửa sổ 2 giây → URL /entry.
2. Happy login: account ban đầu chưa tồn tại → createCustomer → verification
   establishSession chứng minh facts đã khai báo → trusted alias fills → capture
   response 200/success=true → URL /workspace.
3. Wrong password: account dùng chung với case 2; rule riêng verify account bằng
   đúng password, nhưng testcase dùng alias wrong_password. 401 chỉ kiểm expected
   negative result, không suy ra account locked hoặc không tồn tại.
4. Preview /start → /review → nhập orchid → Check → Search ready và URL /review.

Happy login dùng SPA route transition. Preview dùng link sang document khác.
Capture body qua full-document redirect tức thời hiện là hạn chế runtime đã phát
hiện trong thử nghiệm; fixture không dùng full-document redirect cho login.
Không coi acceptance này là chứng minh rằng mọi loại redirect đều capture được.

## Trust và budget

Provisioning mặc định OFF ở các API production. Script bật rõ
`allow_provisioning=True, environment='local'`, chỉ cho exact ephemeral origin,
POST operation đã reviewed. Một attempt, không retry provisioning. Verification
được áp dụng trước LLM và receipt được reuse trong cùng resolution loop.

LLM chỉ trả proposal/plan untrusted. Explorer chỉ chạy actions đã được validator
phê duyệt; tối đa 5 actions/request. Tối đa một coverage pass và ba resolution
cycles/case. Unknown/unsafe clauses vẫn unresolved. Không autonomous provisioning
qua LLM; chỉ trusted policy chọn operation.

Credentials được sinh runtime và đưa vào env aliases, khôi phục env khi kết thúc.
Prompts/audits/YAML/XLSX chỉ dùng aliases. Runner giữ cơ chế tắt screenshot/trace
trên fixture/capture cases để tránh lưu request/secret; safe cases có evidence
bình thường. Backend chỉ ghi method/path/status.

## Artifacts và tiêu chí

`requirements.yaml`, `ui-map.yaml`, `policy.yaml`, `openapi.yaml`,
`generation.json`, `testcases.yaml`, `testcases.xlsx`, `results.json`,
`results.csv`, `junit.xml`, `report.md`, `acceptance.json`, `evidence/`.

`acceptance.json` ghi composition counts (không lưu raw prompt), completions đã redact, provider metadata, các
kết quả runtime và số API calls đã sanitize. `generation.json` giữ obligation →
logical testcase → data preparation → cycle → proposal/plan → validation →
exploration → application history.

Mục tiêu tối thiểu: AC-001-1 và AC-001-2 phải **đã chạy Pass**, provisioning và
validated exploration thật phải xảy ra. `generation_success` độc lập với kết quả
runner; case executable vẫn có thể Fail/Blocked. AC chưa chạy không là Pass.

Offline regression có completion stub (được gọi rõ là stub), nhưng mở Chromium
và gọi backend local thật:

```bash
uv run pytest tests/test_autonomous_acceptance.py -q
```

## Kết quả live ngày 2026-10-07

Lượt `artifacts/autonomous-acceptance-final-proof` dùng DeepSeek thật
(`deepseek-flash`, 13 calls: 7 resolution + 6 exploration), không replay.

| Nghĩa vụ | Cycles | Kết quả runner |
| --- | ---: | --- |
| Empty form | 2 | Pass, không POST trong cửa sổ 2 giây |
| Happy login | 1 | Pass, provision 201 → verify 200 → UI login 200 |
| Wrong password | 2 | Not Executed: assertion thiếu API evidence hợp lệ |
| Hai trang Preview/Search | 3 | Not Executed: assertion chưa chứng minh semantics |

Exploration thật đã click form trống và thực hiện Preview → /review → fill →
Check, thu được alert `Search ready`. Điều đó không tự làm testcase hai trang
executable: assertion proposal vẫn phải qua validator. Model có cả response
sai schema/JSON; không được auto-correct để lấy Pass.

Mục tiêu acceptance tối thiểu đạt, nhưng executable coverage là 2/4 nghĩa vụ,
`generation_success=false`, `INCOMPLETE_COVERAGE`. Hai case chưa chạy không được
tính Pass. Lượt offline dùng stub đạt cả bốn chỉ chứng minh đường cơ chế có thể
chạy khi proposal hợp lệ; không phải bằng chứng model live đạt cả bốn.

## Đóng gaps bằng operation/state provenance — 2026-10-07

Lượt fresh `artifacts/autonomous-acceptance-outcome-proof` giữ nguyên docs/OAS,
app, fixture policy và harness. DeepSeek thật gọi 8 lần: 5 resolution,
3 exploration. Cả bốn testcase executable và runner Chromium **4 Pass**;
coverage 4/4, `generation_success=true`, stop `COVERAGE_COMPLETE`.

- API expansion được dùng contract reference ở cấp change cho các atoms của
  đúng operation source. Response alias phải trỏ tới writer gần nhất đúng
  method/path/origin; counter, writer bị overwrite hoặc operation sai bị reject.
  Contract không được coi là response runtime đã quan sát.
- Exploration giữ approved action bindings trong từng state. Assertion UI phải
  theo đúng source clauses, toàn bộ actions, navigation chain và final current
  `state_id`. Intermediate/stale/unrelated states không chứng minh outcome.
- Resolver có thể tạo một proposal deterministic mới gồm toàn bộ outcome atoms
  từ source và evidence. Proposal LLM thiếu exact text/broad URL regex vẫn reject;
  không chỉnh sửa malformed model output để được chấp nhận.

Cycles lần lượt: 2, 1, 1, 3. Case hai trang có invalid completion ở cycle 1 và
assertion thiếu semantics ở cycle 2; cycle 3 hoàn tất bằng source/state proof.
Đây là kết quả live của lượt này, không bảo đảm mọi completion tương lai hợp lệ.

## Routing capability — 2026-10-07

Lượt fresh `artifacts/autonomous-acceptance-routed-final` giữ nguyên toàn bộ inputs,
app và harness. DeepSeek thật (`deepseek-flash`) gọi **5 lần**: 3 resolution,
2 exploration, so với baseline 8 lần (5 + 3). Cả 4 case executable và Chromium
**4 Pass**; executable coverage 4/4, `generation_success=true`. Cycles: 2, 1, 1, 3.
Tổng usage do provider trả: **52.420 tokens**, baseline **85.545 tokens**.

| Case intent | Baseline capability calls theo cycles | Routing mới |
| --- | --- | --- |
| Empty form | R+E → deterministic | E → deterministic |
| Happy login | R | R |
| Wrong password | R | R |
| Hai trang | R+E → R+E → deterministic | E → R → deterministic |

Mỗi cycle lưu `decisions`: từng gap/classification, capability đã chọn, lý do và
capabilities đã skip. Resolver deterministic luôn chạy trước routing. Evidence
mới được đưa vào cycle tiếp theo; resolver lại chạy trước model. Nếu context đã
có evidence, proposal invalid/unresolved không tự kích hoạt exploration. Giữ
nguyên max-cycles, no-progress/repeated-state và toàn bộ validation/safety.

Replay fixtures đã bỏ các unresolved completions đầu tiên không còn được gọi
trước exploration và các completions dành cho work bị BLOCKED. Ground truth,
source obligations, observations, semantic/safety expectations không đổi.

Lượt trước đó `artifacts/autonomous-acceptance-routed-proof` cũng có 5 calls,
nhưng resolution cuối bị `INVALID_COMPLETION`: case hai trang **Not Executed**,
3/4 Pass, coverage chưa đủ. Không retry/auto-correct completion ấy trong loop;
lượt final là chạy mới cùng inputs. Model live vẫn có thể trả JSON không hợp lệ.

## Prompt projection và usage — 2026-10-07

Prompt dùng một view detached: giữ source clauses, relevant exact operations,
controls cùng locator/name (kể cả conflicts), current state và ancestry cần cho
proof. Action manifests lặp được tách thành `action_chains`; audit receipts và
obsolete histories không gửi lại. Validator vẫn dùng context gốc đầy đủ.

Composition diagnostics chỉ ghi bytes và estimate UTF-8 bytes/4 theo sáu section:
protocol/schema, requirement/source, OpenAPI, UI/state, fixture/data, testcase/gaps.
Đây không phải tokenizer DeepSeek. Usage tổng prompt/completion là số provider trả.
Budget mặc định 12.000 estimated tokens (48.000 bytes); vượt budget trả
`PROMPT_BUDGET_EXCEEDED` trước model call, không cắt source để vừa budget.

Lượt fresh `artifacts/autonomous-acceptance-token-final`: cùng inputs, DeepSeek
`deepseek-flash`, 5 calls (3 resolution + 2 exploration), 4/4 executable và 4/4
Chromium Pass, coverage 4/4. Prompt 27.368, completion 10.269, tổng 37.637 tokens:
giảm 28,2% so với 52.420 baseline. Cycles 2, 1, 1, 3.

Lượt thử trước `autonomous-acceptance-token-proof` có 6 calls, 3 Pass và 1 Not
Executed: thiếu plan `testcase_id` và sai vị trí `reason` đã bị parser reject.
Prompt sau đó làm rõ hai field bắt buộc; parser/validator không auto-correct.
Không coi lượt thử đó là thành công hay bỏ qua chi phí của nó.

So sánh usage và breakdown an toàn, không xuất historical prompts:

```bash
uv run python scripts/compare_llm_usage.py \
  artifacts/autonomous-acceptance-routed-final/acceptance.json \
  artifacts/autonomous-acceptance-token-final/acceptance.json \
  --out artifacts/autonomous-acceptance-token-final/token-comparison.json
```

## Prefix cache reuse — 2026-10-07

Hai cache families độc lập: `resolution` và `exploration`, protocol version 2.
Prompt đặt protocol/schema/safety trước, rồi semantic source/contract đã chọn,
cuối cùng mới testcase/gaps/runtime states/fixtures và examples có identifiers.
Maps serialize theo key; lists giữ thứ tự steps/actions/clauses/state chains.

Timestamp, audit metadata, source provenance và server bindings không tham gia
semantic project prefix; vẫn giữ nguyên trong dynamic tail. Evidence IDs cần
validator không bị đổi/xóa. Thay đổi source/contract đã chọn làm đổi project suffix;
protocol family vẫn ổn định. Không mở lại toàn bộ project để tạo prefix lớn hơn.

Provider audit chỉ lưu family/version, SHA-256 fingerprints, byte counts và usage;
không gửi hashes cho model, không lưu raw prompts. Không có response cache.
Missing/malformed cache counts là unknown; hit ratio tổng là weighted hit/prompt,
không phải trung bình các phần trăm call.

```bash
uv run python scripts/run_autonomous_acceptance.py --enable-llm \
  --out artifacts/autonomous-acceptance-cache-run1
uv run python scripts/run_autonomous_acceptance.py --enable-llm \
  --out artifacts/autonomous-acceptance-cache-run2
uv run python scripts/report_cache_usage.py \
  artifacts/autonomous-acceptance-cache-run2/acceptance.json \
  --out artifacts/autonomous-acceptance-cache-run2/cache-usage.json
```

Không đổi docs/OAS/app/policy/outcomes giữa hai lượt. Mỗi app instance vẫn dùng
fresh database, random loopback port và runtime credentials riêng. Fingerprint
stable prefix của cả 5 call tương ứng đều giống giữa run 1 và run 2.

| Chỉ số thực do DeepSeek trả | Run 1 | Run 2 |
| --- | ---: | ---: |
| Calls (resolution + exploration) | 3 + 2 | 3 + 2 |
| Prompt tokens | 29.797 | 29.756 |
| Cache hit / miss | 5.376 / 24.421 | 10.752 / 19.004 |
| Overall hit ratio | 18,04% | 36,13% |
| Resolution hit ratio | 18,84% | 33,75% |
| Exploration hit ratio | 15,62% | 43,38% |
| Completion tokens | 9.266 | 7.232 |
| Total tokens | 39.063 | 36.988 |
| Executable / Chromium Pass | 4/4 / 4/4 | 4/4 / 4/4 |

Cả hai có executable coverage 4/4 và generation SUCCESS. Run 2 hit ở cả 5
calls; cache hits vẫn phụ thuộc provider, không được đảm bảo bởi client. Prefix
schema clarification làm prompt tăng so với baseline 27.368; đây là tối ưu reuse,
không phải khẳng định mọi call sẽ ít tokens hơn. Parser/validator/routing không đổi.
