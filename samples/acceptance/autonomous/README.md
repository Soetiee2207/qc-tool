---
type: acceptance
status: implemented
created: 2026-10-07
updated: 2026-10-07
lang: vi
changelog:
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

`acceptance.json` ghi prompts/completions đã redact, provider metadata, các
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
