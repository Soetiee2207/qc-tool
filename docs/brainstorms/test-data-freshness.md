---
type: design
status: implemented
created: 2026-10-08
updated: 2026-10-08
lang: vi
changelog:
  - 2026-10-08 | codex | Tách creation history và assurance freshness trong run
---

# Test-data freshness trong một lượt chạy

## Identity và scope

Identity HMAC giữ nguyên: fixture, exact aliases/facts/assurance requirement,
credential fingerprint, config/rules/policy, OpenAPI, backend, environment và
mutation gate. Không có testcase ID trong identity. Không nới weaker proof thành
stronger facts. Cache là object runtime của một generation run, không lưu/import
receipt hoặc tạo global persistent cache. API key/credential không nằm trong audit.

## Hai loại thông tin

- Creation history: operation đã tạo fixture trong run hiện tại, có receipt xác
  thực, contract/environment/origin phù hợp. Giữ sự kiện này ngay cả khi verify
  thất bại để không create lần nữa. Nó không tự chứng minh trạng thái hiện tại.
- Live assurance: facts từ verification hoặc implication được provisioning rule
  duyệt. Hết freshness thì không forward facts/verification cũ sang acquisition.
  Creation observation được rebind với facts rỗng, giữ nguồn và cleanup metadata.

Operator declarations vốn chỉ có assurance DECLARED không phải live verification.
Nếu requirement cho phép declarations, đọc lại trusted config là nguồn authority;
TTL của live evidence không biến declaration thành invalid hay nâng nó lên VERIFIED.

## Freshness và refresh

`PreparationCache(freshness_seconds=300, clock=time.monotonic)` là mặc định.
Run owner có thể truyền cache với freshness riêng vào `run_generation`/
`run_coverage_loop`/`run_resolution_loop`. CLI hiện giữ default 300 giây.
Clock injectable phục vụ test; không cần sleep hay đổi thời gian hệ thống.
Không tăng TTL để che lỗi. Hết hạn không đồng nghĩa giả mạo receipt.

```text
PREPARED → REUSED (exact identity + fresh assurance)
         → STALE → creation history REUSED → reviewed verification
                                              ├→ REVERIFIED
                                              └→ UNVERIFIED / BLOCKED
```

Refresh gọi lại preparation hiện có, không chọn endpoint hay implication mới.
Verifier vẫn qua policy/operation/origin/secret/timeout/call-budget checks hiện có.
Một preparation chỉ có một bounded verification phase. Không verifier an toàn,
proof partial hoặc INVALID thì không AVAILABLE. INVALID giữ phân loại chính xác;
HTTP401 không tự chứng minh locked/nonexistent/password incorrect.

Creation receipt được chuyển vào existing preparation để chặn creation branch.
Ngay cả khi chỉ có verification history và không có creation event, expiry path
cũng tắt mutation: hết proof không chứng minh entity biến mất. Không tự reprovision
để khôi phục assurance. Acquisition với identity mới vẫn theo policy cũ.

Authenticity được kiểm tra trước refresh; fake/mutated receipt, changed store,
timestamp không hợp lệ bị PREPARATION_RECEIPT_REJECTED, không gọi network. Refresh
chỉ rebind private runtime evidence sau exact identity và authentic history.

## Audit

Kết quả giữ `preparation_identity`, `reused_from_testcase`, preparation mode,
ordered stages, verification/provisioning attempted và executed_calls. Lifecycle
gồm PREPARED, REUSED, STALE, REVERIFIED, UNVERIFIED/BLOCKED. Reused creation không
được đếm là call mới; invalid verification chỉ là negative evidence, không reusable
available proof. Secret vẫn runtime-only, observation/audit dùng schema sanitization
hiện có; không serialize private receipt.

## Regression

Clock giả lập: create+verify case A → vượt freshness → case B cùng identity →
verify lại → AVAILABLE, tổng 1 create + 2 verify. Kiểm tra thêm unsafe/missing/
partial/failed verifier, config declarations, identity changes, stronger facts,
fake receipt, run separation, mutation safety và secret redaction.
