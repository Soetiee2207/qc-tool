---
type: finding
status: verified
created: 2026-10-08
updated: 2026-10-08
lang: vi
changelog:
  - 2026-10-08 | codex | Đối chiếu login thủ công và QC bằng metadata/HMAC riêng tư
---

# Đối chiếu login thủ công và prerequisite QC

## Phạm vi

Không sửa `.env`, fixture, testcase, expectation, semantic mapping, validator,
capture runtime hoặc ứng dụng. Không gọi DeepSeek. Thêm riêng script chẩn đoán
và test bảo vệ tính riêng tư/tính không can thiệp của bộ ghi.

## Khác biệt đã chứng minh

Người dùng đăng nhập thành công trong Chromium chẩn đoán, cùng origin frontend
và backend đang được QC dùng. Timeline ghi một POST `/api/auth/login` trả 200;
browser chuyển `/login` → `/` và có hai localStorage key `token`, `user`.
Không lưu giá trị các key này.

HMAC trong bộ nhớ chứng minh field `email` gửi trong lượt thủ công **khác**
giá trị `active_user.email`; field `password` **khớp** `active_user.password`.
QC runner và prerequisite explorer đều gửi đúng hai giá trị fixture đã cấu hình.
Không lưu HMAC, khóa HMAC hoặc giá trị credential.

`active_user.email` lấy từ `QCTOOL_USERNAME`, password lấy từ `QCTOOL_PASSWORD`.
Kiểm tra riêng xác nhận hai alias khớp `.env` và không bị shell override khác
giá trị. Các alias invalid/locked không được dùng trong flow được chẩn đoán.

**Điểm sai khác là định danh login thực tế, không phải QC không đọc được env.**
Không đủ bằng chứng để nói khác biệt đó là typo, email/phone khác nhau, hoặc
account khác. Không truy vấn database và không tự sửa định danh.

## Bảng đối chiếu

| Thuộc tính | MANUAL SUCCESS | QC prerequisite | Phân loại |
|---|---|---|---|
| Method | POST | POST | request construction: giống |
| Endpoint | `https://salonhub-3cg8.onrender.com/api/auth/login` | Cùng endpoint | endpoint/capture: giống |
| Content type | application/json | application/json | request construction: giống |
| Body | email:string, password:string | Cùng cấu trúc | request construction: giống |
| Field email so với fixture | Không khớp | Khớp | credential resolution: khác |
| Field password so với fixture | Khớp | Khớp | credential resolution: giống |
| Cookie trước login | Không có | Không có | session/cookie: giống |
| Cookie thêm/đổi | Không có trong snapshot cuối | Không có | session/cookie: giống |
| Authorization / CSRF header | Không có | Không có | session/CSRF: giống |
| Hidden input | Không có | Không có | session/CSRF: giống |
| Origin | `https://salonhub-soe.vercel.app` | Giống | request construction: giống |
| Referer | `https://salonhub-soe.vercel.app/` | Giống | request construction: giống |
| User Agent | Headed Chromium | Headless Chromium | request construction: khác; headed QC cũng nhận 401 |
| Response | HTTP 200 trong timeline | HTTP 401, success=false | application behavior: khác |
| URL cuối | `/` | `/login` | application behavior: khác |
| Session cuối | Có key token/user | Không có | session: hệ quả của kết quả login |

Lượt thủ công và QC bắt đầu ở context riêng mới: không có cookie/token/user.
Không chuyển storage_state của lượt thủ công sang QC. QC fill đúng unique
`login-email-input`, `login-password-input`; DOM sau fill khớp giá trị runtime.
Submit dùng unique button `login-submit-btn`, step 5. Capture prerequisite có
đúng một request matching, gắn với chính submit này; không nhầm response cũ.

Timeline chứa bootstrap/navigation/resource requests đã bỏ query/fragment.
Đối chiếu tới POST login: 13 request trước login của manual và QC runner xác
nhận có cùng method/URL/resource_type, cùng thứ tự, không bị event truncation.
GET notifications/cart/services/products/socket sau login thành công là hoạt
động **sau** login, không phải bằng chứng QC thiếu prerequisite trước login.
Thứ tự tải asset có thể khác; không gán quan hệ nhân quả từ khác biệt đó.

## Giới hạn của lần capture đầu

`artifacts/login-differential/report.json` giữ nguyên output ban đầu. Bộ ghi
ban đầu gọi Playwright RPC trong request callback, gây reentrant event dispatch:
timeline thấy response nhưng record response chưa được gắn đúng, và runner
chẩn đoán bị timeout capture. Đây là lỗi **script chẩn đoán**, không phải bằng
chứng runtime bình thường timeout hay sản phẩm chậm.

Timeline/manual final session và request HMAC vẫn chứng minh các dữ kiện nêu
trên. Tuy nhiên JSON response của manual chưa được ghi: không khẳng định đã
đọc `success=true` từ JSON lượt đó. Nhãn `MANUAL SUCCESS NOT CAPTURED` trong
output cũ phản ánh thiếu record JSON, không phủ nhận login thực tế thành công.

Script đã sửa để callback chỉ lấy cached metadata; đọc headers/body/DOM/cookies
ở ngoài callback. Regression Chromium local kiểm tra cả 200 và 401 không bị
bộ ghi biến thành capture timeout. Lần xác nhận thứ hai dùng output riêng:
`artifacts/login-differential-confirmed/report.json`; không sửa output cũ.

Lượt thứ hai không có human login trong cửa sổ chờ 300 giây, nên JSON comparison
đúng là `INCOMPLETE_REFERENCE`, exit 2, không phải complete manual comparison.
Phần QC vẫn chạy thật và đầy đủ:

- Runner headed: step 1–5 OK; step 5 capture duy nhất HTTP 401 + success=false,
  trigger step 5; step 6 Fail expected 200; step 7–8 chưa chạy. Final `/login`.
- Prerequisite plan recorded được validator hiện tại duyệt VALID; explorer thật
  fill/fill/click; response duy nhất 401 + success=false; transition mong đợi
  `/` không xuất hiện, trả `UNEXPECTED_TRANSITION`, không tiếp tục goto đích.
- Cả hai có `capture_belongs_to_submit=true`; DOM fill và request credential
  khớp active fixture. Không có cookie/Authorization/CSRF/hidden field.
- Testcase không đổi; context manual/QC khác object; không có model call.
- Scan hai JSON không tìm thấy giá trị credential/API key đã cấu hình; không
  có khóa hoặc digest HMAC được serialize.

Không có HTTP redirect predecessor cho QC login request; manual có navigation
SPA sang `/` trong timeline. Không lưu token để đối chiếu giá trị session.
Metadata cookie là snapshot trước submit và sau kết thúc, không phải log mọi
cookie mutation trung gian. Không khẳng định đã đọc response body shape của
manual; đó là thông tin còn thiếu của reference đầu.

## Source hỗ trợ và giới hạn kết luận 401

- `SalonHub/frontend/src/pages/auth/Login.jsx:66`: submit gửi form qua `login(form)`.
- `SalonHub/frontend/src/services/authService.js:5`: POST `/auth/login`.
- `SalonHub/frontend/src/services/api.js:5`: base `/api`, JSON, withCredentials;
  Authorization chỉ thêm khi localStorage có token.
- `SalonHub/frontend/src/contexts/AuthContext.jsx:33`: success lưu token/user.
- `SalonHub/backend/controllers/authController.js:188`: đọc email/password;
  tìm account theo email **hoặc phone**, không có normalize trong controller.
- Cùng file:198: account không tồn tại hoặc `isActive === false` trả 401.
- Cùng file:204: bcrypt password không khớp cũng trả 401.
- Cùng file:211: account tồn tại/không inactive/password khớp trả 200.

Không thể chọn chính xác nhánh 401 chỉ từ status + success=false. Password
khớp giữa hai lượt không chứng minh password hợp lệ cho **định danh khác**.
Đã chứng minh payload credential khác nhau; chưa chứng minh record DB cụ thể
hoặc cần sửa giá trị nào. Chưa thay đổi bất kỳ cấu hình nào.

## Chạy lại chẩn đoán

```bash
uv run python scripts/diagnose_login_differential.py \
  --config qctool.customer.e2e.yaml \
  --testcases artifacts/customer-workflow-evidence-90s/testcases.yaml \
  --case-id TC_CUSTOMER_001 --manual-wait-seconds 300 \
  --exploration-audit artifacts/customer-workflow-evidence-90s/generation.json \
  --exploration-trace AC-customer-001-5 \
  --out artifacts/login-differential-confirmed/report.json
```

Nhập tài khoản thật vào cửa sổ headed đầu tiên; không gửi credential vào chat.
Recorded audit chỉ cung cấp **plan đã duyệt** để replay prerequisite thật;
không phải recorded network completion, không có LLM call.
Script không lưu screenshot, HAR, trace, body values, cookie/header values.
Chỉ lưu schema JSON, success boolean, status và metadata/HMAC equality booleans.
Exit 0 khi có một successful reference JSON và một matching QC request;
exit 2 nếu thiếu/ambiguous reference. Không auto-correct hoặc sửa testcase.

## Kiểm tra

`uv run pytest tests/test_login_differential.py tests/test_browser.py
tests/test_ui_response_capture.py tests/test_test_fixtures.py
tests/test_resolution_benchmark.py tests/test_generation_benchmark.py -q`

Kết quả: **142 passed**, gồm Chromium local và benchmark offline.
